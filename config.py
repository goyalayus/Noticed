import os
import logging
from dotenv import load_dotenv
from pathlib import Path # Use pathlib for better path handling

logger = logging.getLogger(__name__)

def load_config():
    """Loads configuration from .env file and environment variables."""
    load_dotenv()  # Load variables from .env file

    config = {}

    # --- Gemini ---
    config['gemini_api_key'] = os.getenv('GEMINI_API_KEY')
    if not config['gemini_api_key']:
        logger.critical("FATAL ERROR: Missing required environment variable: GEMINI_API_KEY")
        raise ValueError("Missing GEMINI_API_KEY")

    # --- Twitter Auth ---
    # Twikit documentation suggests username/email (auth_info_1) and password are required for login method,
    # even if cookies are primarily used afterwards.
    config['twitter_username'] = os.getenv('TWITTER_USERNAME')
    config['twitter_email'] = os.getenv('TWITTER_EMAIL') # Optional (auth_info_2 for login)
    config['twitter_password'] = os.getenv('TWITTER_PASSWORD')
    config['twitter_cookie_file'] = os.getenv('TWITTER_COOKIE_FILE') # Optional path to cookies.json

    # Validate that required credentials for the login() method are present
    if not config['twitter_username']:
         logger.critical("FATAL ERROR: Missing required environment variable: TWITTER_USERNAME (required for twikit login)")
         raise ValueError("Missing TWITTER_USERNAME")
    if not config['twitter_password']:
         logger.critical("FATAL ERROR: Missing required environment variable: TWITTER_PASSWORD (required for twikit login)")
         raise ValueError("Missing TWITTER_PASSWORD")

    # Check for cookie file existence only if it's configured
    cookie_path = None
    if config['twitter_cookie_file']:
        cookie_path = Path(config['twitter_cookie_file'])
        if not cookie_path.is_file():
            logger.critical(f"FATAL ERROR: TWITTER_COOKIE_FILE is set ('{config['twitter_cookie_file']}') but the file does not exist or is not a file.")
            raise ValueError(f"Cookie file not found or invalid: {config['twitter_cookie_file']}")
        config['twitter_cookie_file_path'] = cookie_path # Store Path object if valid
    else:
        config['twitter_cookie_file_path'] = None


    # Log a warning if both methods are technically configured
    if config['twitter_username'] and config['twitter_password'] and config['twitter_cookie_file']:
         logger.warning("Both Twitter credentials and cookie file are configured. Twikit login requires credentials; cookie file will likely be used for subsequent session persistence if valid.")

    # --- Bot Settings ---
    config['speaking_style_file_path'] = Path(os.getenv('SPEAKING_STYLE_FILE_PATH', 'speaking_style.txt'))
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

    # --- Create data directory ---
    state_dir = config['state_file_path'].parent # Get directory from Path object
    if state_dir: # Check if there is a parent directory (might be '.' if file is in root)
        try:
            state_dir.mkdir(parents=True, exist_ok=True) # Use pathlib's mkdir
            logger.info(f"Ensured data directory exists: {state_dir}")
        except OSError as e:
            # Changed to warning as maybe permissions are the issue, not creation itself
            logger.warning(f"Could not create or access data directory '{state_dir}': {e}. Ensure it exists and is writable.")
        except Exception as e:
             logger.error(f"Unexpected error ensuring data directory '{state_dir}' exists: {e}")

    # Ensure speaking style file exists
    if not config['speaking_style_file_path'].is_file():
        logger.critical(f"FATAL ERROR: Speaking style file not found at '{config['speaking_style_file_path']}'.")
        raise FileNotFoundError(f"Speaking style file not found: {config['speaking_style_file_path']}")


    logger.info("Configuration loaded successfully.")
    return config

# Example usage (optional, for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    try:
        cfg = load_config()
        print("\n--- Loaded Config (Passwords Masked) ---")
        for key, value in cfg.items():
            # Mask passwords/api keys for printing
            if ('password' in key.lower() or 'api_key' in key.lower()) and value:
                 print(f"  {key}: ******")
            elif isinstance(value, Path):
                 print(f"  {key}: {str(value)}") # Print Path object as string
            else:
                 print(f"  {key}: {value}")
        print("----------------------------------------")

    except (ValueError, FileNotFoundError) as e:
        print(f"\nError loading config: {e}")
    except Exception as e:
        print(f"\nUnexpected error during config load test: {e}")
