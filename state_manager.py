import json
import logging
import os
import aiofiles # Use async file I/O
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

class StateManager:
    """Handles loading and saving processed tweet IDs asynchronously."""

    def __init__(self, file_path: str | Path, max_memory_size: int = 10000):
        """
        Initializes the StateManager.

        Args:
            file_path: Path to the JSON file used for persistence (string or Path object).
            max_memory_size: Maximum number of tweet IDs to keep in memory and in the file.
                             Older entries may be evicted.
        """
        self.file_path = Path(file_path)
        self.processed_ids = set() # Store IDs as strings for consistency
        if max_memory_size <= 0:
             logger.warning(f"max_memory_size should be positive, setting to default 10000. Got: {max_memory_size}")
             self.max_memory_size = 10000
        else:
             self.max_memory_size = max_memory_size
        self._lock = asyncio.Lock() # Protect file access and set modification

    async def load(self) -> None:
        """Loads processed IDs from the JSON file into memory."""
        async with self._lock:
            logger.info(f"Attempting to load state from {self.file_path}...")
            if not self.file_path.exists():
                logger.info(f"State file {self.file_path} not found, starting with empty state.")
                self.processed_ids = set()
                return

            try:
                async with aiofiles.open(self.file_path, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    if not content.strip():
                        logger.info(f"State file {self.file_path} is empty, starting with empty state.")
                        self.processed_ids = set()
                        return

                    ids_from_file = json.loads(content)
                    if not isinstance(ids_from_file, list):
                        logger.error(f"State file content is not a JSON list. Found type: {type(ids_from_file)}. Starting fresh.")
                        # Optionally back up the corrupted file here
                        self._backup_corrupt_file("invalid_format")
                        self.processed_ids = set()
                        return

                    # Convert all loaded IDs to strings for consistency
                    valid_ids = {str(item) for item in ids_from_file if item is not None}

                    # Trim if loaded list > max_memory_size (keep most recent assuming list was appended)
                    # Convert set back to list, sort (optional but helps consistency), then trim
                    sorted_ids = sorted(list(valid_ids)) # Sort ensures somewhat predictable trimming if needed
                    start_index = max(0, len(sorted_ids) - self.max_memory_size)
                    self.processed_ids = set(sorted_ids[start_index:])

                    logger.info(f"Loaded {len(self.processed_ids)} processed tweet IDs (kept latest {self.max_memory_size}) from {self.file_path}.")

            except FileNotFoundError:
                 # This case should ideally be caught by self.file_path.exists() check above, but included for safety
                 logger.info(f"State file {self.file_path} not found during load operation, starting fresh.")
                 self.processed_ids = set()
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode state file {self.file_path}. File might be corrupt. Backing up and starting fresh.", exc_info=False)
                logger.debug("JSONDecodeError details", exc_info=True) # Log full trace in debug
                self._backup_corrupt_file("json_decode_error")
                self.processed_ids = set() # Start fresh after error
            except Exception as e:
                logger.error(f"An unexpected error occurred loading state from {self.file_path}: {e}", exc_info=True)
                # Backup potentially corrupt file on any load error
                self._backup_corrupt_file("unexpected_load_error")
                self.processed_ids = set() # Safest to start fresh

    def _backup_corrupt_file(self, suffix: str):
        """Internal synchronous method to backup a potentially corrupt state file."""
        if not self.file_path.exists():
            return # Nothing to backup
        try:
            backup_path = self.file_path.with_suffix(f"{self.file_path.suffix}.{suffix}.bak")
            # Ensure backup name is unique if it already exists
            counter = 0
            while backup_path.exists():
                counter += 1
                backup_path = self.file_path.with_suffix(f"{self.file_path.suffix}.{suffix}_{counter}.bak")

            os.rename(self.file_path, backup_path) # Use sync rename for simplicity in error handling path
            logger.info(f"Backed up potentially corrupt state file to {backup_path}")
        except OSError as backup_err:
            logger.error(f"Failed to backup corrupt state file {self.file_path}: {backup_err}")
        except Exception as e:
            logger.error(f"Unexpected error during state file backup: {e}")


    async def save(self) -> None:
        """Saves the current set of processed IDs to the JSON file atomically."""
        async with self._lock:
            # Convert set to list and sort for consistent output (easier diffs)
            # Ensure all IDs are strings before saving
            ids_to_save = sorted([str(id_val) for id_val in self.processed_ids])

            # Apply memory limit before saving
            if len(ids_to_save) > self.max_memory_size:
                logger.info(f"State size ({len(ids_to_save)}) exceeds limit ({self.max_memory_size}). Trimming oldest entries before saving.")
                ids_to_save = ids_to_save[-self.max_memory_size:] # Keep the last N elements (assuming sorted implies newest are last - depends on ID type)

            temp_file_path = self.file_path.with_suffix(self.file_path.suffix + '.tmp')

            try:
                # Ensure directory exists before writing
                self.file_path.parent.mkdir(parents=True, exist_ok=True)

                async with aiofiles.open(temp_file_path, mode='w', encoding='utf-8') as f:
                    await f.write(json.dumps(ids_to_save, indent=2)) # Use indent=2 for readability

                # Atomic rename (os.replace is generally atomic on POSIX/Windows)
                os.replace(temp_file_path, self.file_path)
                logger.info(f"Saved {len(ids_to_save)} processed tweet IDs to state file {self.file_path}.")

            except Exception as e:
                logger.error(f"Failed to save state to {self.file_path}: {e}", exc_info=True)
                # Attempt to clean up temp file if it exists
                if temp_file_path.exists():
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary state file {temp_file_path} after save error.")
                    except OSError as rm_err:
                        logger.error(f"Failed to remove temporary state file {temp_file_path} after save error: {rm_err}")

    def is_processed(self, tweet_id: str | int) -> bool:
        """Checks if a tweet ID (str or int) has already been processed."""
        # Accessing set for read is thread-safe in CPython due to GIL, async lock not strictly needed
        # but doesn't hurt if consistency during concurrent mark_processed is paramount.
        return str(tweet_id) in self.processed_ids

    async def mark_processed(self, tweet_id: str | int) -> None:
        """Adds a tweet ID (str or int) to the set of processed IDs, respecting memory limit."""
        if tweet_id is None:
             logger.warning("Attempted to mark None as processed. Skipping.")
             return

        tweet_id_str = str(tweet_id) # Ensure it's a string

        async with self._lock:
            if tweet_id_str not in self.processed_ids:
                 # Check memory limit *before* adding
                 if len(self.processed_ids) >= self.max_memory_size:
                     # Simple eviction: remove an arbitrary element using pop()
                     # For LRU/FIFO, a collections.deque or ordered set would be needed.
                     try:
                         evicted_id = self.processed_ids.pop()
                         logger.debug(f"Evicted state for tweet ID {evicted_id} due to memory limit ({self.max_memory_size}) before adding {tweet_id_str}.")
                     except KeyError:
                         pass # Should not happen if len >= max_memory_size > 0, but safe to ignore

                 self.processed_ids.add(tweet_id_str)
                 logger.debug(f"Marked tweet ID {tweet_id_str} as processed. State size: {len(self.processed_ids)}")
