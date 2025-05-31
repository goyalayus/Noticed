import logging
import time
import asyncio
import random
from twikit import Client as TwikitClient
from twikit.tweet import Tweet # Explicitly import Tweet for type hinting
from twikit.errors import NotFound, Forbidden, TwitterException

from state_manager import StateManager
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class Bot:
    def __init__(
        self,
        config: dict,
        twikit_client: TwikitClient,
        gemini_client: GeminiClient,
        state_manager: StateManager
    ):
        self.config = config
        self.twikit_client = twikit_client
        self.gemini_client = gemini_client
        self.state_manager = state_manager
        self.min_delay = config['min_reply_delay_seconds']
        self.max_delay = config['max_reply_delay_seconds']
        self.own_user_id = config.get('twitter_actual_user_id', None) # Get from config if set by main.py
        self.bot_screen_name = config.get('twitter_username', '').lstrip('@')


    async def _ensure_own_user_id(self): # Keep this for fallback if not set by main.py
        if self.own_user_id is None:
            bot_username_to_fetch = self.bot_screen_name
            if not bot_username_to_fetch:
                logger.error("Twitter username missing in config. Cannot fetch own user ID.")
                return
            try:
                logger.info(f"Fetching own user details for @{bot_username_to_fetch}...")
                me_user = await self.twikit_client.get_user_by_screen_name(bot_username_to_fetch)
                if me_user and me_user.id:
                    self.own_user_id = str(me_user.id)
                    logger.info(f"Fetched own user ID: {self.own_user_id} for @{me_user.screen_name}")
                else:
                    logger.error(f"Could not fetch valid user details for @{bot_username_to_fetch}.")
            except TwitterException as e:
                logger.error(f"Could not fetch own user details for @{bot_username_to_fetch} (Twikit Error): {e}.")
            except Exception as e:
                 logger.error(f"Unexpected error fetching own user details for @{bot_username_to_fetch}: {e}")


    async def run_iteration(self) -> None:
        logger.info("Starting bot iteration...")
        iteration_start_time = time.monotonic()
        processed_this_iteration = 0 # Renamed for clarity
        replied_this_iteration = 0   # Renamed for clarity
        errors_this_iteration = 0    # Renamed for clarity
        state_changed = False

        if not self.own_user_id: # Attempt to fetch if not available from config
            await self._ensure_own_user_id()

        tweets: list[Tweet] = [] # Ensure tweets is typed
        try:
            logger.info(f"Fetching up to {self.config['tweets_to_fetch']} tweets from latest timeline...")
            timeline_result = await self.twikit_client.get_latest_timeline(count=self.config['tweets_to_fetch'])

            if hasattr(timeline_result, '__aiter__'):
                 tweets = [t async for t in timeline_result]
            elif hasattr(timeline_result, '__iter__') and not isinstance(timeline_result, str):
                 tweets = list(timeline_result)
            else:
                 logger.warning(f"Unexpected type from get_latest_timeline: {type(timeline_result)}. Assuming empty.")
            
            if not tweets:
                 logger.info("No new tweets found in timeline fetch.")
                 return
            logger.info(f"Fetched {len(tweets)} tweets. Processing potential replies (oldest first)...")
        # ... (rest of the timeline fetching error handling as before) ...
        except AttributeError as e:
             logger.critical(f"FATAL: Method missing in twikit client (e.g., 'get_latest_timeline'): {e}", exc_info=True)
             raise
        except TypeError as e:
            logger.critical(f"FATAL: TypeError calling timeline fetch: {e}", exc_info=True)
            raise
        except TwitterException as e:
            logger.error(f"Failed to fetch Twitter timeline: {e}", exc_info=False)
            return
        except Exception as e:
            logger.error(f"An unexpected error during timeline fetch: {e}", exc_info=True)
            return

        for i, tweet_obj in enumerate(reversed(tweets)): # Use a more descriptive name
            if not isinstance(tweet_obj, Tweet) or not hasattr(tweet_obj, 'id'):
                 logger.warning(f"Skipping invalid timeline item (type: {type(tweet_obj)}): {tweet_obj!r}")
                 continue

            tweet_id_str = str(tweet_obj.id)
            
            tweet_author = getattr(tweet_obj, 'user', None)
            tweet_author_id = str(getattr(tweet_author, 'id', None)) if tweet_author else None
            tweet_author_handle = getattr(tweet_author, 'screen_name', 'unknown_user') if tweet_author else 'unknown_user'
            current_tweet_url = f"https://x.com/{tweet_author_handle}/status/{tweet_id_str}"

            logger.info(f"Checking tweet ({i+1}/{len(tweets)}): {current_tweet_url} by @{tweet_author_handle}")

            if self.state_manager.is_processed(tweet_id_str):
                logger.info(f"Skipping already processed tweet ID {tweet_id_str}")
                continue

            if self.own_user_id:
                if tweet_author_id == self.own_user_id:
                    logger.info(f"Skipping own tweet: {tweet_id_str}")
                    await self.state_manager.mark_processed(tweet_id_str); state_changed = True
                    continue
                
                reply_to_user_id_val = getattr(tweet_obj, 'in_reply_to_user_id_str', None)
                if reply_to_user_id_val == self.own_user_id:
                    logger.info(f"Skipping reply to self: {tweet_id_str}")
                    await self.state_manager.mark_processed(tweet_id_str); state_changed = True
                    continue
            
            processed_this_iteration += 1

            # --- Enhanced Context Extraction for Retweets and Quote Tweets ---
            text_for_gemini = getattr(tweet_obj, 'text', "") or ""
            image_urls_for_gemini = []

            # Helper to extract media URLs
            def get_media_urls(media_list):
                urls = []
                if media_list:
                    for media_item in media_list:
                        if getattr(media_item, 'type', None) == 'photo':
                            url = getattr(media_item, 'media_url_https', None)
                            if url: urls.append(url)
                return urls

            # Extract images from the current tweet object first
            image_urls_for_gemini.extend(get_media_urls(getattr(tweet_obj, 'media', None)))

            is_native_retweet = hasattr(tweet_obj, 'retweeted_status') and tweet_obj.retweeted_status is not None
            is_quote_tweet = hasattr(tweet_obj, 'quoted_status') and tweet_obj.quoted_status is not None

            if is_native_retweet:
                original_rt_status = tweet_obj.retweeted_status
                logger.info(f"Tweet {tweet_id_str} is a native retweet of {getattr(original_rt_status, 'id', 'N/A')}. Using original tweet's content.")
                text_for_gemini = getattr(original_rt_status, 'text', "") or ""
                # If the retweet itself had no media, check the original retweeted status for media
                if not image_urls_for_gemini:
                    image_urls_for_gemini.extend(get_media_urls(getattr(original_rt_status, 'media', None)))
            
            elif is_quote_tweet:
                quoted_status_obj = tweet_obj.quoted_status
                commenter_text = getattr(tweet_obj, 'text', "") or "" # Text added by the one quoting
                original_quoted_text = getattr(quoted_status_obj, 'text', "") or ""
                
                logger.info(f"Tweet {tweet_id_str} is a quote tweet. Quoted tweet ID: {getattr(quoted_status_obj, 'id', 'N/A')}. Combining texts.")
                text_for_gemini = (
                    f"Commenter's Text: {commenter_text}\n"
                    f"Original Quoted Text: {original_quoted_text}"
                )
                # Prioritize images from the quote tweet's comment if any, then from original quoted
                if not image_urls_for_gemini: # If tweet_obj.media (commenter's media) was empty
                    image_urls_for_gemini.extend(get_media_urls(getattr(quoted_status_obj, 'media', None)))

            if not text_for_gemini.strip() and not image_urls_for_gemini:
                logger.warning(f"Skipping tweet {tweet_id_str}: no effective text and no processable images after context extraction.")
                await self.state_manager.mark_processed(tweet_id_str); state_changed = True
                continue
            
            logger.info(f"Generating reply for tweet ID {tweet_id_str} (Text: '{text_for_gemini[:30].strip()}...', Images: {len(image_urls_for_gemini)})")
            reply_text = await self.gemini_client.generate_reply(text_for_gemini, image_urls_for_gemini)

            if not reply_text:
                logger.warning(f"Gemini did not return a reply for tweet {tweet_id_str}. Skipping post.")
                errors_this_iteration += 1
                await self.state_manager.mark_processed(tweet_id_str); state_changed = True
                continue

            logger.info(f"Attempting to post reply to tweet ID {tweet_id_str}...")
            try:
                if not hasattr(tweet_obj, 'reply') or not callable(tweet_obj.reply):
                    logger.error(f"Tweet object for ID {tweet_id_str} (user @{tweet_author_handle}) does not have a callable 'reply' method.")
                    errors_this_iteration += 1
                    await self.state_manager.mark_processed(tweet_id_str); state_changed = True
                    continue

                replied_tweet = await tweet_obj.reply(reply_text)
                replied_this_iteration += 1
                state_changed = True
                replied_tweet_id = getattr(replied_tweet, 'id', 'UNKNOWN_ID')
                logger.info(f"Successfully posted reply to {current_tweet_url}. New tweet ID: {replied_tweet_id}")
                await self.state_manager.mark_processed(tweet_id_str)

                is_last_tweet_in_batch = (i == len(tweets) - 1)
                if not is_last_tweet_in_batch and replied_this_iteration > 0:
                    delay = random.uniform(self.min_delay, self.max_delay)
                    logger.info(f"Waiting for {delay:.2f}s before next tweet...")
                    await asyncio.sleep(delay)

            except NotFound:
                 logger.warning(f"Original tweet {tweet_id_str} not found (NotFound error). Maybe deleted? Skipping.")
                 errors_this_iteration += 1
                 await self.state_manager.mark_processed(tweet_id_str); state_changed = True
            except Forbidden as e:
                 logger.error(f"Forbidden to reply to tweet {tweet_id_str}: {e}. Skipping.", exc_info=False)
                 errors_this_iteration += 1
                 await self.state_manager.mark_processed(tweet_id_str); state_changed = True
            except TwitterException as e:
                logger.error(f"Twitter API error posting reply for tweet {tweet_id_str}: {e}", exc_info=False)
                errors_this_iteration += 1
            except Exception as e:
                 logger.error(f"An unexpected error replying to {tweet_id_str}: {e}", exc_info=True)
                 errors_this_iteration += 1

        if state_changed:
            logger.info("Saving updated state...")
            await self.state_manager.save()

        iteration_duration = time.monotonic() - iteration_start_time
        logger.info(
            f"Iteration completed in {iteration_duration:.2f}s. "
            f"Tweets processed: {processed_this_iteration}, Replied: {replied_this_iteration}, Errors: {errors_this_iteration}."
        )
