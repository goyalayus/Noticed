# gemini_client.py

import google.generativeai as genai
import logging
import os
from pathlib import Path
import asyncio
# Import exceptions for more specific handling if needed
from google.api_core import exceptions as api_core_exceptions
from google.generativeai.types import generation_types

logger = logging.getLogger(__name__)

# --- Configuration ---
# GEMINI_MODEL_NAME = 'gemini-1.5-flash-latest' # Try this if Pro continues to fail
GEMINI_MODEL_NAME = 'gemini-2.5-pro-exp-03-25'
MAX_REPLY_LENGTH = 280

# --- Safety Settings ---
# Let's try WITH DEFAULTS first, like temp.py
# If this still fails, uncommenting BLOCK_NONE can be tried again,
# but default is often safer and sometimes avoids unexpected policy blocks.
SAFETY_SETTINGS = None
# SAFETY_SETTINGS = {
#     genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
#     genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
#     genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
#     genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
# }

# --- Prompt Template (Keep as is) ---
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
    """Interacts with the Google Gemini API asynchronously."""

    def __init__(self, api_key: str, speaking_style_path: Path):
        if not api_key:
            raise ValueError("Gemini API key is required.")
        if not speaking_style_path or not isinstance(speaking_style_path, Path):
            raise ValueError("Speaking style file path (as a Path object) is required.")

        self.api_key = api_key
        self.speaking_style_path = speaking_style_path
        self.speaking_style = ""
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
        # ... (keep existing load_speaking_style method) ...
        if not self.speaking_style_path.is_file():
            logger.error(f"Speaking style file not found: {self.speaking_style_path}")
            raise FileNotFoundError(f"Speaking style file not found: {self.speaking_style_path}")
        try:
            with open(self.speaking_style_path, 'r', encoding='utf-8') as f:
                self.speaking_style = f.read()
            if not self.speaking_style.strip():
                logger.error(f"Speaking style file '{self.speaking_style_path}' is empty.")
                raise ValueError(f"Speaking style file '{self.speaking_style_path}' is empty.")
            logger.info(f"Successfully loaded speaking style from {self.speaking_style_path} ({len(self.speaking_style)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to load speaking style from '{self.speaking_style_path}': {e}", exc_info=True)
            self.speaking_style = ""
            raise


    async def generate_reply(self, tweet_text: str) -> str | None:
        """Generates a reply using Gemini based on the tweet and speaking style."""
        if not self.model:
             logger.error("Gemini model not initialized. Cannot generate reply.")
             return None
        if not self.speaking_style:
             logger.error("Speaking style not loaded. Cannot generate reply.")
             return None
        if not tweet_text or not tweet_text.strip():
            logger.warning("Received empty or whitespace-only tweet text. Cannot generate reply.")
            return None

        try:
            full_prompt = INSTRUCTION_TEMPLATE.format(
                max_chars=MAX_REPLY_LENGTH,
                speaking_style=self.speaking_style,
                tweet_text=tweet_text
            )
        except KeyError as e:
            logger.error(f"Error formatting Gemini prompt template (missing key?): {e}")
            return None

        logger.info(f"Sending request to Gemini (model: {self.model_name}) for tweet: \"{tweet_text[:50].strip()}...\"")
        # logger.debug(f"Full prompt being sent:\n{full_prompt}") # Uncomment for extreme debugging

        response = None # Initialize response variable
        try:
            # --- Generate content using the async method ---
            # Simplified call: Removed generation_config for now, using SAFETY_SETTINGS defined above (currently None/default)
            response = await self.model.generate_content_async(
                contents=full_prompt,
                safety_settings=SAFETY_SETTINGS
                # generation_config=genai.types.GenerationConfig(
                #     # candidate_count=1, # Default is usually 1
                #     # stop_sequences=['\n'],
                #     max_output_tokens=150, # Keep a reasonable token limit
                #     temperature=0.7,
                # ),
            )

            # --- More Robust Response Handling ---
            generated_text = None

            # Check if candidates exist *before* trying .text
            if not response.candidates:
                logger.warning("Gemini response has NO candidates.")
                # Log detailed feedback if available
                try:
                    feedback = response.prompt_feedback
                    logger.warning(f"Prompt Feedback: Block Reason: {feedback.block_reason}, Safety Ratings: {feedback.safety_ratings}")
                except (AttributeError, ValueError) as feedback_err:
                    logger.warning(f"Could not retrieve detailed prompt feedback: {feedback_err}")
                return None # Definitely no text if no candidates

            # If candidates exist, *then* try accessing text
            try:
                 # This still might raise ValueError if the *single* candidate is blocked/invalid,
                 # but we know the list wasn't empty.
                 generated_text = response.text
            except ValueError as ve:
                 # This indicates blocking/issues even with candidates present
                 logger.warning(f"Accessing response.text failed. Error: {ve}")
                 # Log candidate details if possible
                 try:
                     for candidate in response.candidates:
                          logger.warning(f"Candidate details: Finish Reason: {candidate.finish_reason}, Safety Ratings: {candidate.safety_ratings}")
                 except Exception as cand_exc:
                     logger.warning(f"Could not log candidate details: {cand_exc}")
                 return None # Blocked or invalid content
            except Exception as text_exc:
                 logger.warning(f"Unexpected error accessing response.text: {text_exc}", exc_info=True)
                 return None # Other unexpected error


            # --- Process Valid Text ---
            if generated_text:
                trimmed_text = generated_text.strip()
                if trimmed_text:
                    # Truncate if needed
                    if len(trimmed_text) > MAX_REPLY_LENGTH:
                        logger.warning(f"Gemini response exceeded {MAX_REPLY_LENGTH} chars ({len(trimmed_text)}). Truncating.")
                        trimmed_text = trimmed_text[:MAX_REPLY_LENGTH]

                    # Minimal check for unwanted boilerplate (adapt if needed)
                    if trimmed_text.lower().startswith(("generated reply:", "reply:")):
                        logger.warning("Removing potential boilerplate prefix from reply.")
                        trimmed_text = trimmed_text.split(":", 1)[-1].strip()

                    if trimmed_text:
                       logger.info(f"Successfully generated reply: \"{trimmed_text}\"")
                       return trimmed_text
                    else:
                       logger.warning("Gemini response became empty after cleaning/truncating.")
                       return None
                else:
                    logger.warning("Gemini response via .text was empty or whitespace.")
                    return None
            else:
                # This case should be less likely now with the candidate check above
                logger.warning("Response.text was unexpectedly empty/None despite having candidates.")
                return None


        # --- Handle API Call Exceptions ---
        except generation_types.StopCandidateException as sce:
             # Specific exception if candidate stopped early (e.g., safety)
             logger.warning(f"Gemini generation stopped unexpectedly (likely safety/policy). StopCandidateException: {sce}")
             if response: # Log feedback if response object exists
                 try: logger.warning(f"Prompt Feedback: {response.prompt_feedback}")
                 except Exception: pass
                 try: logger.warning(f"Candidates: {response.candidates}")
                 except Exception: pass
             return None
        except api_core_exceptions.GoogleAPIError as api_err:
            # Catch potential errors from the API call itself (network, auth, quota, etc.)
            logger.error(f"Gemini API call failed: {type(api_err).__name__} - {api_err}", exc_info=True)
            return None
        except Exception as e:
            # Catch any other unexpected errors during generation/processing
            logger.error(f"Unexpected error during Gemini generation or response processing: {e}", exc_info=True)
            if response: # Log response details if available
                 logger.error(f"Response object at time of error: {response!r}")
            return None
