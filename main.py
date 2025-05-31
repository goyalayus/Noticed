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

async def main_loop():
    global shutdown_requested, main_task
    logger.info("=======================================")
    logger.info(" Starting Twitter Gemini Bot Service   ")
    logger.info("=======================================")

    cfg = None
    try:
        cfg = config.load_config()
        cfg_state_file_path = cfg['state_file_path']
        cfg_style_file_path = cfg['speaking_style_file_path']
        # Removed: cfg_blog_content_file_path = cfg['blog_content_file_path']
        cfg_cookie_file_path_obj = cfg['twitter_cookie_file_path']
        cfg_twitter_username_raw = cfg['twitter_username']
        cfg_twitter_username_cleaned = cfg_twitter_username_raw.lstrip('@')

    except (ValueError, FileNotFoundError) as e:
        logger.critical(f"Configuration error: {e}", exc_info=True)
        sys.exit(1)

    state_mgr = None
    try:
        state_mgr = state_manager.StateManager(cfg_state_file_path)
        await state_mgr.load()
        logger.info("State manager initialized.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize State Manager: {e}", exc_info=True)
        sys.exit(1)

    gemini_cli = None
    try:
        gemini_cli = gemini_client.GeminiClient(
            cfg['gemini_api_key'],
            cfg_style_file_path
            # Removed cfg_blog_content_file_path
        )
        await gemini_cli.load_speaking_style()
        # Removed: await gemini_cli.load_blog_content()
        logger.info("Gemini client initialized and speaking style loaded.")
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
            'auth_info_1': cfg_twitter_username_raw,
            'password': cfg['twitter_password']
        }
        login_method_info = [f"user='{cfg_twitter_username_raw}'", "password=***"]

        if cfg.get('twitter_email'):
            login_args['auth_info_2'] = cfg['twitter_email']
            login_method_info.append(f"email='{cfg['twitter_email']}'")
        else:
            login_method_info.append("email=not_provided")

        login_args['cookies_file'] = str(cfg_cookie_file_path_obj)
        login_method_info.append(f"cookies_file='{cfg_cookie_file_path_obj.name}'")
        
        logger.info(f"Attempting Twitter login using: {', '.join(login_method_info)}...")
        await twikit_cli.login(**login_args)
        logger.info("Twikit login method called successfully.")

        logger.info(f"Verifying login by fetching user @{cfg_twitter_username_cleaned}...")
        authenticated_user = await twikit_cli.get_user_by_screen_name(cfg_twitter_username_cleaned)
        
        if not authenticated_user or not authenticated_user.id:
             logger.critical("FATAL: Login seemed successful, but could not fetch own user details afterwards.")
             if hasattr(twikit_cli, 'save_cookies'):
                try: await twikit_cli.save_cookies(str(cfg_cookie_file_path_obj))
                except Exception as esc: logger.warning(f"Failed to save cookies after login verification issue: {esc}")
             sys.exit(1)

        logger.info(f"Twitter login successful for user: @{authenticated_user.screen_name} (ID: {authenticated_user.id})")
        cfg['twitter_actual_user_id'] = str(authenticated_user.id)

        if hasattr(twikit_cli, 'save_cookies'):
            try:
                await twikit_cli.save_cookies(str(cfg_cookie_file_path_obj))
                logger.info(f"Cookies saved to {cfg_cookie_file_path_obj}")
            except Exception as e_cookie_save:
                logger.warning(f"Failed to save cookies to {cfg_cookie_file_path_obj}: {e_cookie_save}")
        else:
            logger.warning("Twikit client does not have 'save_cookies' method. Cookies might not be saved explicitly by bot.")


    except AttributeError as e:
        logger.critical(f"FATAL: Twitter client attribute error (e.g. method not found): {e}", exc_info=True)
        sys.exit(1)
    except FileNotFoundError as e: 
        logger.critical(f"FATAL: Twitter login - Cookie file issue from config: {e}", exc_info=True)
        sys.exit(1)
    except TwitterException as e:
        logger.critical(f"FATAL: Failed to login to Twitter or verify user ({type(e).__name__}): {e}", exc_info=True)
        sys.exit(1)
    except TypeError as e:
        logger.critical(f"FATAL: TypeError during Twitter login (check twikit.login arguments): {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"FATAL: An unexpected error occurred during Twitter client initialization or login: {e}", exc_info=True)
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

    def signal_handler_wrapper(sig):
        nonlocal loop
        signal_handler(sig, loop, main_task)

    for sig_name in ('SIGINT', 'SIGTERM'):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            logger.warning(f"Signal {sig_name} not available on this platform. Skipping handler.")
            continue
        try:
             loop.add_signal_handler(sig, signal_handler_wrapper, sig)
             logger.debug(f"Registered signal handler for {sig_name} using loop.add_signal_handler")
        except (NotImplementedError, AttributeError, RuntimeError) :
             logger.warning(f"asyncio.loop.add_signal_handler not fully supported for {sig_name}. Using standard signal.signal.")
             def sync_signal_handler(s, f):
                 logger.info(f"Sync signal handler caught {s}. Requesting shutdown via global flag.")
                 global shutdown_requested
                 shutdown_requested = True
                 if main_task and not main_task.done():
                     loop.call_soon_threadsafe(main_task.cancel)
             signal.signal(sig, sync_signal_handler)


    logger.info("Performing initial bot run...")
    try:
        if app_bot: await app_bot.run_iteration()
        logger.info("Initial bot run completed.")
    except Exception as e:
         logger.error(f"Initial bot run encountered an error: {e}", exc_info=True)

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
                 if app_bot: await app_bot.run_iteration()
            except asyncio.CancelledError:
                 logger.info("Bot iteration cancelled during execution.")
                 break
            except Exception as e:
                 logger.error(f"Bot iteration failed: {e}", exc_info=True)

    except asyncio.CancelledError:
         logger.info("Main loop task was cancelled.")
    finally:
        logger.info("Exited main loop.")
        logger.info("Performing final state save before exiting...")
        try:
            if state_mgr:
                 await state_mgr.save()
                 logger.info("Final state saved successfully.")
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

def signal_handler(sig, loop, task_to_cancel):
    global shutdown_requested
    if shutdown_requested:
        logger.warning(f"Signal {sig} received again, shutdown already in progress.")
        return
    logger.info(f"Received signal: {sig}. Initiating graceful shutdown...")
    shutdown_requested = True
    if task_to_cancel and not task_to_cancel.done():
        logger.info("Cancelling main loop task...")
        task_to_cancel.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
         logger.info("KeyboardInterrupt received by top-level asyncio.run, stopping.")
    except asyncio.CancelledError:
         logger.info("Main execution task cancelled at top-level.")
    except SystemExit as se:
        logger.info(f"SystemExit called with code {se.code}")
        sys.exit(se.code)
    except Exception as e:
         logger.critical(f"Unhandled exception during script execution: {e}", exc_info=True)
         sys.exit(1)
    finally:
        logger.info("Application process terminating.")

