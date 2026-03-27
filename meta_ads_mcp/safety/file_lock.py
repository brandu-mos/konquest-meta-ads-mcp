"""
Atomic file write with cross-platform file locking.

Prevents concurrent write corruption on accounts.yaml and other shared files.

Usage:
    from meta_ads_mcp.safety.file_lock import atomic_yaml_write, locked_yaml_read_modify_write

    # Simple read-modify-write with locking
    locked_yaml_read_modify_write(filepath, modifier_fn)
"""
import logging
import os
import tempfile
import time
from typing import Callable, Optional

import yaml

logger = logging.getLogger("meta-ads-mcp.safety.file_lock")

# Lock timeout
LOCK_TIMEOUT_SECONDS = 10
LOCK_RETRY_INTERVAL = 0.1


def _lock_path(filepath: str) -> str:
    return filepath + ".lock"


def _acquire_lock(filepath: str, timeout: float = LOCK_TIMEOUT_SECONDS) -> bool:
    """Acquire a file lock. Returns True if acquired, False if timeout."""
    lock_path = _lock_path(filepath)
    start = time.monotonic()

    while time.monotonic() - start < timeout:
        try:
            # O_CREAT | O_EXCL: create only if doesn't exist (atomic on most OS)
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            # Check if lock is stale (older than 30 seconds)
            try:
                lock_age = time.time() - os.path.getmtime(lock_path)
                if lock_age > 30:
                    logger.warning(f"Removing stale lock (age={lock_age:.0f}s): {lock_path}")
                    os.remove(lock_path)
                    continue
            except OSError:
                pass
            time.sleep(LOCK_RETRY_INTERVAL)

    logger.error(f"Failed to acquire lock after {timeout}s: {lock_path}")
    return False


def _release_lock(filepath: str):
    """Release a file lock."""
    lock_path = _lock_path(filepath)
    try:
        os.remove(lock_path)
    except OSError:
        pass


def atomic_write(filepath: str, content: str, encoding: str = "utf-8"):
    """Write content to file atomically (write temp + rename)."""
    dir_path = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # Atomic rename (on same filesystem)
        if os.path.exists(filepath):
            os.replace(tmp_path, filepath)
        else:
            os.rename(tmp_path, filepath)
    except Exception:
        # Cleanup temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def locked_yaml_read_modify_write(
    filepath: str,
    modifier: Callable[[dict], None],
    timeout: float = LOCK_TIMEOUT_SECONDS,
) -> dict:
    """
    Safely read, modify, and write a YAML file with file locking and atomic write.

    Args:
        filepath: Path to YAML file.
        modifier: Function that modifies the data dict in-place.
        timeout: Lock acquisition timeout.

    Returns:
        {"status": "success"} or {"status": "error", "reason": str}
    """
    if not _acquire_lock(filepath, timeout):
        return {"status": "error", "reason": f"Could not acquire lock on {filepath} after {timeout}s"}

    try:
        # Read
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Modify
        modifier(data)

        # Write atomically
        content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
        atomic_write(filepath, content)

        return {"status": "success"}

    except (OSError, yaml.YAMLError) as e:
        logger.error(f"Failed to read-modify-write {filepath}: {e}")
        return {"status": "error", "reason": str(e)}

    finally:
        _release_lock(filepath)
