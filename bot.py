import logging
import time
import asyncio
import random
from twikit import Client as TwikitClient
from twikit.tweet import Tweet # Import Tweet type hint

# Try importing NotFound, fall back to base exception if needed
try:
    from twikit.errors import NotFound, Forbidden, TwitterException
except ImportError:
    # If NotFound doesn't exist, just import the others
    from twikit.errors import Forbidden, TwitterException
    NotFound = None # Define NotFound as None so the except block can check

from state_manager import StateManager
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

class Bot:
    """Orchestrates the bot's main logic."""

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
        self.own_user_id = None # Initialize own user ID


    async def _ensure_own_user_id(self):
        """Fetches and caches the bot's own user ID if not already done."""
        if self.own_user_id is None:
            bot_username = self.config.get('twitter_username', '').lstrip('@')
            if not bot_username:
                logger.error("Twitter username missing in config. Cannot fetch own user ID.")
                return

            try:
                logger.info(f"Fetching own user details for @{bot_username}...")
                me_user = await self.twikit_client.get_user_by_screen_name(bot_username)
                if me_user and me_user.id:
                    self.own_user_id = me_user.id
                    logger.info(f"Fetched own user ID: {self.own_user_id}")
                else:
                    logger.error(f"Could not fetch valid user details for @{bot_username}.")
            except TwitterException as e:
                logger.error(f"Could not fetch own user details for @{bot_username}: {e}. Self-checks will be skipped.")
            except AttributeError:
                logger.error(f"Could not fetch own user details for @{bot_username} due to missing 'get_user_by_screen_name' method or user attributes.")
            except Exception as e:
                 logger.error(f"Unexpected error fetching own user details for @{bot_username}: {e}")


    async def run_iteration(self) -> None:
        """Performs one cycle of fetching, generating, and replying."""
        logger.info("Starting bot iteration...")
        iteration_start_time = time.monotonic()
        processed_count = 0
        reply_count = 0
        error_count = 0
        state_changed = False

        # --- Uncomment this block if you want to enable self-checks ---
        # logger.info("Ensuring own user ID is known for self-checks...")
        # await self._ensure_own_user_id()
        # if not self.own_user_id:
        #     logger.warning("Own user ID could not be determined. Self-checks will be disabled.")
        # -------------------------------------------------------------

        # 1. Fetch Home Timeline Tweets
        tweets = []
        try:
            logger.info(f"Fetching up to {self.config['tweets_to_fetch']} tweets from latest timeline...")
            # *** FIX APPLIED HERE: Use get_latest_timeline ***
            # Assuming it takes a 'count' argument similar to the previous attempt.
            # Further verification might be needed if it uses different parameters.
            timeline_result = await self.twikit_client.get_latest_timeline(count=self.config['tweets_to_fetch'])

            # Process the result - could be list, iterator, or async iterator
            if hasattr(timeline_result, '__aiter__'):
                 logger.debug("Timeline result is an async iterator.")
                 tweets = [t async for t in timeline_result]
            elif hasattr(timeline_result, '__iter__') and not isinstance(timeline_result, str):
                 logger.debug("Timeline result is a sync iterator or list.")
                 tweets = list(timeline_result)
            # No need for explicit list check if list also has __iter__
            # elif isinstance(timeline_result, list):
            #      logger.debug("Timeline result is a list.")
            #      tweets = timeline_result
            else:
                 logger.warning(f"Unexpected type returned by get_latest_timeline: {type(timeline_result)}. Assuming empty list.")
                 tweets = []

            if not tweets:
                 logger.info("No new tweets found in timeline fetch for this iteration.")
                 # Optional: Save state even if no tweets found, to record the check time?
                 # if state_changed: await self.state_manager.save()
                 return # Successful iteration, nothing new to do

            logger.info(f"Fetched {len(tweets)} tweets. Processing potential replies...")

        except AttributeError:
             # This might catch if 'get_latest_timeline' also doesn't exist, but unlikely given the previous error msg
             logger.critical(f"FATAL: The 'get_latest_timeline' method does not seem to exist on the twikit client.", exc_info=True)
             raise # Re-raise to stop the bot service

        except TypeError as e:
            # Catch if 'count' is not a valid argument for get_latest_timeline
            logger.critical(f"FATAL: TypeError calling 'get_latest_timeline'. Does it accept a 'count' argument? Error: {e}", exc_info=True)
            raise # Re-raise to stop the bot service

        except TwitterException as e:
            logger.error(f"Failed to fetch Twitter timeline using get_latest_timeline: {e}", exc_info=True)
            return # End this iteration
        except Exception as e:
            logger.error(f"An unexpected error occurred during timeline fetch: {e}", exc_info=True)
            return # End this iteration


        # Process oldest first in the fetched batch
        for i, tweet in enumerate(reversed(tweets)):
            # Check if it's a valid Tweet object from twikit
            if not isinstance(tweet, Tweet) or not hasattr(tweet, 'id') or not hasattr(tweet, 'text'):
                 # Log the type if it's unexpected
                 logger.warning(f"Skipping invalid/unexpected timeline item (type: {type(tweet)}): {tweet!r}")
                 continue

            tweet_id = str(tweet.id)
            tweet_text = tweet.text or "" # Ensure text is not None
            tweet_author_user = getattr(tweet, 'user', None)
            # Safely access screen_name, provide default
            tweet_author_handle = getattr(tweet_author_user, 'screen_name', 'unknown_user') if tweet_author_user else 'unknown_user'
            tweet_url = f"https://x.com/{tweet_author_handle}/status/{tweet_id}"

            logger.info(f"Checking tweet ({i+1}/{len(tweets)}): {tweet_url}")

            # 2. Check if Already Processed
            if self.state_manager.is_processed(tweet_id):
                logger.info(f"Skipping already processed tweet ID {tweet_id}")
                continue

            processed_count += 1 # Count tweets we actually attempt to process

            # --- Optional Self-Checks (Requires _ensure_own_user_id to be called and successful) ---
            # if self.own_user_id:
            #     try:
            #         tweet_author_id = getattr(tweet_author_user, 'id', None)
            #         if tweet_author_id and str(tweet_author_id) == str(self.own_user_id):
            #             logger.info(f"Skipping own tweet: {tweet_id}")
            #             await self.state_manager.mark_processed(tweet_id)
            #             state_changed = True
            #             continue
            #
            #         reply_to_user_id_str = getattr(tweet, 'in_reply_to_user_id_str', None)
            #         if reply_to_user_id_str and reply_to_user_id_str == str(self.own_user_id):
            #             logger.info(f"Skipping reply to self: {tweet_id}")
            #             await self.state_manager.mark_processed(tweet_id)
            #             state_changed = True
            #             continue
            #     except Exception as e:
            #          logger.warning(f"Error during self-check for tweet {tweet_id}: {e}", exc_info=False)
            # ------------------------------------------------------------------------------------

            # 3. Generate Reply using Gemini
            if not tweet_text.strip():
                logger.warning(f"Skipping tweet {tweet_id} because its text is empty or whitespace.")
                await self.state_manager.mark_processed(tweet_id) # Mark as processed to avoid retrying
                state_changed = True
                continue

            logger.info(f"Generating reply for tweet ID {tweet_id}...")
            reply_text = await self.gemini_client.generate_reply(tweet_text)

            if not reply_text:
                logger.warning(f"Gemini did not return a reply for tweet {tweet_id}. Skipping post.")
                error_count += 1
                await self.state_manager.mark_processed(tweet_id)
                state_changed = True
                continue

            # 4. Post Reply to Twitter
            logger.info(f"Attempting to post reply to tweet ID {tweet_id}...")
            try:
                # Ensure the tweet object has the 'reply' method
                if not hasattr(tweet, 'reply') or not callable(tweet.reply):
                    logger.error(f"Tweet object for ID {tweet_id} does not have a callable 'reply' method. Skipping reply.")
                    error_count += 1
                    # Mark as processed? Or leave for potential future fix? Let's mark it.
                    await self.state_manager.mark_processed(tweet_id)
                    state_changed = True
                    continue

                reply_tweet = await tweet.reply(reply_text)
                reply_count += 1
                state_changed = True
                reply_tweet_id = getattr(reply_tweet, 'id', 'UNKNOWN_ID')
                logger.info(f"Successfully posted reply to {tweet_url}. New tweet ID: {reply_tweet_id}")

                # 5. Mark as Processed (only after successful post)
                await self.state_manager.mark_processed(tweet_id)

                # 6. Randomized Delay
                is_last_tweet_in_batch = (i == len(tweets) - 1)
                if not is_last_tweet_in_batch:
                    delay = random.uniform(self.min_delay, self.max_delay)
                    logger.info(f"Waiting for {delay:.2f}s (randomized {self.min_delay}-{self.max_delay}s) before processing next tweet...")
                    await asyncio.sleep(delay)
                else:
                    logger.info("Successfully replied to the last tweet in this batch. No intra-batch delay needed.")

            # Specific exception handling for replies
            except NotFound if NotFound else Exception as e:
                 if NotFound and isinstance(e, NotFound):
                     logger.warning(f"Original tweet {tweet_id} not found when trying to reply (NotFound error). Maybe deleted? Skipping.")
                     error_count += 1
                     await self.state_manager.mark_processed(tweet_id) # Mark as processed
                     state_changed = True
                 else:
                     # Reraise if NotFound not defined or error is different, to be caught below
                     raise e

            except Forbidden as e:
                 logger.error(f"Forbidden to reply to tweet {tweet_id}: {e}. Skipping.", exc_info=False) # Less verbose log
                 error_count += 1
                 await self.state_manager.mark_processed(tweet_id) # Mark as processed
                 state_changed = True
            except TwitterException as e:
                # More specific error logging could go here based on e.response or e.api_codes if available
                logger.error(f"Twitter API error posting reply for tweet {tweet_id}: {e}", exc_info=True)
                error_count += 1
                # Don't mark as processed, could be temporary (rate limit, etc.)
            except Exception as e:
                 logger.error(f"An unexpected error occurred while replying to {tweet_id}: {e}", exc_info=True)
                 error_count += 1
                 # Consider marking processed only for certain unexpected errors, otherwise retry might be ok

        # 7. Save State if Changed
        if state_changed:
            logger.info("Saving updated state...")
            await self.state_manager.save()

        iteration_duration = time.monotonic() - iteration_start_time
        logger.info(
            f"Iteration completed in {iteration_duration:.2f}s. "
            f"Checked: {processed_count}, Replied: {reply_count}, Errors: {error_count}."
        )
