import asyncio
import logging
import argparse
import re
from pathlib import Path

# Make sure these are accessible from your project structure
import config
from gemini_client import GeminiClient as BotGeminiClient # Alias to avoid confusion
from twikit import Client as TwikitClient
from twikit.tweet import Tweet
from twikit.errors import NotFound, Forbidden, TwitterException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger("explain_tweet")

# --- New Prompt Template for Explanation ---
EXPLANATION_PROMPT_TEMPLATE = """
You are an AI assistant. Your task is to explain the content of the provided tweet, including its text and any associated images.
The user wants to understand what the tweet is about.

**Your Knowledge Base (Consider this as context the user has previously written about, like blog posts):**
--- START BLOG CONTENT ---
{blog_content}
--- END BLOG CONTENT ---

**The user's typical Twitter Speaking Style (This is for context on *how* they usually communicate, but your task is to EXPLAIN, not emulate this style for the explanation itself):**
--- START SPEAKING STYLE ---
{speaking_style}
--- END SPEAKING STYLE ---

**Tweet to Explain (Text part):**
--- START TWEET TEXT ---
{tweet_text}
--- END TWEET TEXT ---

**Instructions for Explanation:**
1.  Analyze the provided tweet text.
2.  If an image is associated (indicated by a following image part in the prompt to Gemini), describe the image and explain how it relates to the tweet's text.
3.  If the tweet is a "Quote Tweet", the input text will be formatted as:
    "Commenter's Text: [Text added by the person quoting]
    Original Quoted Text: [Text of the tweet they are quoting]"
    Explain both the commenter's addition and the original quoted content, and their relationship.
4.  If the tweet is a "Native Retweet", the input text will be the content of the original tweet. Explain that original content.
5.  Provide a clear, concise explanation of the tweet's meaning, message, or observation.
6.  You can draw insights or make connections based on the provided "Knowledge Base" (blog content) if relevant to understanding the tweet's context, but primarily focus on explaining the tweet itself.
7.  **Output only the explanation.** No salutations or meta-commentary about your process.
"""

class ExplainerGeminiClient(BotGeminiClient):
    """
    Specialized Gemini client for generating explanations.
    Overrides the prompt template.
    """
    async def generate_explanation(self, tweet_text: str, image_urls: list[str] | None = None) -> str | None:
        if not self.model:
            logger.error("Gemini model not initialized.")
            return None
        # speaking_style and blog_content are loaded by parent's __init__ and load methods

        try:
            prompt_text_part = EXPLANATION_PROMPT_TEMPLATE.format(
                speaking_style=self.speaking_style, # Still needed for template
                blog_content=self.blog_content,     # Still needed for template
                tweet_text=tweet_text or "[No text content in tweet]"
            )
        except KeyError as e:
            logger.error(f"Error formatting explanation prompt template (missing key?): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error formatting explanation prompt template: {e}", exc_info=True)
            return None

        prompt_parts_for_api: list[str | dict] = [prompt_text_part]

        if image_urls:
            image_added_context = False
            for img_url in image_urls[:1]: # Process only the first image
                image_bytes, mime_type = await self._fetch_image_data(img_url) # Reuse parent's method
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
                        prompt_parts_for_api.append(image_part_dict)
                        prompt_parts_for_api.append({"text": "[The above image was included with the tweet. Explain its content and relation to the text.]"})
                        image_added_context = True
                        logger.info(f"Added image {img_url} to Gemini prompt parts for explanation.")
                        break
                    except Exception as e:
                        logger.error(f"Error preparing image data for explanation {img_url}: {e}")
            if not image_added_context and image_urls:
                prompt_parts_for_api.append({"text": "[An image was linked in the tweet but could not be processed for context.]"})

        logger.info(f"Sending request to Gemini for EXPLANATION of: \"{(tweet_text or '')[:50].strip()}...\" (Images: {len(image_urls or [])})")

        try:
            response = await self.model.generate_content_async(
                contents=prompt_parts_for_api,
                safety_settings=self.SAFETY_SETTINGS, # Use parent's safety settings
                generation_config=generation_types.GenerationConfig(temperature=0.3, max_output_tokens=500) # Explanation can be longer
            )

            if not response.candidates:
                logger.warning("Gemini explanation response has NO candidates.")
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    logger.warning(f"Prompt Feedback: Block Reason: {response.prompt_feedback.block_reason}, Ratings: {response.prompt_feedback.safety_ratings}")
                return None

            generated_text = response.text
            if generated_text:
                logger.info(f"Successfully generated explanation.")
                return generated_text.strip()
            else:
                logger.warning("Gemini explanation was empty.")
                return None

        except Exception as e:
            logger.error(f"Unexpected error during Gemini explanation generation: {e}", exc_info=True)
            return None


def parse_tweet_id_from_url(url: str) -> str | None:
    """Extracts tweet ID from a Twitter URL."""
    match = re.search(r"/status/(\d+)", url)
    if match:
        return match.group(1)
    return None

# Helper to get media URLs, adapted from bot.py
def get_media_urls(media_list):
    urls = []
    if media_list:
        for media_item in media_list:
            if getattr(media_item, 'type', None) == 'photo': # Focus on photos for Gemini
                url = getattr(media_item, 'media_url_https', None)
                if url: urls.append(url)
    return urls

async def main(tweet_url: str):
    logger.info(f"Attempting to explain tweet: {tweet_url}")

    cfg = None
    try:
        cfg = config.load_config()
    except (ValueError, FileNotFoundError) as e:
        logger.critical(f"Configuration error: {e}")
        return

    tweet_id_str = parse_tweet_id_from_url(tweet_url)
    if not tweet_id_str:
        logger.error(f"Could not parse tweet ID from URL: {tweet_url}")
        return

    logger.info(f"Parsed Tweet ID: {tweet_id_str}")

    # Initialize Twitter Client
    twikit_cli = None
    try:
        twikit_cli = TwikitClient('en-US')
        login_args = {
            'auth_info_1': cfg['twitter_username'],
            'password': cfg['twitter_password']
        }
        if cfg.get('twitter_email'):
            login_args['auth_info_2'] = cfg['twitter_email']

        # Use the Path object from config for cookies_file
        login_args['cookies_file'] = str(cfg['twitter_cookie_file_path'])
        
        logger.info(f"Attempting Twitter login...")
        await twikit_cli.login(**login_args)
        logger.info("Twitter login successful.")
    except Exception as e:
        logger.critical(f"Failed to login to Twitter: {e}")
        return

    # Initialize Gemini Client for Explanations
    explainer_gemini_cli = None
    try:
        explainer_gemini_cli = ExplainerGeminiClient(
            cfg['gemini_api_key'],
            cfg['speaking_style_file_path'],
            cfg['blog_content_file_path']
        )
        await explainer_gemini_cli.load_speaking_style() # Still load them as parent expects
        await explainer_gemini_cli.load_blog_content()
        logger.info("Explainer Gemini client initialized.")
    except Exception as e:
        logger.critical(f"Failed to initialize Explainer Gemini client: {e}")
        return

    # Fetch the specific tweet
    tweet_obj: Tweet | None = None
    try:
        logger.info(f"Fetching tweet by ID: {tweet_id_str}...")
        tweet_obj = await twikit_cli.get_tweet_by_id(int(tweet_id_str))
        if not tweet_obj:
            logger.error(f"Tweet with ID {tweet_id_str} not found.")
            return
        logger.info(f"Successfully fetched tweet: {tweet_obj.id}")
    except NotFound:
        logger.error(f"Tweet {tweet_id_str} not found (NotFound error).")
        return
    except Forbidden as e:
        logger.error(f"Forbidden to access tweet {tweet_id_str}: {e}.")
        return
    except TwitterException as e:
        logger.error(f"Twitter API error fetching tweet {tweet_id_str}: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error fetching tweet {tweet_id_str}: {e}", exc_info=True)
        return

    # --- Context Extraction (adapted from bot.py) ---
    text_for_gemini = getattr(tweet_obj, 'text', "") or ""
    image_urls_for_gemini = []

    # Extract images from the current tweet object first
    image_urls_for_gemini.extend(get_media_urls(getattr(tweet_obj, 'media', None)))

    is_native_retweet = hasattr(tweet_obj, 'retweeted_status') and tweet_obj.retweeted_status is not None
    is_quote_tweet = hasattr(tweet_obj, 'quoted_status') and tweet_obj.quoted_status is not None

    original_tweet_text_for_log = text_for_gemini # For logging

    if is_native_retweet:
        original_rt_status = tweet_obj.retweeted_status
        rt_id = getattr(original_rt_status, 'id', 'N/A')
        logger.info(f"Tweet {tweet_id_str} is a native retweet of {rt_id}. Using original tweet's content for explanation.")
        text_for_gemini = getattr(original_rt_status, 'text', "") or ""
        if not image_urls_for_gemini: # If the RT itself had no image
            image_urls_for_gemini.extend(get_media_urls(getattr(original_rt_status, 'media', None)))
        original_tweet_text_for_log = f"Retweet of: {text_for_gemini}"

    elif is_quote_tweet:
        quoted_status_obj = tweet_obj.quoted_status
        qt_id = getattr(quoted_status_obj, 'id', 'N/A')
        commenter_text = getattr(tweet_obj, 'text', "") or ""
        original_quoted_text = getattr(quoted_status_obj, 'text', "") or ""
        
        logger.info(f"Tweet {tweet_id_str} is a quote tweet of {qt_id}. Combining texts for explanation.")
        text_for_gemini = (
            f"Commenter's Text: {commenter_text}\n"
            f"Original Quoted Text: {original_quoted_text}"
        )
        if not image_urls_for_gemini: # If the quote comment had no image
            image_urls_for_gemini.extend(get_media_urls(getattr(quoted_status_obj, 'media', None)))
        original_tweet_text_for_log = text_for_gemini


    if not text_for_gemini.strip() and not image_urls_for_gemini:
        logger.warning(f"Skipping explanation for tweet {tweet_id_str}: no effective text and no processable images after context extraction.")
        return

    logger.info(f"Tweet content for Gemini: '{original_tweet_text_for_log[:100].strip()}...', Images: {len(image_urls_for_gemini)}")
    if image_urls_for_gemini:
        logger.info(f"Image URLs: {image_urls_for_gemini}")

    # Generate explanation
    explanation = await explainer_gemini_cli.generate_explanation(text_for_gemini, image_urls_for_gemini)

    if explanation:
        print("\n--- Explanation from Gemini ---")
        print(explanation)
        print("-----------------------------")
    else:
        print("\n--- Gemini could not generate an explanation. ---")

    # Close twitter client (optional, but good practice if script does one-off tasks)
    if twikit_cli and hasattr(twikit_cli, 'close'):
        try:
            await twikit_cli.close()
            logger.info("Closed Twitter client session.")
        except Exception as e:
            logger.warning(f"Error closing twikit client: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explain a tweet (including retweets/quotes with images) using Gemini.")
    parser.add_argument("tweet_url", help="The URL of the tweet to explain.")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.tweet_url))
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
    except Exception as e:
        logger.critical(f"Unhandled exception in script: {e}", exc_info=True)
