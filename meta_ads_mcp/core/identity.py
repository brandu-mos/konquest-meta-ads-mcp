"""
Instagram Identity Gate - production enforcement module.

Implements:
1. 3-step resolution ladder (registry -> promote_pages -> ad_account)
2. Persistent per-account readiness state
3. Hard preflight gate for all write corridors
4. Explicit placement_mode handling (full_meta / facebook_only / instagram_only)

RULES:
- If placement_mode == "full_meta" and instagram_ready == False: HARD BLOCK
- If placement_mode == "instagram_only" and instagram_ready == False: HARD BLOCK
- If placement_mode == "facebook_only" and instagram_ready == False: ALLOW with explicit note
- No silent fallback from full_meta to facebook_only. Ever.
- No conversational branching ("do you want FB-only?"). Ever.

Uses instagram_user_id as the canonical public parameter.
Never uses instagram_actor_id (deprecated).
"""
import datetime
import logging
import os
from typing import Optional

import yaml

from meta_ads_mcp.core.api import api_client
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.identity")

# Registry path
_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config")
_ACCOUNTS_YAML = os.path.join(_CONFIG_DIR, "accounts.yaml")

# Valid placement modes
VALID_PLACEMENT_MODES = ("full_meta", "facebook_only", "instagram_only")
DEFAULT_PLACEMENT_MODE = "full_meta"


# ===================================================================
# PUBLIC API
# ===================================================================


def resolve_instagram_identity(account_id: str, page_id: Optional[str] = None) -> dict:
    """
    Resolve instagram_user_id for an ad account. 3-step ladder:

    1. Registry (accounts.yaml) - instant, no API call
    2. promote_pages endpoint - works with system user token
    3. ad account instagram_accounts endpoint

    Auto-persists resolved identity to registry.

    Returns:
        {
            "instagram_user_id": str or None,
            "instagram_username": str or None,
            "instagram_ready": bool,
            "resolution_method": str,
            "resolution_confidence": "high" | "none",
            "page_id": str or None,
            "blocked": bool,
            "block_reason": str or None,
        }
    """
    account_id = ensure_account_id_format(account_id)

    # Step 1: Registry lookup (zero API cost)
    registry_result = _check_registry(account_id)
    if registry_result and registry_result.get("instagram_user_id"):
        logger.info(f"IG identity resolved from registry: {registry_result['instagram_user_id']}")
        return _success(
            ig_id=registry_result["instagram_user_id"],
            username=registry_result.get("instagram_username"),
            method="registry",
            page_id=registry_result.get("page_id") or page_id,
        )

    # Step 2: promote_pages endpoint (works with system token)
    effective_page_id = page_id or (registry_result.get("page_id") if registry_result else None)
    if effective_page_id:
        promote_result = _resolve_via_promote_pages(account_id, effective_page_id)
        if promote_result:
            logger.info(f"IG identity resolved via promote_pages: {promote_result['instagram_user_id']}")
            _persist_to_registry(account_id, promote_result["instagram_user_id"],
                                 promote_result.get("instagram_username"), "api_confirmed")
            return _success(
                ig_id=promote_result["instagram_user_id"],
                username=promote_result.get("instagram_username"),
                method="promote_pages",
                page_id=effective_page_id,
            )

    # Step 3: ad account instagram_accounts endpoint
    api_result = _resolve_via_ad_account(account_id)
    if api_result:
        logger.info(f"IG identity resolved via ad account: {api_result['instagram_user_id']}")
        _persist_to_registry(account_id, api_result["instagram_user_id"],
                             api_result.get("instagram_username"), "api_confirmed")
        return _success(
            ig_id=api_result["instagram_user_id"],
            username=api_result.get("instagram_username"),
            method="ad_account_ig_accounts",
            page_id=page_id,
        )

    # All steps failed - persist failure state
    _persist_failure_to_registry(account_id)
    logger.warning(f"IG identity UNRESOLVED for {account_id}")
    return {
        "instagram_user_id": None,
        "instagram_username": None,
        "instagram_ready": False,
        "resolution_method": "unresolved",
        "resolution_confidence": "none",
        "page_id": page_id,
        "blocked": True,
        "block_reason": (
            f"Cannot resolve Instagram identity for {account_id}. "
            "Manual fix required: add IG account to Business Manager, "
            "link it to the Page, or set instagram_user_id in accounts.yaml."
        ),
        "manual_fix_required": True,
        "manual_fix_steps": [
            "1. Go to Business Settings > Instagram Accounts > Add",
            "2. Connect the correct Instagram account",
            "3. Assign it to the correct ad account",
            "4. Verify page linkage",
            "5. Re-run verification",
        ],
    }


def get_account_readiness(account_id: str, page_id: Optional[str] = None) -> dict:
    """
    Get full Instagram readiness state for an account.
    Returns persistent state model with all capability fields.
    """
    account_id = ensure_account_id_format(account_id)
    result = resolve_instagram_identity(account_id, page_id)

    registry = _check_registry(account_id)
    slug = registry.get("client_slug", "unknown") if registry else "unknown"

    return {
        "account_id": account_id,
        "client_slug": slug,
        "page_id": result.get("page_id"),
        "instagram_business_account_id": result.get("instagram_user_id"),
        "instagram_handle": result.get("instagram_username"),
        "instagram_ready": result.get("instagram_ready", False),
        "instagram_ready_reason": (
            f"Resolved via {result['resolution_method']}" if result.get("instagram_ready")
            else result.get("block_reason", "Unknown failure")
        ),
        "instagram_failure_stage": None if result.get("instagram_ready") else result.get("resolution_method"),
        "placements_allowed": {
            "facebook": True,
            "instagram": result.get("instagram_ready", False),
        },
        "last_verified_at": datetime.date.today().isoformat(),
        "source_of_truth": result.get("resolution_method"),
        "manual_fix_required": result.get("manual_fix_required", False),
        "manual_fix_steps": result.get("manual_fix_steps"),
    }


def enforce_instagram_gate(
    account_id: str,
    page_id: Optional[str] = None,
    placement_mode: str = DEFAULT_PLACEMENT_MODE,
) -> dict:
    """
    HARD PREFLIGHT GATE. Call before any ad creation, activation, or launch.

    Returns:
        {
            "allowed": bool,
            "placement_mode": str,
            "instagram_user_id": str or None,
            "effective_placements": {"facebook": bool, "instagram": bool},
            "block_reason": str or None,  # only if not allowed
            "manual_fix_steps": list or None,
        }

    RULES:
    - full_meta + IG not ready = HARD BLOCK
    - instagram_only + IG not ready = HARD BLOCK
    - facebook_only + IG not ready = ALLOW (explicit IG unavailable)
    """
    if placement_mode not in VALID_PLACEMENT_MODES:
        return {
            "allowed": False,
            "placement_mode": placement_mode,
            "instagram_user_id": None,
            "effective_placements": {"facebook": False, "instagram": False},
            "block_reason": f"Invalid placement_mode: '{placement_mode}'. Valid: {VALID_PLACEMENT_MODES}",
            "manual_fix_steps": None,
        }

    readiness = get_account_readiness(account_id, page_id)
    ig_ready = readiness["instagram_ready"]
    ig_id = readiness["instagram_business_account_id"]

    if placement_mode == "facebook_only":
        # Always allowed, but explicitly note IG status
        return {
            "allowed": True,
            "placement_mode": "facebook_only",
            "instagram_user_id": ig_id,
            "instagram_ready": ig_ready,
            "effective_placements": {"facebook": True, "instagram": False},
            "block_reason": None,
            "instagram_unavailable_note": None if ig_ready else readiness["instagram_ready_reason"],
        }

    if placement_mode in ("full_meta", "instagram_only") and not ig_ready:
        # HARD BLOCK
        return {
            "allowed": False,
            "placement_mode": placement_mode,
            "instagram_user_id": None,
            "instagram_ready": False,
            "effective_placements": {"facebook": False, "instagram": False},
            "block_reason": (
                f"BLOCKED: placement_mode='{placement_mode}' requires Instagram readiness. "
                f"Account {account_id} is NOT Instagram-ready. "
                f"Reason: {readiness['instagram_ready_reason']}. "
                "Use placement_mode='facebook_only' to explicitly run FB-only, "
                "or fix the Instagram identity issue first."
            ),
            "manual_fix_required": True,
            "manual_fix_steps": readiness.get("manual_fix_steps"),
            "allowed_fallbacks": ["facebook_only (requires explicit operator request)"],
        }

    # full_meta or instagram_only with IG ready
    effective = {
        "facebook": placement_mode != "instagram_only",
        "instagram": True,
    }
    return {
        "allowed": True,
        "placement_mode": placement_mode,
        "instagram_user_id": ig_id,
        "instagram_ready": True,
        "effective_placements": effective,
        "block_reason": None,
    }


# ===================================================================
# INTERNAL HELPERS
# ===================================================================


def _success(ig_id: str, username: Optional[str], method: str, page_id: Optional[str]) -> dict:
    return {
        "instagram_user_id": ig_id,
        "instagram_username": username,
        "instagram_ready": True,
        "resolution_method": method,
        "resolution_confidence": "high",
        "page_id": page_id,
        "blocked": False,
        "block_reason": None,
    }


def _check_registry(account_id: str) -> Optional[dict]:
    """Check accounts.yaml for cached instagram_user_id."""
    try:
        with open(_ACCOUNTS_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for slug, client in data.get("clients", {}).items():
            if ensure_account_id_format(client.get("account_id", "")) == account_id:
                ig_id = client.get("instagram_user_id")
                return {
                    "instagram_user_id": ig_id if ig_id else None,
                    "instagram_username": client.get("instagram_username"),
                    "page_id": client.get("page_id"),
                    "client_slug": slug,
                }
    except Exception as e:
        logger.debug(f"Registry lookup failed: {e}")
    return None


def _resolve_via_promote_pages(account_id: str, page_id: str) -> Optional[dict]:
    """Resolve IG via promote_pages endpoint. Works with system user token."""
    try:
        api_client._ensure_initialized()
        result = api_client.graph_get(
            f"/{account_id}/promote_pages",
            fields=["id", "name", "instagram_business_account"],
        )
        # First pass: match exact page_id
        for page in result.get("data", []):
            ig_biz = page.get("instagram_business_account")
            if ig_biz and isinstance(ig_biz, dict):
                ig_id = ig_biz.get("id")
                if ig_id and page.get("id") == page_id:
                    username = _fetch_ig_username(ig_id)
                    return {"instagram_user_id": ig_id, "instagram_username": username}
        # Second pass: any page with IG
        for page in result.get("data", []):
            ig_biz = page.get("instagram_business_account")
            if ig_biz and isinstance(ig_biz, dict):
                ig_id = ig_biz.get("id")
                if ig_id:
                    username = _fetch_ig_username(ig_id)
                    return {"instagram_user_id": ig_id, "instagram_username": username}
    except Exception as e:
        logger.debug(f"promote_pages resolution failed: {e}")
    return None


def _resolve_via_ad_account(account_id: str) -> Optional[dict]:
    """Resolve IG via ad account instagram_accounts endpoint."""
    try:
        api_client._ensure_initialized()
        result = api_client.graph_get(
            f"/{account_id}/instagram_accounts",
            fields=["id", "username"],
        )
        accounts = result.get("data", [])
        if accounts:
            return {
                "instagram_user_id": accounts[0].get("id"),
                "instagram_username": accounts[0].get("username"),
            }
    except Exception as e:
        logger.debug(f"ad account IG resolution failed: {e}")
    return None


def _fetch_ig_username(ig_id: str) -> Optional[str]:
    """Fetch IG username from ID."""
    try:
        ig_detail = api_client.graph_get(f"/{ig_id}", fields=["id", "username"])
        return ig_detail.get("username")
    except Exception:
        return None


def _persist_to_registry(account_id: str, ig_id: str, username: Optional[str], method: str):
    """Persist resolved IG identity to accounts.yaml with file locking."""
    from meta_ads_mcp.safety.file_lock import locked_yaml_read_modify_write

    def _modifier(data):
        for slug, client in data.get("clients", {}).items():
            if ensure_account_id_format(client.get("account_id", "")) == account_id:
                client["instagram_user_id"] = ig_id
                if username:
                    client["instagram_username"] = username
                if "ig_resolution" not in client:
                    client["ig_resolution"] = {}
                client["ig_resolution"]["status"] = "api_confirmed"
                client["ig_resolution"]["method"] = method
                client["ig_resolution"]["last_verified_at"] = datetime.date.today().isoformat()
                if "instagram_ready" in client:
                    client["instagram_ready"] = True
                break

    result = locked_yaml_read_modify_write(_ACCOUNTS_YAML, _modifier)
    if result["status"] == "success":
        logger.info(f"Persisted IG identity {ig_id} for {account_id} to registry (locked)")
    else:
        logger.warning(f"Failed to persist IG identity to registry: {result['reason']}")


def _persist_failure_to_registry(account_id: str):
    """Persist IG resolution failure to registry with file locking."""
    from meta_ads_mcp.safety.file_lock import locked_yaml_read_modify_write

    def _modifier(data):
        for slug, client in data.get("clients", {}).items():
            if ensure_account_id_format(client.get("account_id", "")) == account_id:
                if "ig_resolution" not in client:
                    client["ig_resolution"] = {}
                client["ig_resolution"]["status"] = "unresolved"
                client["ig_resolution"]["last_verified_at"] = datetime.date.today().isoformat()
                client["ig_resolution"]["manual_fix_required"] = True
                break

    result = locked_yaml_read_modify_write(_ACCOUNTS_YAML, _modifier)
    if result["status"] != "success":
        logger.debug(f"Failed to persist failure state: {result['reason']}")
