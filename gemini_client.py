# gemini_client.py

import google.generativeai as genai
import logging
import os
from pathlib import Path
import asyncio
import aiofiles # For async file reading
from google.api_core import exceptions as api_core_exceptions
from google.generativeai.types import generation_types

logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = 'gemini-2.5-flash-preview-05-20' # Or 'gemini-1.5-pro-latest' if Flash struggles
MAX_REPLY_LENGTH = 280

SAFETY_SETTINGS = {
    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
}

# --- Enhanced Prompt Template for Ayush Goyal ---
INSTRUCTION_TEMPLATE = """You are Ayush Goyal, a 20-year-old software developer from IIT Roorkee with aspirations to be a founder.
You are active on Twitter, sharing thoughtful perspectives and engaging in discussions related to technology, startups, product development, and occasionally, personal growth and philosophical musings.
The goal of your Twitter replies is to provide value, sound knowledgeable and insightful (drawing from the kind of thinking and analysis present in your blog content below), and encourage meaningful interactions that might lead to new followers.

**Your Knowledge Base (Consider this as your past writings and thoughts):**
--- START BLOG CONTENT ---
{blog_content}
--- END BLOG CONTENT ---

**Your Typical Twitter Speaking Style (Tone, Phrasing, Vocabulary):**
--- START SPEAKING STYLE ---
{speaking_style}
--- END SPEAKING STYLE ---

**Task:** Generate a reply to the target tweet.

**Guidelines for Replying:**

1.  **Persona & Knowledge Integration:**
    *   Embody Ayush Goyal: young, intelligent, ambitious, technically inclined but with broad interests.
    *   When forming your reply, subtly draw upon insights, analysis styles, or topics covered in the 'BLOG CONTENT' section as if they are your own well-considered thoughts. You don't need to directly quote, but the *spirit* and *depth* should be reflected.
    *   Showcase understanding relevant to the tweet's topic, informed by your "blog content."

2.  **Interaction Style (Choose one or blend appropriately):**
    *   **Compliment:** Offer a genuine, specific compliment to the original tweet or tweeter, perhaps relating it to a theme from your blog content.
    *   **Ask a Good Question:** Pose a thoughtful, open-ended question that invites discussion or deeper reflection, potentially inspired by questions your blog content might implicitly raise.
    *   **Opinionated but Knowledgeable Perspective:** Share a concise, well-reasoned opinion or insight. This is a key opportunity to use the "blog content" as a foundation for your take. Ensure it's presented humbly.

3.  **Tone & Speaking Style Adherence:**
    *   Maintain a humble and conversational tone, even when sharing strong opinions.
    *   Strictly follow the tone, phrasing, and vocabulary exemplified in the 'SPEAKING STYLE' section. This is how Ayush typically communicates on Twitter.

4.  **Constraints:**
    *   Maximum reply length: {max_chars} characters.
    *   **CRITICAL: Output *ONLY* the raw tweet reply text.** No introductions ("Here's a reply:"), explanations, salutations, or any extra formatting. Just the reply itself.

**Tweet to Reply To:**
--- START TWEET ---
{tweet_text}
--- END TWEET ---

**Generated Reply (as Ayush Goyal):**"""


class GeminiClient:
    """Interacts with the Google Gemini API asynchronously."""

    def __init__(self, api_key: str, speaking_style_path: Path, blog_content_path: Path): # <<< MODIFIED
        if not api_key:
            raise ValueError("Gemini API key is required.")
        if not speaking_style_path or not isinstance(speaking_style_path, Path):
            raise ValueError("Speaking style file path (as a Path object) is required.")
        if not blog_content_path or not isinstance(blog_content_path, Path): # <<< NEW
            raise ValueError("Blog content file path (as a Path object) is required.")

        self.api_key = api_key
        self.speaking_style_path = speaking_style_path
        self.blog_content_path = blog_content_path # <<< NEW
        self.speaking_style = ""
        self.blog_content = "" # <<< NEW
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
        """Loads the speaking style from the file."""
        if not self.speaking_style_path.is_file():
            logger.error(f"Speaking style file not found: {self.speaking_style_path}")
            raise FileNotFoundError(f"Speaking style file not found: {self.speaking_style_path}")
        try:
            async with aiofiles.open(self.speaking_style_path, 'r', encoding='utf-8') as f:
                self.speaking_style = await f.read()
            if not self.speaking_style.strip():
                logger.warning(f"Speaking style file '{self.speaking_style_path}' is empty. Replies might lack specific style.")
                # Allow empty style file, but log a warning.
            logger.info(f"Successfully loaded speaking style from {self.speaking_style_path} ({len(self.speaking_style)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to load speaking style from '{self.speaking_style_path}': {e}", exc_info=True)
            self.speaking_style = "" # Ensure it's reset on failure
            raise

    async def load_blog_content(self) -> bool: # <<< NEW METHOD
        """Loads the blog content from the file."""
        if not self.blog_content_path.is_file():
            logger.error(f"Blog content file not found: {self.blog_content_path}")
            raise FileNotFoundError(f"Blog content file not found: {self.blog_content_path}")
        try:
            async with aiofiles.open(self.blog_content_path, 'r', encoding='utf-8') as f:
                self.blog_content = await f.read()
            if not self.blog_content.strip():
                logger.error(f"Blog content file '{self.blog_content_path}' is empty.")
                # This is a critical error if we intend to use it as knowledge base
                raise ValueError(f"Blog content file '{self.blog_content_path}' is empty.")
            logger.info(f"Successfully loaded blog content from {self.blog_content_path} ({len(self.blog_content)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to load blog content from '{self.blog_content_path}': {e}", exc_info=True)
            self.blog_content = "" # Ensure it's reset on failure
            raise

    async def generate_reply(self, tweet_text: str) -> str | None:
        """Generates a reply using Gemini based on the tweet, speaking style, and blog content."""
        if not self.model:
             logger.error("Gemini model not initialized. Cannot generate reply.")
             return None
        if not self.speaking_style and self.speaking_style_path.exists(): # Check if path exists to differentiate from empty file
             logger.error("Speaking style not loaded. Cannot generate reply effectively.")
             # Consider an attempt to load, or rely on startup loading
             return None
        if not self.blog_content: # <<< NEW CHECK
             logger.error("Blog content not loaded. Cannot generate reply effectively.")
             return None
        if not tweet_text or not tweet_text.strip():
            logger.warning("Received empty or whitespace-only tweet text. Cannot generate reply.")
            return None

        try:
            full_prompt = INSTRUCTION_TEMPLATE.format(
                max_chars=MAX_REPLY_LENGTH,
                speaking_style=self.speaking_style,
                blog_content=self.blog_content, # <<< NEW
                tweet_text=tweet_text
            )
        except KeyError as e:
            logger.error(f"Error formatting Gemini prompt template (missing key?): {e}")
            return None
        except Exception as e: # Catch other formatting errors
            logger.error(f"Unexpected error formatting Gemini prompt template: {e}", exc_info=True)
            return None


        logger.info(f"Sending request to Gemini (model: {self.model_name}) for tweet: \"{tweet_text[:50].strip()}...\"")
        # logger.debug(f"Prompt length: {len(full_prompt)}") # Good to log for very long prompts
        # if len(full_prompt) > 700000: # Example threshold
            # logger.warning(f"Full prompt is very long ({len(full_prompt)} chars). This might impact performance or cost.")
            # For extreme debug: logger.debug(f"Full prompt being sent:\n{full_prompt}")


        response = None
        try:
            response = await self.model.generate_content_async(
                contents=full_prompt,
                safety_settings=SAFETY_SETTINGS,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=None, # Max 280 chars, ~120 tokens allows for some buffer
                    temperature=0.65 # Slightly less deterministic, more conversational for Ayush
                )
            )

            generated_text = None
            if not response.candidates:
                logger.warning("Gemini response has NO candidates.")
                try:
                    feedback = response.prompt_feedback
                    logger.warning(f"Prompt Feedback: Block Reason: {feedback.block_reason}, Safety Ratings: {feedback.safety_ratings}")
                except (AttributeError, ValueError) as feedback_err:
                    logger.warning(f"Could not retrieve detailed prompt feedback: {feedback_err}")
                return None

            try:
                 generated_text = response.text
            except ValueError as ve: # Often indicates content blocked
                 logger.warning(f"Accessing response.text failed. ValueError: {ve}")
                 logger.warning("This usually means the response was blocked by safety filters or other generation issues.")
                 try:
                     for i, candidate in enumerate(response.candidates):
                          logger.warning(f"  Candidate {i}: Finish Reason: {candidate.finish_reason}, Safety Ratings: {candidate.safety_ratings}")
                          if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                            for part_i, part in enumerate(candidate.content.parts):
                                logger.warning(f"    Part {part_i} text: {getattr(part, 'text', 'N/A')}")
                 except Exception as cand_exc:
                     logger.warning(f"Could not log detailed candidate information: {cand_exc}")
                 return None
            except Exception as text_exc:
                 logger.warning(f"Unexpected error accessing response.text: {text_exc}", exc_info=True)
                 return None

            if generated_text:
                trimmed_text = generated_text.strip().replace('"', '')
                prefixes_to_remove = [
                    "Generated Reply (as Ayush Goyal):",
                    "Generated Reply:",
                    "Reply (as Ayush Goyal):",
                    "Reply:",
                    "Ayush Goyal:"
                    "Okay, here's a reply:",
                    "Here's a reply:"
                ]
                for prefix in prefixes_to_remove:
                    if trimmed_text.lower().startswith(prefix.lower()):
                        trimmed_text = trimmed_text[len(prefix):].strip()
                        break

                if trimmed_text:
                    if len(trimmed_text) > MAX_REPLY_LENGTH:
                        logger.warning(f"Gemini response exceeded {MAX_REPLY_LENGTH} chars ({len(trimmed_text)}). Truncating.")
                        trimmed_text = trimmed_text[:MAX_REPLY_LENGTH]

                    if trimmed_text:
                       logger.info(f"Successfully generated reply (Ayush Goyal): \"{trimmed_text}\"")
                       return trimmed_text
                    else:
                       logger.warning("Gemini response (Ayush Goyal) became empty after cleaning/truncating.")
                       return None
                else:
                    logger.warning("Gemini response (Ayush Goyal) via .text was empty or whitespace after initial strip and prefix removal.")
                    return None
            else: # Should be caught by candidate check or .text exception
                logger.warning("Response.text (Ayush Goyal) was unexpectedly empty/None despite having candidates.")
                return None

        except generation_types.StopCandidateException as sce:
             logger.warning(f"Gemini generation stopped unexpectedly for Ayush (likely safety/policy). StopCandidateException: {sce}")
             if response:
                 try: logger.warning(f"Prompt Feedback: {response.prompt_feedback}")
                 except Exception: pass
                 try: logger.warning(f"Candidates: {response.candidates}")
                 except Exception: pass
             return None
        except api_core_exceptions.InvalidArgument as iae:
            logger.error(f"Gemini API InvalidArgument for Ayush: {iae}. Prompt might be too long or malformed.", exc_info=True)
            return None
        except api_core_exceptions.GoogleAPIError as api_err:
            logger.error(f"Gemini API call failed for Ayush: {type(api_err).__name__} - {api_err}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Gemini generation for Ayush: {e}", exc_info=True)
            if response:
                 logger.error(f"Response object at time of error (Ayush): {response!r}")
            return None
