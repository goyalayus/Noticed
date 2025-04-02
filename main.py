import asyncio
import logging
import signal
import os
import sys
from pathlib import Path
from twikit import Client as TwikitClient
from twikit.errors import TwitterException # Generic twikit exception

import config
import state_manager
import gemini_client
import bot

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
# Silence noisy libraries if needed
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

logger = logging.getLogger(__name__) # Get logger for this module

# --- Global Flag for Graceful Shutdown ---
shutdown_requested = False
main_task = None # To store the main loop task for cancellation

async def main():
    global shutdown_requested, main_task
    logger.info("=======================================")
    logger.info(" Starting Twitter Gemini Bot Service   ")
    logger.info("=======================================")

    # --- 1. Load Configuration ---
    try:
        cfg = config.load_config()
        cfg_state_file_str = str(cfg['state_file_path'])
        cfg_style_file_path = cfg['speaking_style_file_path']
        cfg_cookie_file_str = str(cfg['twitter_cookie_file_path']) if cfg.get('twitter_cookie_file_path') else None
        # Store username without the '@' if it exists, as screen_name usually doesn't have it
        cfg_twitter_username = cfg['twitter_username'].lstrip('@')

    except (ValueError, FileNotFoundError) as e:
        logger.critical(f"Configuration error: {e}", exc_info=True)
        sys.exit(1)

    # --- 2. Initialize State Manager ---
    try:
        state_mgr = state_manager.StateManager(cfg_state_file_str)
        await state_mgr.load()
        logger.info("State manager initialized.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize State Manager: {e}", exc_info=True)
        sys.exit(1)

    # --- 3. Initialize Gemini Client ---
    gemini_cli = None
    try:
        gemini_cli = gemini_client.GeminiClient(cfg['gemini_api_key'], cfg_style_file_path)
        await gemini_cli.load_speaking_style()
        logger.info("Gemini client initialized and speaking style loaded successfully.")
    except (ValueError, ConnectionError, FileNotFoundError) as e:
         logger.critical(f"FATAL: Failed to initialize Gemini client or load speaking style: {e}", exc_info=True)
         sys.exit(1)
    except Exception as e:
         logger.critical(f"FATAL: Unexpected error initializing Gemini client: {e}", exc_info=True)
         sys.exit(1)


    # --- 4. Initialize Twitter Client (Twikit) ---
    twikit_cli = None
    try:
        twikit_cli = TwikitClient('en-US')

        login_args = {}
        login_method_info = []

        # Pass username *with* '@' if needed by login, or without if not. Let's assume login needs the raw input.
        login_args['auth_info_1'] = cfg['twitter_username'] # Use original config value for login
        login_args['password'] = cfg['twitter_password']
        login_method_info.append(f"user='{cfg['twitter_username']}'") # Log original form
        login_method_info.append("password=***")

        if cfg.get('twitter_email'):
            login_args['auth_info_2'] = cfg['twitter_email']
            login_method_info.append("email=provided")
        else:
             login_method_info.append("email=not_provided")

        if cfg_cookie_file_str:
            login_args['cookies_file'] = cfg_cookie_file_str
            login_method_info.append(f"cookies_file='{cfg_cookie_file_str}'")
        else:
            login_method_info.append("cookies_file=not_provided")

        logger.info(f"Attempting Twitter login using: {', '.join(login_method_info)}...")
        await twikit_cli.login(**login_args)
        logger.info("Twikit login method called successfully.")

        # Verify login by fetching self info using get_user_by_screen_name
        # Use the username *without* the '@' symbol, as expected by screen_name lookups.
        logger.info(f"Verifying login by fetching user @{cfg_twitter_username}...")
        # *** FIX APPLIED HERE ***
        authenticated_user = await twikit_cli.get_user_by_screen_name(cfg_twitter_username)
        # Check if user object was returned
        if not authenticated_user or not authenticated_user.id:
             logger.critical("FATAL: Login seemed successful, but could not fetch own user details afterwards.")
             sys.exit(1)

        logger.info(f"Twitter login successful for user: @{authenticated_user.screen_name} (ID: {authenticated_user.id})")

    except AttributeError as e:
        # Catch if get_user_by_screen_name doesn't exist either
        logger.critical(f"FATAL: Twitter client attribute error during login/verification: {e}", exc_info=True)
        sys.exit(1)
    except FileNotFoundError as e:
        logger.critical(f"FATAL: Twitter login failed - Cookie file issue?: {e}", exc_info=True)
        sys.exit(1)
    except TwitterException as e:
        logger.critical(f"FATAL: Failed to login to Twitter or verify user ({type(e).__name__}): {e}", exc_info=True)
        sys.exit(1)
    except TypeError as e:
        logger.critical(f"FATAL: TypeError during Twitter login (likely incorrect arguments passed to twikit.login): {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"FATAL: An unexpected error occurred during Twitter client initialization or login: {e}", exc_info=True)
        sys.exit(1)


    # --- 5. Initialize Bot ---
    try:
        # Pass the authenticated user ID to the Bot if needed for self-checks
        # Or let the bot fetch it itself using the config username
        app_bot = bot.Bot(cfg, twikit_cli, gemini_cli, state_mgr)
        logger.info("Application Bot initialized.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize Application Bot: {e}", exc_info=True)
        sys.exit(1)

    # --- 6. Setup Signal Handling for Graceful Shutdown ---
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler(sig):
        global shutdown_requested, main_task
        if shutdown_requested:
            logger.warning(f"Signal {sig} received again, shutdown already in progress.")
            return
        logger.info(f"Received signal: {sig}. Initiating graceful shutdown...")
        shutdown_requested = True
        if main_task and not main_task.done():
            logger.info("Cancelling main loop task...")
            main_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
             loop.add_signal_handler(sig, signal_handler, sig)
             logger.debug(f"Registered signal handler for {sig} using loop.add_signal_handler")
        except NotImplementedError:
             logger.warning(f"asyncio.loop.add_signal_handler not fully supported on this platform for {sig}. Using standard signal.signal.")
             signal.signal(sig, lambda s, f: signal_handler(s))


    # --- 7. Initial Run ---
    logger.info("Performing initial bot run...")
    try:
        await app_bot.run_iteration()
        logger.info("Initial bot run completed.")
    except Exception as e:
         logger.error(f"Initial bot run encountered an error: {e}", exc_info=True)


    # --- 8. Run Loop ---
    logger.info(f"Entering main run loop. Fetch interval: {cfg['fetch_interval_minutes']} minutes ({cfg['fetch_interval_seconds']} seconds).")
    main_task = asyncio.current_task()
    try:
        while not shutdown_requested:
            logger.debug(f"Loop running. Shutdown requested: {shutdown_requested}. Sleeping for {cfg['fetch_interval_seconds']}s.")
            try:
                 await asyncio.sleep(cfg['fetch_interval_seconds'])
            except asyncio.CancelledError:
                 logger.info("Main loop sleep cancelled, likely during shutdown.")
                 break

            if shutdown_requested:
                 logger.info("Shutdown requested during sleep interval check, breaking loop.")
                 break

            logger.info("Interval finished. Triggering bot iteration...")
            try:
                 await app_bot.run_iteration()
            except asyncio.CancelledError:
                 logger.info("Bot iteration cancelled during execution.")
                 break
            except Exception as e:
                 logger.error(f"Bot iteration failed: {e}", exc_info=True)

    except asyncio.CancelledError:
         logger.info("Main loop task was cancelled.")
    finally:
        logger.info("Exited main loop.")
        # --- Graceful Shutdown Logic ---
        logger.info("Performing final state save before exiting...")
        try:
            if state_mgr:
                 await state_mgr.save()
                 logger.info("Final state saved successfully.")
            else:
                 logger.warning("State manager was not initialized, skipping final save.")
        except Exception as e:
            logger.error(f"ERROR: Failed to save state during shutdown: {e}", exc_info=True)

        if twikit_cli and hasattr(twikit_cli, 'close'):
            try:
                logger.info("Attempting to close Twitter client session...")
                close_method = getattr(twikit_cli, 'close')
                if asyncio.iscoroutinefunction(close_method):
                    await close_method()
                    logger.info("Asynchronously closed Twitter client session.")
                else:
                    close_method()
                    logger.info("Synchronously closed Twitter client session.")
            except Exception as e:
                logger.error(f"Error closing twikit client: {e}", exc_info=True)
        elif twikit_cli:
             logger.info("Twikit client does not appear to have a 'close' method. Skipping.")


        logger.info("=======================================")
        logger.info(" Twitter Gemini Bot Service stopped.   ")
        logger.info("=======================================")
        stop_event.set()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
         logger.info("KeyboardInterrupt received (outside main loop perhaps?), stopping.")
    except asyncio.CancelledError:
         logger.info("Main execution task cancelled.")
    except Exception as e:
         logger.critical(f"Unhandled exception during main execution setup: {e}", exc_info=True)
         sys.exit(1)
    finally:
        logger.info("Application process terminating.")
