import google.generativeai as genai
import logging
import os
from pathlib import Path
import asyncio
import aiofiles
import aiohttp # For fetching images
from PIL import Image # For image type detection
import io # For working with bytes as files

from google.generativeai import types as generation_types
from google.api_core import exceptions as api_core_exceptions


logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = 'gemini-2.5-pro-preview-05-06'
MAX_REPLY_LENGTH = 140 # As defined in the original bot, not in the simple prompt template.

SAFETY_SETTINGS = None

# User-provided instruction template
INSTRUCTION_TEMPLATE = """You are an AI assistant generating Twitter replies based on a user's past style.
Generate a reply to the target tweet, adhering strictly to the provided speaking style.

Constraints:
- Max length: {max_chars} characters.
- Match the tone and vocabulary of the speaking style reference.
- Be humble and conversational if the style dictates.
- **CRITICAL: Output *ONLY* the raw tweet reply text.** No introductions, explanations, quotes, or extra formatting.

Speaking Style Reference Text:
--- START STYLE ---
{speaking_style}
--- END STYLE ---

Tweet to Reply To:
--- START TWEET ---
{tweet_text}
--- END TWEET ---

Generated Reply:"""


class GeminiClient:
    def __init__(self, api_key: str, speaking_style_path: Path): # Removed blog_content_path
        if not api_key:
            raise ValueError("Gemini API key is required.")
        if not speaking_style_path or not isinstance(speaking_style_path, Path):
            raise ValueError("Speaking style file path (as a Path object) is required.")

        self.api_key = api_key
        self.speaking_style_path = speaking_style_path
        self.speaking_style = ""
        # Removed self.blog_content_path and self.blog_content
        self.model = None
        self.model_name = GEMINI_MODEL_NAME

        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.model_name)
            logger.info(f"Gemini client configured for model: {self.model_name}")
        except Exception as e:
            logger.critical(f"FATAL: Failed to configure Gemini client or model '{self.model_name}': {e}", exc_info=True)
            raise ConnectionError(f"Failed to configure Gemini client: {e}") from e

    async def load_speaking_style(self) -> bool:
        if not self.speaking_style_path.is_file():
            logger.error(f"Speaking style file not found: {self.speaking_style_path}")
            raise FileNotFoundError(f"Speaking style file not found: {self.speaking_style_path}")
        try:
            async with aiofiles.open(self.speaking_style_path, 'r', encoding='utf-8') as f:
                self.speaking_style = await f.read()
            if not self.speaking_style.strip():
                logger.warning(f"Speaking style file '{self.speaking_style_path}' is empty. Replies may lack specific style.")
            logger.info(f"Successfully loaded speaking style from {self.speaking_style_path} ({len(self.speaking_style)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to load speaking style from '{self.speaking_style_path}': {e}", exc_info=True)
            self.speaking_style = ""
            raise

    # Removed load_blog_content method

    async def _fetch_image_data(self, image_url: str) -> tuple[bytes | None, str | None]:
        """Fetches image data and determines MIME type."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        try:
                            img = Image.open(io.BytesIO(image_bytes))
                            mime_type = Image.MIME.get(img.format.upper()) if img.format else None
                            if mime_type:
                                logger.info(f"Fetched image {image_url}, MIME (Pillow): {mime_type}, Size: {len(image_bytes)} bytes")
                                return image_bytes, mime_type
                            else:
                                server_content_type = resp.headers.get('Content-Type')
                                if server_content_type and server_content_type.startswith('image/'):
                                     logger.warning(f"Pillow couldn't determine MIME for {image_url} (format: {img.format}), using server's {server_content_type}")
                                     return image_bytes, server_content_type
                                else:
                                     logger.warning(f"Could not determine valid image MIME type for {image_url} from Pillow or server header ({server_content_type}).")
                                     return None, None
                        except Exception as e_pil:
                            logger.warning(f"Pillow error processing image {image_url}: {e_pil}. Falling back to server Content-Type if available.")
                            server_content_type = resp.headers.get('Content-Type')
                            if server_content_type and server_content_type.startswith('image/'):
                                return image_bytes, server_content_type
                            else:
                                logger.warning(f"Failed to determine MIME type for {image_url} after Pillow error and invalid server Content-Type ({server_content_type}).")
                                return None, None
                    else:
                        logger.warning(f"Failed to fetch image {image_url}, status: {resp.status}")
                        return None, None
        except Exception as e:
            logger.error(f"Error fetching image {image_url}: {e}", exc_info=True)
            return None, None


    async def generate_reply(self, tweet_text: str, image_urls: list[str] | None = None) -> str | None:
        if not self.model:
             logger.error("Gemini model not initialized.")
             return None
        if not self.speaking_style and self.speaking_style_path.exists(): # Check if speaking style loaded
             logger.error("Speaking style not loaded (file exists but content is empty or load failed).")
             return None
        # Removed blog_content check

        try:
            # Use the new INSTRUCTION_TEMPLATE
            # MAX_REPLY_LENGTH is used for truncation after generation, and in the prompt
            prompt_text_part = INSTRUCTION_TEMPLATE.format(
                max_chars=MAX_REPLY_LENGTH, # max_chars placeholder is in the new template
                speaking_style=self.speaking_style,
                tweet_text=tweet_text or "[No text content in tweet]"
                # Removed blog_content
            )
        except KeyError as e:
            logger.error(f"Error formatting Gemini prompt template (missing key?): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error formatting Gemini prompt template: {e}", exc_info=True)
            return None

        prompt_parts_for_api: list[str | dict] = [prompt_text_part]

        if image_urls:
            image_added_context = False
            for img_url in image_urls[:1]: # Process only the first image
                image_bytes, mime_type = await self._fetch_image_data(img_url)
                if image_bytes and mime_type:
                    try:
                        import base64
                        encoded_image_data = base64.b64encode(image_bytes).decode('utf-8')
                        image_part_dict = {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded_image_data
                            }
                        }
                        # Prepend image part so it appears before the "Generated Reply:" cue from the prompt
                        prompt_parts_for_api.insert(0, image_part_dict)
                        # Add a textual cue about the image *after* the image, but *before* the main prompt text.
                        # This is a bit of a hack to fit the simpler prompt structure.
                        # A more robust solution might involve a more complex prompt_parts construction.
                        # For now, let's try putting it directly before the main text part.
                        # This means the image part will be first, then this text cue, then the main prompt.
                        prompt_parts_for_api.insert(1, {"text": "\n[The above image was provided with the tweet. Consider it in your reply.]\n"})
                        image_added_context = True
                        logger.info(f"Added image {img_url} to Gemini prompt parts.")
                        break
                    except Exception as e:
                        logger.error(f"Error preparing image data for {img_url}: {e}")
            if not image_added_context and image_urls:
                 # If image processing failed, add a note to the text prompt part for the LLM
                 # This needs to be done carefully to not break the main prompt's structure
                 # Let's append it to the main prompt_text_part before it's added to prompt_parts_for_api
                 # For simplicity, we'll add a simple text part to prompt_parts_for_api
                 prompt_parts_for_api.append({"text": "\n[An image was linked in the tweet but could not be processed for context.]"})


        logger.info(f"Sending request to Gemini (model: {self.model_name}) for text: \"{(tweet_text or '')[:50].strip()}...\" (Images: {len(image_urls or [])})")
        
        response = None
        try:
            use_max_output_tokens_none = "preview" in self.model_name.lower()
            
            gen_config_args = {"temperature": 0.65}
            if use_max_output_tokens_none:
                # For preview models that might not support max_output_tokens=None well,
                # or if we want to cap output, let's set a reasonable limit.
                # The prompt already asks for MAX_REPLY_LENGTH.
                gen_config_args["max_output_tokens"] = None # Allow some buffer
                logger.info(f"Using max_output_tokens={gen_config_args['max_output_tokens']} for preview model {self.model_name}")
            else:
                gen_config_args["max_output_tokens"] = None # Allow some buffer

            current_generation_config = generation_types.GenerationConfig(**gen_config_args)

            response = await self.model.generate_content_async(
                contents=prompt_parts_for_api,
                safety_settings=SAFETY_SETTINGS,
                generation_config=current_generation_config
            )
            generated_text = None
            if not response.candidates:
                logger.warning("Gemini response has NO candidates.")
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                     logger.warning(f"Prompt Feedback: Block Reason: {response.prompt_feedback.block_reason}, Ratings: {response.prompt_feedback.safety_ratings}")
                return None

            try:
                 generated_text = response.text
            except ValueError as ve:
                 logger.warning(f"Accessing response.text failed. ValueError: {ve}")
                 if response.candidates:
                     for i, candidate in enumerate(response.candidates):
                          finish_reason_name = candidate.finish_reason.name if candidate.finish_reason else 'N/A'
                          logger.warning(f"  Candidate {i}: Finish Reason: {finish_reason_name}, Safety Ratings: {candidate.safety_ratings}")
                 return None
            except Exception as text_exc:
                 logger.warning(f"Unexpected error accessing response.text: {text_exc}", exc_info=True)
                 return None

            if generated_text:
                # The new prompt ends with "Generated Reply:", so the model should ideally just output the reply.
                # However, it might still sometimes add prefixes.
                trimmed_text = generated_text.strip().replace('"', '') # Keep basic quote removal
                
                # Prefixes to remove, in case model still adds them despite "Generated Reply:" cue
                prefixes_to_remove = [
                    "Generated Reply (as Ayush Goyal):", "Generated Reply:",
                    "Reply (as Ayush Goyal):", "Reply:", "Ayush Goyal:",
                    "Okay, here's a reply:", "Here's a reply:",
                    "Okay, as Ayush Goyal, my reply would be:",
                    "As Ayush Goyal:" # Adding simpler prefixes
                ]
                for prefix in prefixes_to_remove:
                    if trimmed_text.lower().startswith(prefix.lower()):
                        trimmed_text = trimmed_text[len(prefix):].strip()
                        break
                
                if trimmed_text:
                    if len(trimmed_text) > MAX_REPLY_LENGTH:
                        logger.warning(f"Gemini response was long ({len(trimmed_text)} chars). Truncating to {MAX_REPLY_LENGTH}.")
                        # Smart truncation (at last space)
                        last_space_index = trimmed_text[:MAX_REPLY_LENGTH].rfind(' ')
                        if last_space_index != -1 and last_space_index > MAX_REPLY_LENGTH - 30:
                            trimmed_text = trimmed_text[:last_space_index]
                        else: 
                            trimmed_text = trimmed_text[:MAX_REPLY_LENGTH]
                    
                    if trimmed_text: # Check again after potential truncation
                       logger.info(f"Successfully generated reply: \"{trimmed_text}\"")
                       return trimmed_text
                    else:
                       logger.warning("Gemini response became empty after truncation.")
                       return None
                else:
                    logger.warning("Gemini response was empty or whitespace after prefix removal.")
                    return None
            else:
                logger.warning("Response.text was unexpectedly empty/None despite having candidates (or after .text access issues).")
                return None

        except generation_types.StopCandidateException as sce:
             logger.warning(f"Gemini generation stopped (likely safety/policy). StopCandidateException: {sce}")
             if response and hasattr(response, 'prompt_feedback'):
                 try: logger.warning(f"Prompt Feedback: {response.prompt_feedback}")
                 except: pass
             return None
        except aiohttp.ClientError as http_err:
            logger.error(f"HTTP error fetching image for multimodal prompt: {http_err}", exc_info=True)
            return None
        except api_core_exceptions.InvalidArgument as iae:
            logger.error(f"Gemini API InvalidArgument: {iae}. Prompt (text + image) might be too large or malformed.", exc_info=True)
            return None
        except api_core_exceptions.DeadlineExceeded as dee:
            logger.error(f"Gemini API DeadlineExceeded: {dee}. Request took too long.", exc_info=True)
            return None
        except generation_types.BlockedPromptException as bpe:
            logger.error(f"Gemini prompt was explicitly blocked by API. BlockedPromptException: {bpe}")
            if response and hasattr(response, 'prompt_feedback'):
                 logger.warning(f"Prompt Feedback: {response.prompt_feedback}")
            return None
        except generation_types.UnsupportedUserLocation as uul:
            logger.error(f"Gemini API: User location not supported. UnsupportedUserLocation: {uul}")
            return None
        except api_core_exceptions.GoogleAPIError as api_err:
            logger.error(f"Gemini API call failed: {type(api_err).__name__} - {api_err}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Gemini generation or response processing: {e}", exc_info=True)
            if response:
                 logger.error(f"Response object at time of error: {response!r}")
            return None
