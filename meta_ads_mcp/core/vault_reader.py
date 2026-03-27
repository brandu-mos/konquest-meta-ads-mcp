"""
Vault Reader - reads client intelligence from Obsidian vault.

Auto-resolves client data before ad creation:
- Brand voice, ICPs, angles, objections, offers, positioning
- Page ID, Pixel ID, IG ID from profile
- Campaign history, what works, assets

If critical files are missing or empty, blocks execution
and instructs operator to run /full_pipeline first.

## Readiness Levels
- blocked: critical files missing, cannot proceed
- minimal: profile only, basic operations possible
- partial: critical files present, some important missing
- production_ready: all critical + important files present

## Write Corridor Requirements
- create_campaign: minimal
- create_adset: partial (needs profile for tracking)
- create_ad / ad_builder: partial (needs brand voice, ICPs)
- build_execution_pack: partial
- build_activation_pack: minimal
- build_mutation_pack: minimal
"""
import logging
import os
from typing import Any, Optional

from meta_ads_mcp.core.api import api_client
from meta_ads_mcp.core.utils import ensure_account_id_format
from meta_ads_mcp.engine.storage import resolve_slug
from meta_ads_mcp.server import mcp

logger = logging.getLogger("meta-ads-mcp.vault_reader")

VAULT_BASE = os.environ.get("VAULT_PATH", os.path.join(os.path.expanduser("~"), "marketing-vault"))

# Files required for ad creation (critical)
CRITICAL_FILES = {
    "00-profile.md": "Account IDs, pixel, page, IG, social handles",
    "04-brand-voice.md": "Tone, language, style rules for copy",
    "02-icp-personas.md": "Target audience profiles",
}

# Files used for copy quality (important but not blocking)
IMPORTANT_FILES = {
    "05-messaging-house.md": "Angles, value props, proof points",
    "08-objections.md": "Objections + bias deployment",
    "matrix.md": "Decision Matrix (ICP x Angle x Bias x Format)",
    "03-offers.md": "Products, pricing, packages",
    "01-positioning.md": "USP, competitive advantages",
    "06-content-pillars.md": "What Works - top performers",
}

# Files useful for context
CONTEXT_FILES = {
    "07-campaign-history.md": "Past campaigns and results",
    "10-assets.md": "Colors, fonts, brand assets",
    "09-constraints.md": "Budget, legal, brand limits",
    "12-next-actions.md": "TODOs and priorities",
}


def _read_vault_file(slug: str, filename: str) -> Optional[str]:
    """Read a file from the client's vault directory."""
    path = os.path.join(VAULT_BASE, "01_CLIENTS", slug, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return content if content and len(content) > 20 else None  # Empty or stub = None
    except OSError:
        return None


def _extract_profile_ids(profile_content: str) -> dict:
    """Extract operational IDs from 00-profile.md using robust regex patterns.

    Handles multiple formats: colon-separated, table rows, parenthetical IDs.
    Examples matched:
      - "**Page ID:** 111222333444555"
      - "- **Ad Account:** act_1234567890 (name: Foo)"
      - "| Page | 111222333444555 |"
      - "Page (ID: 111222333444555)"
    """
    import re
    ids = {"page_id": None, "pixel_id": None, "instagram_user_id": None, "ad_account_id": None}
    if not profile_content:
        return ids

    # Extract all numeric IDs > 5 digits from context-relevant lines
    _DIGIT_ID = re.compile(r'(\d{6,})')
    _ACT_ID = re.compile(r'(act_\d+)')

    for line in profile_content.split("\n"):
        line_lower = line.lower()

        # Ad account (act_ prefix is definitive)
        if not ids["ad_account_id"]:
            act_match = _ACT_ID.search(line)
            if act_match and ("account" in line_lower or "act_" in line_lower):
                ids["ad_account_id"] = act_match.group(1)

        # Page ID - require "page" context, extract first numeric ID
        if not ids["page_id"] and "page" in line_lower and ("id" in line_lower or ":" in line_lower):
            if "instagram" not in line_lower and "pixel" not in line_lower:
                m = _DIGIT_ID.search(line)
                if m:
                    ids["page_id"] = m.group(1)

        # Pixel ID - require "pixel" context
        if not ids["pixel_id"] and "pixel" in line_lower and ("id" in line_lower or ":" in line_lower):
            m = _DIGIT_ID.search(line)
            if m:
                ids["pixel_id"] = m.group(1)

        # Instagram user ID - require "instagram" context
        if not ids["instagram_user_id"] and "instagram" in line_lower and ("id" in line_lower or ":" in line_lower or "user" in line_lower):
            m = _DIGIT_ID.search(line)
            if m:
                ids["instagram_user_id"] = m.group(1)

    return ids


@mcp.tool()
def read_client_vault(
    account_id: str,
    include_context: bool = False,
) -> dict:
    """
    Read all client intelligence from the Obsidian vault for ad operations.

    Auto-resolves: brand voice, ICPs, angles, objections, profile IDs.
    If critical files are missing, returns explicit blockers.

    Args:
        account_id: Ad account ID. Resolved to client slug via registry.
        include_context: If True, also reads campaign history, assets, constraints.
    """
    account_id = ensure_account_id_format(account_id)
    slug = resolve_slug(account_id)

    if not slug:
        return {
            "error": f"Cannot resolve client slug for {account_id}. Check accounts.yaml registry.",
            "blocked_at": "slug_resolution",
            "action_required": "Add this account to meta-ads-mcp/config/accounts.yaml",
        }

    # Check vault directory exists
    client_dir = os.path.join(VAULT_BASE, "01_CLIENTS", slug)
    if not os.path.exists(client_dir):
        return {
            "error": f"Client directory not found: 01_CLIENTS/{slug}/",
            "blocked_at": "vault_missing",
            "action_required": f"Run /full_pipeline for this client to create vault files.",
        }

    # Read critical files
    critical = {}
    missing_critical = []
    for filename, description in CRITICAL_FILES.items():
        content = _read_vault_file(slug, filename)
        if content:
            critical[filename] = content
        else:
            missing_critical.append({"file": filename, "description": description})

    # Read important files
    important = {}
    missing_important = []
    for filename, description in IMPORTANT_FILES.items():
        content = _read_vault_file(slug, filename)
        if content:
            important[filename] = content
        else:
            missing_important.append({"file": filename, "description": description})

    # Read context files if requested
    context = {}
    if include_context:
        for filename, description in CONTEXT_FILES.items():
            content = _read_vault_file(slug, filename)
            if content:
                context[filename] = content

    # Extract profile IDs
    profile_ids = _extract_profile_ids(critical.get("00-profile.md", ""))

    # Also try to get IDs from registry as fallback
    from meta_ads_mcp.engine.storage import read_json_store
    import yaml
    registry_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config", "accounts.yaml"
    )
    registry_ids = {}
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        client_data = data.get("clients", {}).get(slug, {})
        registry_ids = {
            "page_id": client_data.get("page_id"),
            "pixel_id": client_data.get("pixel_id"),
            "instagram_user_id": client_data.get("instagram_user_id"),
            "ad_account_id": client_data.get("account_id"),
        }
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        logger.warning(f"Registry lookup failed for slug '{slug}': {e}")

    # Merge: vault profile IDs + registry IDs (registry as fallback)
    resolved_ids = {}
    for key in ["page_id", "pixel_id", "instagram_user_id", "ad_account_id"]:
        resolved_ids[key] = profile_ids.get(key) or registry_ids.get(key)

    # Determine readiness
    if missing_critical:
        readiness = "blocked"
        action = f"Run /full_pipeline for '{slug}' to populate: {', '.join(m['file'] for m in missing_critical)}"
    elif missing_important:
        readiness = "partial"
        action = f"Consider running /deep_research for '{slug}' to populate: {', '.join(m['file'] for m in missing_important)}"
    else:
        readiness = "ready"
        action = None

    return {
        "account_id": account_id,
        "client_slug": slug,
        "readiness": readiness,
        "action_required": action,
        "resolved_ids": resolved_ids,
        "missing_critical": missing_critical,
        "missing_important": missing_important,
        "files_loaded": {
            "critical": list(critical.keys()),
            "important": list(important.keys()),
            "context": list(context.keys()),
        },
        "brand_voice": critical.get("04-brand-voice.md"),
        "icp_personas": critical.get("02-icp-personas.md"),
        "profile": critical.get("00-profile.md"),
        "messaging_house": important.get("05-messaging-house.md"),
        "objections": important.get("08-objections.md"),
        "decision_matrix": important.get("matrix.md"),
        "offers": important.get("03-offers.md"),
        "positioning": important.get("01-positioning.md"),
        "content_pillars": important.get("06-content-pillars.md"),
        "campaign_history": context.get("07-campaign-history.md"),
        "assets": context.get("10-assets.md"),
        "constraints": context.get("09-constraints.md"),
    }


# ===================================================================
# ENFORCEMENT GATE - called by all write corridors
# ===================================================================

# Minimum readiness per corridor
CORRIDOR_REQUIREMENTS = {
    "create_campaign": "minimal",
    "create_adset": "partial",
    "create_ad": "partial",
    "create_multi_asset_ad": "partial",
    "build_execution_pack": "partial",
    "execute_paused_launch": "minimal",
    "build_mutation_pack": "minimal",
    "execute_mutation_pack": "minimal",
    "build_activation_pack": "minimal",
    "execute_activation_pack": "minimal",
}

READINESS_ORDER = {"blocked": 0, "minimal": 1, "partial": 2, "production_ready": 3}


def enforce_vault_gate(account_id: str, corridor: str) -> tuple[Optional[dict], Optional[dict]]:
    """
    Enforce vault intelligence gate before a write operation.

    Returns (error_dict, vault_context).
    If error_dict is not None, the operation must be blocked.
    If error_dict is None, vault_context contains resolved intelligence.
    """
    account_id = ensure_account_id_format(account_id)
    slug = resolve_slug(account_id)

    if not slug:
        return ({"error": f"Cannot resolve client for {account_id}. Add to accounts.yaml.",
                 "blocked_at": "vault_gate", "action_required": "Register account in config/accounts.yaml"}, None)

    # Read vault
    vault = read_client_vault(account_id, include_context=False)

    if vault.get("error"):
        return ({"error": vault["error"], "blocked_at": "vault_gate",
                 "action_required": vault.get("action_required")}, None)

    # Determine actual readiness
    raw_readiness = vault.get("readiness", "blocked")
    critical_loaded = vault.get("files_loaded", {}).get("critical", [])
    important_loaded = vault.get("files_loaded", {}).get("important", [])

    if raw_readiness == "blocked":
        readiness = "blocked"
    elif "00-profile.md" in critical_loaded:
        if "04-brand-voice.md" in critical_loaded and "02-icp-personas.md" in critical_loaded:
            if len(important_loaded) >= 3:
                readiness = "production_ready" if len(important_loaded) >= 5 else "partial"
            else:
                readiness = "partial"
        else:
            readiness = "minimal"
    else:
        readiness = "blocked"

    # Check corridor requirement
    required = CORRIDOR_REQUIREMENTS.get(corridor, "partial")
    required_level = READINESS_ORDER.get(required, 2)
    actual_level = READINESS_ORDER.get(readiness, 0)

    if actual_level < required_level:
        missing = vault.get("missing_critical", []) + vault.get("missing_important", [])
        return ({
            "error": f"Vault readiness '{readiness}' below required '{required}' for {corridor}.",
            "blocked_at": "vault_gate",
            "vault_readiness": readiness,
            "required_readiness": required,
            "missing_files": [m["file"] for m in missing],
            "action_required": vault.get("action_required") or f"Run /full_pipeline for '{slug}'",
        }, None)

    # Build context for the corridor
    vault_context = {
        "client_slug": slug,
        "vault_readiness": readiness,
        "vault_files_loaded": vault.get("files_loaded"),
        "vault_blockers": [m["file"] for m in vault.get("missing_critical", [])],
        "resolved_ids": vault.get("resolved_ids", {}),
        "used_vault_context": {
            "brand_voice": vault.get("brand_voice") is not None,
            "icp": vault.get("icp_personas") is not None,
            "messaging_house": vault.get("messaging_house") is not None,
            "objections": vault.get("objections") is not None,
            "offers": vault.get("offers") is not None,
        },
        # Actual content for use in copy/decisions
        "brand_voice": vault.get("brand_voice"),
        "icp_personas": vault.get("icp_personas"),
        "messaging_house": vault.get("messaging_house"),
        "objections": vault.get("objections"),
        "offers": vault.get("offers"),
        "positioning": vault.get("positioning"),
        "content_pillars": vault.get("content_pillars"),
    }

    return (None, vault_context)
