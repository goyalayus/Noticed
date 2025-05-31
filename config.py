import os
import logging
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

def load_config():
    """Loads configuration from .env file and environment variables."""
    load_dotenv()

    config = {}

    # --- Gemini ---
    config['gemini_api_key'] = os.getenv('GEMINI_API_KEY')
    if not config['gemini_api_key']:
        logger.critical("FATAL ERROR: Missing required environment variable: GEMINI_API_KEY")
        raise ValueError("Missing GEMINI_API_KEY")

    # --- Twitter Auth ---
    config['twitter_username'] = os.getenv('TWITTER_USERNAME')
    config['twitter_email'] = os.getenv('TWITTER_EMAIL')
    config['twitter_password'] = os.getenv('TWITTER_PASSWORD')
    config['twitter_cookie_file'] = os.getenv('TWITTER_COOKIE_FILE') # Path to cookies.json

    if not config['twitter_username']:
         logger.critical("FATAL ERROR: Missing required environment variable: TWITTER_USERNAME")
         raise ValueError("Missing TWITTER_USERNAME")
    if not config['twitter_password']:
         logger.critical("FATAL ERROR: Missing required environment variable: TWITTER_PASSWORD")
         raise ValueError("Missing TWITTER_PASSWORD")

    cookie_path_str = config['twitter_cookie_file']
    if cookie_path_str:
        cookie_path = Path(cookie_path_str)
        if not cookie_path.is_file():
            logger.warning(f"TWITTER_COOKIE_FILE ('{cookie_path_str}') not found or is not a file. Login will rely on credentials only and may attempt to create/update this file.")
            config['twitter_cookie_file_path'] = cookie_path # Store path even if not existing yet for twikit to use
        else:
            config['twitter_cookie_file_path'] = cookie_path
            logger.info(f"Twitter cookie file found: {cookie_path}")
    else:
        default_cookie_path = Path('cookies.json')
        config['twitter_cookie_file_path'] = default_cookie_path
        logger.info(f"TWITTER_COOKIE_FILE not set in .env. Defaulting to use/create '{default_cookie_path}'.")


    # --- Bot Settings ---
    config['speaking_style_file_path'] = Path(os.getenv('SPEAKING_STYLE_FILE_PATH', 'speaking_style.txt'))
    # Removed: config['blog_content_file_path']
    config['state_file_path'] = Path(os.getenv('STATE_FILE_PATH', 'data/processed_tweets.json'))

    try:
        fetch_interval_minutes = int(os.getenv('FETCH_INTERVAL_MINUTES', '10'))
        if fetch_interval_minutes <= 0:
             raise ValueError("FETCH_INTERVAL_MINUTES must be a positive integer")
        config['fetch_interval_minutes'] = fetch_interval_minutes
        config['fetch_interval_seconds'] = fetch_interval_minutes * 60
    except ValueError as e:
        logger.warning(f"Invalid FETCH_INTERVAL_MINUTES, using default 10 minutes (600 seconds): {e}")
        config['fetch_interval_minutes'] = 10
        config['fetch_interval_seconds'] = 600

    try:
        tweets_to_fetch = int(os.getenv('TWEETS_TO_FETCH', '20'))
        if tweets_to_fetch <= 0:
             raise ValueError("TWEETS_TO_FETCH must be a positive integer")
        config['tweets_to_fetch'] = tweets_to_fetch
    except ValueError as e:
        logger.warning(f"Invalid TWEETS_TO_FETCH, using default 20: {e}")
        config['tweets_to_fetch'] = 20

    try:
        min_delay = int(os.getenv('MIN_REPLY_DELAY_SECONDS', '30'))
        max_delay = int(os.getenv('MAX_REPLY_DELAY_SECONDS', '60'))
        if min_delay < 0 or max_delay < min_delay:
             raise ValueError("MIN_REPLY_DELAY_SECONDS must be >= 0 and MAX_REPLY_DELAY_SECONDS must be >= MIN_REPLY_DELAY_SECONDS")
        config['min_reply_delay_seconds'] = min_delay
        config['max_reply_delay_seconds'] = max_delay
    except ValueError as e:
        logger.warning(f"Invalid reply delay settings, using defaults 30-60s: {e}")
        config['min_reply_delay_seconds'] = 30
        config['max_reply_delay_seconds'] = 60

    state_dir = config['state_file_path'].parent
    if state_dir:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured data directory exists: {state_dir}")
        except OSError as e:
            logger.warning(f"Could not create or access data directory '{state_dir}': {e}.")
        except Exception as e:
             logger.error(f"Unexpected error ensuring data directory '{state_dir}' exists: {e}")

    if not config['speaking_style_file_path'].is_file():
        logger.critical(f"FATAL ERROR: Speaking style file not found at '{config['speaking_style_file_path']}'.")
        raise FileNotFoundError(f"Speaking style file not found: {config['speaking_style_file_path']}")

    # Removed check for blog_content_file_path
    # if not config['blog_content_file_path'].is_file():
    #     logger.critical(f"FATAL ERROR: Blog content file not found at '{config['blog_content_file_path']}'.")
    #     raise FileNotFoundError(f"Blog content file not found: {config['blog_content_file_path']}")

    logger.info("Configuration loaded successfully.")
    return config

