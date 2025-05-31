import asyncio
import logging
import signal
import os
import sys
from pathlib import Path
from twikit import Client as TwikitClient
from twikit.errors import TwitterException

import config
import state_manager
import gemini_client
import bot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

shutdown_requested = False
main_task = None

async def main_loop(): # Renamed to avoid conflict with main function if any
    global shutdown_requested, main_task
    logger.info("=======================================")
    logger.info(" Starting Twitter Gemini Bot Service   ")
    logger.info("=======================================")

    try:
        cfg = config.load_config()
        cfg_state_file_str = str(cfg['state_file_path'])
        cfg_style_file_path = cfg['speaking_style_file_path']
        cfg_blog_content_file_path = cfg['blog_content_file_path'] # <<< NEW
        cfg_cookie_file_str = str(cfg['twitter_cookie_file_path']) if cfg.get('twitter_cookie_file_path') else None
        cfg_twitter_username = cfg['twitter_username'].lstrip('@')
    except (ValueError, FileNotFoundError) as e:
        logger.critical(f"Configuration error: {e}", exc_info=True)
        sys.exit(1)

    state_mgr = None
    try:
        state_mgr = state_manager.StateManager(cfg_state_file_str)
        await state_mgr.load()
        logger.info("State manager initialized.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize State Manager: {e}", exc_info=True)
        sys.exit(1)

    gemini_cli = None
    try:
        gemini_cli = gemini_client.GeminiClient(
            cfg['gemini_api_key'],
            cfg_style_file_path,
            cfg_blog_content_file_path # <<< PASS NEW PATH
        )
        await gemini_cli.load_speaking_style()
        await gemini_cli.load_blog_content() # <<< LOAD BLOG CONTENT
        logger.info("Gemini client initialized, speaking style and blog content loaded.")
    except (ValueError, ConnectionError, FileNotFoundError) as e:
         logger.critical(f"FATAL: Failed to initialize Gemini client or load content: {e}", exc_info=True)
         sys.exit(1)
    except Exception as e:
         logger.critical(f"FATAL: Unexpected error initializing Gemini client: {e}", exc_info=True)
         sys.exit(1)

    twikit_cli = None
    try:
        twikit_cli = TwikitClient('en-US')
        login_args = {
            'auth_info_1': cfg['twitter_username'],
            'password': cfg['twitter_password']
        }
        login_method_info = [f"user='{cfg['twitter_username']}'", "password=***"]

        if cfg.get('twitter_email'):
            login_args['auth_info_2'] = cfg['twitter_email']
            login_method_info.append("email=provided")
        else:
             login_method_info.append("email=not_provided")

        if cfg_cookie_file_str: # Check if path string is not None
            login_args['cookies_file'] = cfg_cookie_file_str # Pass string path
            login_method_info.append(f"cookies_file='{Path(cfg_cookie_file_str).name}'") # Log only filename
        else:
            # Attempt to create/use default 'cookies.json' if not specified and path is None
            default_cookie_file = Path('cookies.json')
            login_args['cookies_file'] = str(default_cookie_file)
            login_method_info.append(f"cookies_file='{default_cookie_file.name}' (default)")


        logger.info(f"Attempting Twitter login using: {', '.join(login_method_info)}...")
        await twikit_cli.login(**login_args)
        logger.info("Twikit login method called.")

        logger.info(f"Verifying login by fetching user @{cfg_twitter_username}...")
        authenticated_user = await twikit_cli.get_user_by_screen_name(cfg_twitter_username)
        if not authenticated_user or not authenticated_user.id:
             logger.critical("FATAL: Login seemed successful, but could not fetch own user details.")
             # Attempt to save cookies even on verification failure, as login might have partially worked
             if hasattr(twikit_cli, 'save_cookies') and cfg_cookie_file_str:
                try: await twikit_cli.save_cookies(cfg_cookie_file_str)
                except: logger.warning("Failed to save cookies after login verification issue.")
             sys.exit(1)
        logger.info(f"Twitter login successful for user: @{authenticated_user.screen_name} (ID: {authenticated_user.id})")

        # Save cookies after successful login and verification if a path was given
        if hasattr(twikit_cli, 'save_cookies') and cfg_cookie_file_str:
            try:
                await twikit_cli.save_cookies(cfg_cookie_file_str)
                logger.info(f"Cookies saved to {cfg_cookie_file_str}")
            except Exception as e_cookie_save:
                logger.warning(f"Failed to save cookies to {cfg_cookie_file_str}: {e_cookie_save}")
        elif hasattr(twikit_cli, 'save_cookies') and not cfg_cookie_file_str:
             # If no specific cookie file was in env, but login created one
             logger.info(f"Twikit may have saved cookies to its default location (e.g., {default_cookie_file.name})")


    except AttributeError as e:
        logger.critical(f"FATAL: Twitter client attribute error: {e}", exc_info=True)
        sys.exit(1)
    except FileNotFoundError as e: # Should be caught by config load if path is invalid
        logger.critical(f"FATAL: Twitter login - Cookie file issue: {e}", exc_info=True)
        sys.exit(1)
    except TwitterException as e:
        logger.critical(f"FATAL: Failed to login/verify Twitter ({type(e).__name__}): {e}", exc_info=True)
        sys.exit(1)
    except TypeError as e:
        logger.critical(f"FATAL: TypeError during Twitter login: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"FATAL: Unexpected error during Twitter client init/login: {e}", exc_info=True)
        sys.exit(1)

    app_bot = None
    try:
        app_bot = bot.Bot(cfg, twikit_cli, gemini_cli, state_mgr)
        logger.info("Application Bot initialized.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize Application Bot: {e}", exc_info=True)
        sys.exit(1)

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

    for sig_name in ('SIGINT', 'SIGTERM'):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            logger.warning(f"Signal {sig_name} not available on this platform. Skipping handler.")
            continue
        try:
             loop.add_signal_handler(sig, signal_handler, sig)
             logger.debug(f"Registered signal handler for {sig_name}")
        except (NotImplementedError, AttributeError, RuntimeError) : # More robust for different OS
             logger.warning(f"asyncio.loop.add_signal_handler not fully supported for {sig_name}. Using standard signal.signal.")
             signal.signal(sig, lambda s, f: signal_handler(s)) # s is sig num, f is frame

    logger.info("Performing initial bot run...")
    try:
        if app_bot: await app_bot.run_iteration()
        logger.info("Initial bot run completed.")
    except Exception as e:
         logger.error(f"Initial bot run encountered an error: {e}", exc_info=True)

    logger.info(f"Entering main run loop. Interval: {cfg['fetch_interval_minutes']}m.")
    main_task = asyncio.current_task() # Get current task (the main_loop task)
    try:
        while not shutdown_requested:
            logger.debug(f"Loop: Shutdown requested: {shutdown_requested}. Sleeping for {cfg['fetch_interval_seconds']}s.")
            try:
                 await asyncio.sleep(cfg['fetch_interval_seconds'])
            except asyncio.CancelledError:
                 logger.info("Main loop sleep cancelled.")
                 break # Exit sleep and then the while loop

            if shutdown_requested:
                 logger.info("Shutdown requested during sleep interval, breaking loop.")
                 break

            logger.info("Interval finished. Triggering bot iteration...")
            try:
                 if app_bot: await app_bot.run_iteration()
            except asyncio.CancelledError:
                 logger.info("Bot iteration cancelled.")
                 break
            except Exception as e:
                 logger.error(f"Bot iteration failed: {e}", exc_info=True)

    except asyncio.CancelledError:
         logger.info("Main loop task was cancelled.")
    finally:
        logger.info("Exited main loop.")
        logger.info("Performing final state save...")
        try:
            if state_mgr: await state_mgr.save()
            logger.info("Final state saved.")
        except Exception as e:
            logger.error(f"ERROR: Failed to save state during shutdown: {e}", exc_info=True)

        if twikit_cli and hasattr(twikit_cli, 'close'):
            try:
                logger.info("Attempting to close Twitter client...")
                close_method = getattr(twikit_cli, 'close')
                if asyncio.iscoroutinefunction(close_method): await close_method()
                else: close_method()
                logger.info("Twitter client closed.")
            except Exception as e:
                logger.error(f"Error closing twikit client: {e}", exc_info=True)
        elif twikit_cli:
             logger.info("Twikit client has no 'close' method.")

        logger.info("=======================================")
        logger.info(" Twitter Gemini Bot Service stopped.   ")
        logger.info("=======================================")
        stop_event.set()


if __name__ == "__main__":
    # Removed load_dotenv() from here as it's called in config.load_config()
    try:
        asyncio.run(main_loop()) # Call the renamed async function
    except KeyboardInterrupt:
         logger.info("KeyboardInterrupt received by top-level, stopping.")
    except asyncio.CancelledError:
         logger.info("Main execution task cancelled at top-level.")
    except Exception as e:
         # This will catch errors during asyncio.run() itself or if main_loop()
         # raises an unhandled exception before its own try/finally.
         logger.critical(f"Unhandled exception during script execution: {e}", exc_info=True)
         sys.exit(1)
    finally:
        logger.info("Application process terminating.")
