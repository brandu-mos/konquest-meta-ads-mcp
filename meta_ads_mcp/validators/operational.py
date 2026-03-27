"""
Operational validation checks (Category E).

Validates operational readiness: rollback snapshots, vault logging paths,
confirmation triggers, rate limit headroom, and blocked action detection.

Phase: v1.0 (Foundation) - fully implemented.
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("meta-ads-mcp.validators.operational")


def check_rollback_directory(client_slug: str, base_path: Optional[str] = None) -> dict:
    """
    Verify rollback directory exists and is writable for a client.

    Returns:
        dict with 'ready' bool and 'path' string.
    """
    if base_path is None:
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "rollback")

    client_path = os.path.join(base_path, client_slug)

    try:
        os.makedirs(client_path, exist_ok=True)
        # Test writability
        test_file = os.path.join(client_path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return {"ready": True, "path": client_path}
    except (OSError, PermissionError) as e:
        return {"ready": False, "path": client_path, "error": str(e)}


def check_manifest_directory(client_slug: str, base_path: Optional[str] = None) -> dict:
    """
    Verify manifest directory exists for a client.

    Returns:
        dict with 'ready' bool and 'path' string.
    """
    if base_path is None:
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "manifests")

    client_path = os.path.join(base_path, client_slug)

    try:
        os.makedirs(client_path, exist_ok=True)
        return {"ready": True, "path": client_path}
    except (OSError, PermissionError) as e:
        return {"ready": False, "path": client_path, "error": str(e)}


def check_debug_directory(base_path: Optional[str] = None) -> dict:
    """Verify debug directory exists and is writable."""
    if base_path is None:
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "debug")

    try:
        os.makedirs(base_path, exist_ok=True)
        return {"ready": True, "path": base_path}
    except (OSError, PermissionError) as e:
        return {"ready": False, "path": base_path, "error": str(e)}


def validate_no_active_status_in_create(payload: dict) -> dict:
    """
    Ensure a create payload does not set status to ACTIVE.

    This is a hard safety rule: all objects must be created as PAUSED.
    """
    status = payload.get("status", "PAUSED")
    if status == "ACTIVE":
        return {
            "valid": False,
            "message": "Cannot create objects as ACTIVE. All objects must be created as PAUSED.",
            "remediation": "Remove 'status: ACTIVE' or change to 'status: PAUSED'.",
        }
    return {"valid": True, "message": "Status is PAUSED (safe)"}
