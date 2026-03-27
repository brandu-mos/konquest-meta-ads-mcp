"""
Ad management tools.

Provides read operations and manifest-driven ad creation.
Supports three creative modes:
  1. Simple: single image/video with object_story_spec
  2. Dynamic Creative: multiple text/media variants via asset_feed_spec
  3. FLEX/DOF (Advantage+ Creative): degrees_of_freedom optimization

All ads created as PAUSED. Requires valid creative manifest.

## Creative Mode Selection Rules

### Simple mode
Use when: single image or video, one copy variant, one CTA.
Detection: manifest has exactly 1 variant, no multi-text arrays.
API: object_story_spec with video_data or link_data.

### Dynamic mode
Use when: multiple text/headline/description/image variants for Meta to test.
Detection: manifest has multiple bodies OR titles OR images.
API: asset_feed_spec with arrays of bodies, titles, descriptions, images/videos.

### DOF (Advantage+ Creative)
Use when: letting Meta optimize creative elements automatically.
Detection: manifest explicitly declares mode=dof OR creative_profile says dof.
API: degrees_of_freedom_spec (requires compatible account/format).
Note: Not all accounts/formats support DOF. Fall back to dynamic with explicit log.

## Why Manifest-Driven Creation
- Prevents duplicate ads (manifest tracks what's been created)
- Ensures creative analysis happened before ad runs
- Links creative to its SRT, transcript, and analysis
- Provides rollback reference chain
- Enables deterministic replay of ad creation
"""
import json as _json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.ads")

# Fields for list view
AD_LIST_FIELDS = [
    "id", "name", "status", "effective_status",
    "campaign_id", "adset_id",
    "creative", "tracking_specs",
    "created_time", "updated_time",
]

# Fields for detail view
AD_DETAIL_FIELDS = AD_LIST_FIELDS + [
    "bid_amount", "bid_type",
    "conversion_specs", "source_ad_id",
    "issues_info", "recommendations",
]

# Valid CTA types
VALID_CTA_TYPES = [
    "SHOP_NOW", "LEARN_MORE", "SIGN_UP", "BOOK_TRAVEL", "CONTACT_US",
    "DOWNLOAD", "GET_OFFER", "GET_QUOTE", "SUBSCRIBE", "WATCH_MORE",
    "APPLY_NOW", "ORDER_NOW", "SEND_MESSAGE", "CALL_NOW", "GET_DIRECTIONS",
    "OPEN_LINK", "NO_BUTTON",
]

# CTA -> URL type compatibility (for validation)
CTA_URL_COMPATIBILITY = {
    "SHOP_NOW": ["product_page", "collection_page", "bundle_page", "landing_page"],
    "LEARN_MORE": ["landing_page", "lead_page", "product_page", "collection_page", "homepage"],
    "SIGN_UP": ["lead_page", "landing_page"],
    "APPLY_NOW": ["lead_page", "landing_page"],
    "SUBSCRIBE": ["lead_page", "landing_page"],
    "CONTACT_US": ["lead_page", "landing_page", "homepage"],
    "ORDER_NOW": ["product_page", "bundle_page", "landing_page"],
    "GET_OFFER": ["landing_page", "product_page"],
}


def _load_manifest_entry(manifest_json: str, logical_creative_id: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Load and validate a manifest entry.

    Returns (entry, error). If error is not None, entry is None.
    """
    try:
        manifest = _json.loads(manifest_json)
    except _json.JSONDecodeError as e:
        return None, f"Malformed manifest JSON: {e}"

    if not isinstance(manifest, dict):
        return None, "Manifest must be a JSON object."

    # Find the logical_creative_id in the manifest
    creatives = manifest.get("creatives", [])
    if not creatives:
        # Maybe the manifest IS the creative entry itself
        if manifest.get("logical_creative_id") == logical_creative_id:
            return manifest, None
        return None, f"No creatives array in manifest and top-level logical_creative_id does not match."

    for entry in creatives:
        if entry.get("logical_creative_id") == logical_creative_id:
            return entry, None

    return None, f"logical_creative_id '{logical_creative_id}' not found in manifest. Available: {[c.get('logical_creative_id') for c in creatives]}"


def _detect_creative_mode(entry: dict) -> tuple[str, str]:
    """
    Detect creative mode from manifest entry.

    Returns (mode, reason) where mode is 'simple', 'dynamic', or 'dof'.
    """
    # Explicit mode declaration takes priority
    explicit_mode = entry.get("creative_mode")
    if explicit_mode in ("simple", "dynamic", "dof"):
        return explicit_mode, f"Explicit mode declaration in manifest: {explicit_mode}"

    profile = entry.get("creative_profile", {})
    if isinstance(profile, dict) and profile.get("creative_mode"):
        pm = profile["creative_mode"]
        if pm in ("simple", "dynamic", "dof"):
            return pm, f"Mode from creative_profile: {pm}"

    # Infer from structure
    variants = entry.get("variants", [])
    bodies = entry.get("bodies", [])
    titles = entry.get("titles", [])
    images = entry.get("images", [])

    multi_text = len(bodies) > 1 or len(titles) > 1
    multi_media = len(variants) > 1 or len(images) > 1

    if multi_text or multi_media:
        return "dynamic", f"Multiple text ({len(bodies)} bodies, {len(titles)} titles) or media ({len(variants)} variants, {len(images)} images) detected."

    return "simple", "Single variant, single text - simple mode."


def _build_simple_creative_spec(
    entry: dict,
    page_id: str,
    instagram_user_id: Optional[str],
    destination_url: str,
    primary_text: str,
    headline: Optional[str],
    description: Optional[str],
    cta_type: str,
) -> dict:
    """Build object_story_spec for simple mode."""
    # Determine if video or image
    variants = entry.get("variants", [])
    video_id = None
    image_hash = None
    image_url = None

    if variants:
        v = variants[0]
        video_id = v.get("meta_video_id") or v.get("video_id")
        image_hash = v.get("image_hash")
        image_url = v.get("image_url") or v.get("thumbnail_url")

    # Also check top-level
    if not video_id:
        video_id = entry.get("meta_video_id") or entry.get("video_id")
    if not image_hash:
        image_hash = entry.get("image_hash")

    spec: dict[str, Any] = {"page_id": page_id}
    if instagram_user_id:
        spec["instagram_user_id"] = instagram_user_id

    cta_block = {"type": cta_type, "value": {"link": destination_url}}

    if video_id:
        spec["video_data"] = {
            "video_id": video_id,
            "message": primary_text,
            "call_to_action": cta_block,
        }
        # Video ads REQUIRE a thumbnail (image_url or image_hash)
        # Try provided values first, then auto-fetch from video
        if image_url:
            spec["video_data"]["image_url"] = image_url
        elif image_hash:
            spec["video_data"]["image_hash"] = image_hash
        else:
            # Auto-fetch thumbnail from uploaded video
            try:
                vr = api_client.graph_get(f"/{video_id}", fields=["thumbnails", "picture"])
                thumbs = vr.get("thumbnails", {})
                if isinstance(thumbs, dict):
                    thumb_data = thumbs.get("data", [])
                    if thumb_data:
                        spec["video_data"]["image_url"] = thumb_data[0].get("uri", "")
                if not spec["video_data"].get("image_url"):
                    pic = vr.get("picture")
                    if pic:
                        spec["video_data"]["image_url"] = pic
            except Exception:
                pass  # Will fail at API call if no thumbnail
    else:
        spec["link_data"] = {
            "link": destination_url,
            "message": primary_text,
            "call_to_action": cta_block,
        }
        if headline:
            spec["link_data"]["name"] = headline
        if description:
            spec["link_data"]["description"] = description
        if image_hash:
            spec["link_data"]["image_hash"] = image_hash

    return spec


# ==================== READ TOOLS ====================

@mcp.tool()
def get_ads(
    account_id: str,
    campaign_id: Optional[str] = None,
    adset_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    List ads for an account, campaign, or ad set.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        campaign_id: Optional - filter ads by campaign.
        adset_id: Optional - filter ads by ad set (takes precedence over campaign_id).
        status_filter: Filter by effective_status: 'ACTIVE', 'PAUSED', 'ARCHIVED', or 'ALL'.
        limit: Maximum results per page (default 50).
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    params = {"limit": str(min(limit, 100))}

    if status_filter and status_filter.upper() != "ALL":
        status_val = status_filter.upper()
        valid_statuses = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"]
        if status_val in valid_statuses:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{status_val}"]}}]'

    if adset_id:
        endpoint = f"/{adset_id}/ads"
    elif campaign_id:
        endpoint = f"/{campaign_id}/ads"
    else:
        endpoint = f"/{account_id}/ads"

    try:
        result = api_client.graph_get(endpoint, fields=AD_LIST_FIELDS, params=params)
        ads = result.get("data", [])
        all_ads = list(ads)
        paging = result.get("paging", {})
        while paging.get("next") and len(all_ads) < 200:
            after_cursor = paging.get("cursors", {}).get("after")
            if not after_cursor:
                break
            params["after"] = after_cursor
            result = api_client.graph_get(endpoint, fields=AD_LIST_FIELDS, params=params)
            next_ads = result.get("data", [])
            if not next_ads:
                break
            all_ads.extend(next_ads)
            paging = result.get("paging", {})

        status_counts = {}
        for a in all_ads:
            es = a.get("effective_status", "UNKNOWN")
            status_counts[es] = status_counts.get(es, 0) + 1

        return {
            "total": len(all_ads),
            "status_counts": status_counts,
            "ads": all_ads,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }
    except MetaAPIError:
        raise


@mcp.tool()
def get_ad_details(ad_id: str) -> dict:
    """
    Get detailed ad information including creative reference,
    tracking specs, conversion specs, issues, and recommendations.

    Args:
        ad_id: Ad ID (numeric string).
    """
    api_client._ensure_initialized()
    try:
        result = api_client.graph_get(f"/{ad_id}", fields=AD_DETAIL_FIELDS)
        creative_ref = result.get("creative")
        if creative_ref and isinstance(creative_ref, dict):
            creative_id = creative_ref.get("id")
            if creative_id:
                try:
                    creative_details = api_client.graph_get(
                        f"/{creative_id}",
                        fields=[
                            "id", "name", "title", "body", "status",
                            "thumbnail_url", "image_url",
                            "object_story_spec", "asset_feed_spec",
                            "degrees_of_freedom_spec",
                            "url_tags", "call_to_action_type",
                        ],
                    )
                    result["creative_details"] = creative_details
                except MetaAPIError as e:
                    logger.warning("Could not fetch creative %s: %s", creative_id, e)
                    result["creative_details"] = {"error": str(e)}
        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result
    except MetaAPIError:
        raise


# ==================== WRITE TOOLS ====================

@mcp.tool()
def create_ad_from_manifest(
    account_id: str,
    adset_id: str,
    logical_creative_id: str,
    manifest_json: str,
    ad_name: str,
    page_id: str,
    destination_url: str,
    primary_text: str = "",
    cta_type: str = "SHOP_NOW",
    headline: Optional[str] = None,
    description: Optional[str] = None,
    instagram_user_id: Optional[str] = None,
    meta_video_id: Optional[str] = None,
    destination_url_override: Optional[str] = None,
    cta_override: Optional[str] = None,
    primary_text_override: Optional[str] = None,
    headline_override: Optional[str] = None,
    copy_mode: str = "manual",
    angle_name: Optional[str] = None,
    icp_name: Optional[str] = None,
    funnel_stage: str = "tofu",
    dry_run: bool = False,
    placement_mode: str = "full_meta",
) -> dict:
    """
    Create an ad from a manifest entry (always PAUSED, manifest-driven, no exceptions).

    Loads the manifest entry, detects creative mode, resolves identity,
    checks for duplicates, validates pre-write, creates the ad,
    and verifies post-write.

    INSTAGRAM GATE: Enforced via placement_mode parameter.
    - full_meta (default): requires IG identity, BLOCKS if unavailable
    - facebook_only: explicit FB-only, no IG placements
    - instagram_only: requires IG identity, BLOCKS if unavailable

    For video ads: provide meta_video_id from upload_video_asset + poll_video_processing.
    The video must be in 'ready' state before calling this tool.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        adset_id: Target ad set ID.
        logical_creative_id: ID of the creative entry in the manifest (e.g., 'lc_example_brand_001').
        manifest_json: JSON string containing the manifest or a single creative entry.
            Must include the logical_creative_id entry with variants, CTA, etc.
        ad_name: Name for the ad. Greek text validated.
        page_id: Facebook Page ID for the ad identity.
        destination_url: Primary destination URL for the ad CTA.
        primary_text: Primary text / message body. Required for manual mode, optional for auto/hybrid.
        cta_type: Call to action type (default 'SHOP_NOW'). See VALID_CTA_TYPES.
        headline: Optional headline text. Auto-generated if copy_mode='auto' and not provided.
        description: Optional description text. Auto-generated if copy_mode='auto' and not provided.
        instagram_user_id: Optional IG user ID. If not provided, attempts resolution from account.
        destination_url_override: If set, overrides manifest URL. Logged explicitly.
        cta_override: If set, overrides manifest CTA. Logged explicitly.
        primary_text_override: If set, overrides manifest primary text. Logged explicitly.
        headline_override: If set, overrides manifest headline. Logged explicitly.
        copy_mode: 'manual' (default), 'auto' (generate from vault), 'hybrid' (fill gaps).
        angle_name: Marketing angle for auto/hybrid copy generation.
        icp_name: Target ICP for auto/hybrid copy generation.
        funnel_stage: 'tofu', 'mofu', 'bofu' for copy tone/structure.
        dry_run: If true, runs all validation but does not create the ad. Returns what would be created.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overrides_applied = []

    # --- Vault gate ---
    from meta_ads_mcp.core.vault_reader import enforce_vault_gate
    vault_error, vault_ctx = enforce_vault_gate(account_id, "create_ad")
    if vault_error:
        return vault_error

    # ============================================================
    # Step 0: Load and validate manifest entry
    # ============================================================

    entry, manifest_error = _load_manifest_entry(manifest_json, logical_creative_id)
    if manifest_error:
        return {
            "error": f"Manifest validation failed: {manifest_error}",
            "blocked_at": "manifest_validation",
        }

    # ============================================================
    # Step 1: Apply overrides (explicit, logged)
    # ============================================================

    effective_url = destination_url
    if destination_url_override:
        effective_url = destination_url_override
        overrides_applied.append(f"destination_url: '{destination_url}' -> '{destination_url_override}'")

    effective_cta = cta_type.upper().strip()
    if cta_override:
        effective_cta = cta_override.upper().strip()
        overrides_applied.append(f"cta_type: '{cta_type}' -> '{cta_override}'")

    effective_text = primary_text
    if primary_text_override:
        effective_text = primary_text_override
        overrides_applied.append(f"primary_text overridden")

    effective_headline = headline
    if headline_override:
        effective_headline = headline_override
        overrides_applied.append(f"headline overridden")

    # ============================================================
    # Step 1.5: Auto/Hybrid copy generation
    # ============================================================
    copy_generation_result = None

    if copy_mode in ("auto", "hybrid"):
        try:
            from meta_ads_mcp.engine.copy_generator import generate_copy
        except ImportError:
            return {
                "error": "Auto/hybrid copy generation requires the KonQuest Meta Ads MCP Premium bundle.",
                "blocked_at": "premium_required",
                "note": "Use copy_mode='manual' with the open-core package, or upgrade to premium for vault-driven copy generation.",
            }

        gen_result = generate_copy(
            vault_ctx=vault_ctx,
            concept={"angle": angle_name or "", "icp": icp_name or "", "funnel_stage": funnel_stage},
            funnel_stage=funnel_stage,
            existing_primary_text=effective_text if copy_mode == "hybrid" else None,
            existing_headline=effective_headline if copy_mode == "hybrid" else None,
            existing_description=description if copy_mode == "hybrid" else None,
            copy_mode=copy_mode,
        )

        if gen_result.get("error"):
            return gen_result

        if not gen_result.get("validation_passed"):
            return {
                "error": "Auto-generated copy failed validation. Ad NOT created.",
                "blocked_at": "copy_validation",
                "copy_generation": gen_result,
                "validation_issues": gen_result.get("validation_issues", []),
            }

        # Apply generated copy
        if copy_mode == "auto" or (copy_mode == "hybrid" and not effective_text):
            effective_text = gen_result["generated_primary_text"]
        if copy_mode == "auto" or (copy_mode == "hybrid" and not effective_headline):
            effective_headline = gen_result["generated_headline"]
        if copy_mode == "auto" or (copy_mode == "hybrid" and not description):
            description = gen_result["generated_description"]

        copy_generation_result = gen_result
        overrides_applied.append(f"copy_mode={copy_mode}: copy generated from vault")

    # ============================================================
    # Step 2: Input validation
    # ============================================================

    # CTA validation
    if effective_cta not in VALID_CTA_TYPES:
        return {
            "error": f"Invalid CTA type: '{effective_cta}'.",
            "valid_values": VALID_CTA_TYPES,
            "blocked_at": "input_validation",
        }

    # URL basic validation
    if not effective_url or not effective_url.startswith("http"):
        return {
            "error": f"Invalid destination URL: '{effective_url}'. Must start with http/https.",
            "blocked_at": "input_validation",
        }

    # Detect creative mode
    creative_mode, mode_reason = _detect_creative_mode(entry)

    # For v1.3 corridor: only simple mode is supported
    # Dynamic and DOF require asset_feed_spec which needs uploaded assets
    if creative_mode != "simple":
        return {
            "error": f"Creative mode '{creative_mode}' detected but only 'simple' is supported in v1.3 paused-only corridor. {mode_reason}",
            "creative_mode": creative_mode,
            "mode_reason": mode_reason,
            "blocked_at": "creative_mode_restriction",
        }

    # ============================================================
    # Step 3: Parent ad set inspection
    # ============================================================

    try:
        parent_adset = api_client.graph_get(
            f"/{adset_id}",
            fields=[
                "id", "name", "status", "effective_status", "campaign_id",
                "optimization_goal", "billing_event", "targeting", "promoted_object",
            ],
        )
    except MetaAPIError as e:
        return {"error": f"Cannot read parent ad set {adset_id}: {e}", "blocked_at": "parent_inspection"}

    parent_campaign_id = parent_adset.get("campaign_id", "")
    adset_status = parent_adset.get("effective_status", "")

    if adset_status in ("DELETED", "ARCHIVED"):
        return {
            "error": f"Parent ad set {adset_id} is {adset_status}.",
            "blocked_at": "parent_inspection",
        }

    # ============================================================
    # Step 4: Duplicate prevention
    # ============================================================

    try:
        existing_ads = api_client.graph_get(
            f"/{adset_id}/ads",
            fields=["id", "name", "creative", "status"],
            params={"limit": "100"},
        )
        for existing in existing_ads.get("data", []):
            if existing.get("status") == "DELETED":
                continue
            # Check name match
            if existing.get("name") == ad_name:
                return {
                    "error": f"Duplicate detected: ad with name '{ad_name}' already exists in ad set {adset_id}.",
                    "duplicate_ad_id": existing.get("id"),
                    "duplicate_ad_name": existing.get("name"),
                    "blocked_at": "duplicate_prevention",
                }
    except MetaAPIError as e:
        logger.warning(f"Duplicate check skipped (API error): {e}. Proceeding with creation.")

    # ============================================================
    # Step 4.5: INSTAGRAM IDENTITY GATE (HARD PREFLIGHT)
    # ============================================================
    from meta_ads_mcp.core.identity import enforce_instagram_gate
    ig_gate = enforce_instagram_gate(account_id, page_id, placement_mode)
    if not ig_gate["allowed"]:
        return {
            "error": ig_gate["block_reason"],
            "blocked_at": "instagram_identity_gate",
            "placement_mode": placement_mode,
            "manual_fix_required": ig_gate.get("manual_fix_required", False),
            "manual_fix_steps": ig_gate.get("manual_fix_steps"),
            "allowed_fallbacks": ig_gate.get("allowed_fallbacks"),
        }
    if not instagram_user_id and ig_gate.get("instagram_user_id"):
        instagram_user_id = ig_gate["instagram_user_id"]
        logger.info(f"IG identity resolved via gate: {instagram_user_id}")

    # ============================================================
    # Step 5: Build creative spec
    # ============================================================

    # Inject meta_video_id into entry if provided as parameter
    # This allows the caller to provide a video uploaded via upload_video_asset
    if meta_video_id:
        entry["meta_video_id"] = meta_video_id
        # Also inject into first variant if exists
        variants = entry.get("variants", [])
        if variants:
            variants[0]["meta_video_id"] = meta_video_id

    # Detect asset type for logging
    has_video = bool(
        meta_video_id
        or entry.get("meta_video_id")
        or entry.get("video_id")
        or any(v.get("meta_video_id") or v.get("video_id") for v in entry.get("variants", []))
    )
    asset_type = "video" if has_video else "link"

    object_story_spec = _build_simple_creative_spec(
        entry=entry,
        page_id=page_id,
        instagram_user_id=instagram_user_id,
        destination_url=effective_url,
        primary_text=effective_text,
        headline=effective_headline,
        description=description,
        cta_type=effective_cta,
    )

    # ============================================================
    # Step 6: Pre-write validation
    # ============================================================

    payload_for_validation = {
        "name": ad_name,
        "adset_id": adset_id,
        "status": "PAUSED",
        "creative": {"object_story_spec": object_story_spec},
    }

    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="ad",
        target_object_id=None,
        payload=payload_for_validation,
        safety_tier=3,
        is_ad_creation=True,
        manifest_ref=logical_creative_id,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Ad NOT created.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    # ============================================================
    # Step 7: Dry run gate
    # ============================================================

    if dry_run:
        return {
            "dry_run": True,
            "would_create": {
                "ad_name": ad_name,
                "adset_id": adset_id,
                "creative_mode": creative_mode,
                "mode_reason": mode_reason,
                "cta": effective_cta,
                "destination_url": effective_url,
                "page_id": page_id,
                "instagram_user_id": instagram_user_id,
                "object_story_spec": object_story_spec,
                "overrides_applied": overrides_applied,
            },
            "validation": validation_dict,
            "logical_creative_id": logical_creative_id,
        }

    # ============================================================
    # Step 8: Pre-write snapshot
    # ============================================================

    try:
        existing_count = api_client.graph_get(
            f"/{adset_id}/ads", fields=["id"], params={"limit": "0"},
        )
        pre_ad_count = len(existing_count.get("data", []))
    except MetaAPIError:
        pre_ad_count = "unknown"

    rollback_ref = f"create_ad_{adset_id}_{logical_creative_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # ============================================================
    # Step 9: API call - create ad
    # ============================================================

    api_payload = {
        "adset_id": adset_id,
        "name": ad_name,
        "status": "PAUSED",
        "creative": _json.dumps({"object_story_spec": object_story_spec}),
    }

    try:
        result = api_client.graph_post(
            f"/{account_id}/ads",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during ad creation: {e}",
            "validation": validation_dict,
            "creative_mode": creative_mode,
            "blocked_at": "api_call",
            "rollback_reference": rollback_ref,
        }

    ad_id = result.get("id")
    if not ad_id:
        return {
            "error": "Ad creation returned no ID.",
            "api_response": result,
            "blocked_at": "api_response",
        }

    # ============================================================
    # Step 10: Post-write verification
    # ============================================================

    verification = {
        "ad_id": ad_id,
        "status_verified": False,
        "name_verified": False,
        "adset_link_verified": False,
        "campaign_link_verified": False,
        "creative_verified": False,
        "creative_mode_verified": False,
        "cta_verified": False,
        "destination_verified": False,
        "identity_verified": False,
        "critical_mismatch": False,
    }

    try:
        created = api_client.graph_get(
            f"/{ad_id}",
            fields=[
                "id", "name", "status", "effective_status",
                "adset_id", "campaign_id", "creative",
            ],
        )

        # Status
        if created.get("status") == "PAUSED":
            verification["status_verified"] = True
        else:
            verification["critical_mismatch"] = True
            verification["status_actual"] = created.get("status")
            logger.critical("CRITICAL: Ad %s status is %s!", ad_id, created.get("status"))

        # Name
        if created.get("name") == ad_name:
            verification["name_verified"] = True
        else:
            verification["name_actual"] = created.get("name")
            verification["name_note"] = "Name mismatch - possible encoding issue"

        # Ad set link
        if created.get("adset_id") == adset_id:
            verification["adset_link_verified"] = True

        # Campaign link
        if created.get("campaign_id") == parent_campaign_id:
            verification["campaign_link_verified"] = True

        # Creative attached
        creative_ref = created.get("creative", {})
        created_creative_id = creative_ref.get("id") if isinstance(creative_ref, dict) else None
        if created_creative_id:
            verification["creative_verified"] = True

            # Verify creative details
            try:
                cr = api_client.graph_get(
                    f"/{created_creative_id}",
                    fields=["id", "object_story_spec", "asset_feed_spec",
                            "degrees_of_freedom_spec", "call_to_action_type",
                            "instagram_user_id"],
                )
                # Mode
                has_oss = bool(cr.get("object_story_spec"))
                has_afs = bool(cr.get("asset_feed_spec"))
                has_dof = bool(cr.get("degrees_of_freedom_spec"))
                actual_mode = "dof" if has_dof else ("dynamic" if has_afs else "simple")
                verification["creative_mode_verified"] = actual_mode == creative_mode
                verification["creative_mode_actual"] = actual_mode

                # CTA
                actual_cta = cr.get("call_to_action_type", "")
                if actual_cta == effective_cta:
                    verification["cta_verified"] = True
                else:
                    verification["cta_actual"] = actual_cta

                # Destination URL (from OSS)
                oss = cr.get("object_story_spec", {})
                vd = oss.get("video_data", {})
                ld = oss.get("link_data", {})
                data = vd or ld
                cta_val = data.get("call_to_action", {}).get("value", {})
                actual_url = cta_val.get("link", ld.get("link", ""))
                # Meta normalizes URLs (adds trailing slash, etc.)
                url_match = (
                    actual_url == effective_url
                    or actual_url.rstrip("/") == effective_url.rstrip("/")
                )
                if url_match:
                    verification["destination_verified"] = True
                else:
                    verification["destination_actual"] = actual_url

                # Identity
                actual_ig = cr.get("instagram_user_id")
                if instagram_user_id:
                    verification["identity_verified"] = actual_ig == instagram_user_id
                else:
                    verification["identity_verified"] = True  # Not required

                verification["effective_status"] = created.get("effective_status")

            except MetaAPIError as e:
                verification["creative_detail_error"] = str(e)
        else:
            verification["creative_note"] = "No creative reference returned"

    except MetaAPIError as e:
        verification["verification_error"] = str(e)

    # ============================================================
    # Step 11: Value context (from manifest if available)
    # ============================================================

    value_context = None
    pv = entry.get("product_value")
    if pv and isinstance(pv, dict):
        value_context = {
            "value_amount": pv.get("value_amount"),
            "value_currency": pv.get("value_currency"),
            "value_source": pv.get("value_source"),
            "value_confidence": pv.get("value_confidence"),
            "is_tracked_revenue": pv.get("is_tracked_revenue", False),
            "is_estimated": pv.get("is_estimated", True),
        }

    # ============================================================
    # Step 12: Identity summary
    # ============================================================

    identity = {
        "page_id": page_id,
        "instagram_user_id": instagram_user_id,
        "identity_source": "explicit_parameter",
        "identity_confidence": "high" if instagram_user_id else "page_only",
    }

    # ============================================================
    # Step 13: Destination summary
    # ============================================================

    dest_resolution = entry.get("destination_resolution", {})
    destination = {
        "resolved_url": effective_url,
        "url_source": dest_resolution.get("url_source", "explicit_parameter"),
        "url_confidence": dest_resolution.get("url_confidence", "high"),
        "url_type": dest_resolution.get("url_type", "unknown"),
        "requires_confirmation": dest_resolution.get("requires_confirmation", False),
    }

    # ============================================================
    # Step 14: Mutation log entry
    # ============================================================

    log_entry = (
        f"### [{timestamp}] CREATE ad\n"
        f"- **Account:** {account_id}\n"
        f"- **Campaign:** {parent_campaign_id}\n"
        f"- **Ad Set:** {adset_id} ({parent_adset.get('name', '?')})\n"
        f"- **Ad ID:** {ad_id}\n"
        f"- **Ad Name:** {ad_name}\n"
        f"- **Logical Creative:** {logical_creative_id}\n"
        f"- **Creative mode:** {creative_mode}\n"
        f"- **CTA:** {effective_cta}\n"
        f"- **Destination:** {effective_url} (source: {destination['url_source']})\n"
        f"- **Asset type:** {asset_type}{' (video_id=' + str(meta_video_id) + ')' if meta_video_id else ''}\n"
        f"- **Identity:** page={page_id}, ig={instagram_user_id or 'none'}\n"
        f"- **Status:** PAUSED (enforced)\n"
        f"- **Overrides:** {', '.join(overrides_applied) or 'none'}\n"
        f"- **Validation:** {validation_result.verdict.value}\n"
        f"- **Verification:** status={'OK' if verification['status_verified'] else 'MISMATCH'}, "
        f"name={'OK' if verification['name_verified'] else 'MISMATCH'}, "
        f"creative={'OK' if verification['creative_verified'] else 'MISSING'}, "
        f"cta={'OK' if verification['cta_verified'] else 'MISMATCH'}, "
        f"dest={'OK' if verification['destination_verified'] else 'MISMATCH'}\n"
        f"- **Rollback ref:** {rollback_ref}\n"
    )

    return {
        "ad_id": ad_id,
        "status": "PAUSED",
        "adset_id": adset_id,
        "campaign_id": parent_campaign_id,
        "logical_creative_id": logical_creative_id,
        "creative_mode": creative_mode,
        "asset_type": asset_type,
        "meta_video_id": meta_video_id,
        "mode_reason": mode_reason,
        "cta": effective_cta,
        "destination": destination,
        "identity": identity,
        "value_context": value_context,
        "overrides_applied": overrides_applied,
        "copy_generation": copy_generation_result,
        "validation": validation_dict,
        "verification": verification,
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


# --- Phase C.3: Ad update ---

@mcp.tool()
def update_ad(
    ad_id: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    creative_id: Optional[str] = None,
) -> dict:
    """
    Update an existing ad. Supervised write - validates before applying.

    Takes a pre-write snapshot for rollback, validates the update payload,
    applies via Meta API, and verifies post-write state.

    Note on creative_id: Swaps the creative attached to this ad. The new creative
    must already exist (created via create_multi_asset_ad or the Meta UI).
    This does NOT create a new creative - it re-points the ad to an existing one.

    Args:
        ad_id: Ad ID to update.
        name: New ad name. Subject to naming enforcement.
        status: New status. Allowed: 'PAUSED', 'ACTIVE', 'ARCHIVED'.
            Activating requires confirmation-level validation.
        creative_id: ID of an existing creative to attach to this ad.
            Format: numeric string (e.g., '120239290442460377').
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- At least one field must be provided ---
    if all(v is None for v in [name, status, creative_id]):
        return {
            "error": "No update fields provided. Specify at least one field to update.",
            "supported_fields": ["name", "status", "creative_id"],
            "blocked_at": "input_validation",
        }

    # --- Status validation ---
    allowed_statuses = ["PAUSED", "ACTIVE", "ARCHIVED"]
    if status is not None:
        status_upper = status.upper().strip()
        if status_upper not in allowed_statuses:
            return {
                "error": f"Invalid status '{status}'. Allowed: {allowed_statuses}",
                "blocked_at": "input_validation",
            }
        status = status_upper

    # --- Creative ID validation ---
    if creative_id is not None:
        creative_id = creative_id.strip()
        if not creative_id.isdigit():
            return {
                "error": f"Invalid creative_id '{creative_id}'. Must be a numeric string.",
                "blocked_at": "input_validation",
            }

    # --- Step 0: Pre-write snapshot ---
    api_client._ensure_initialized()
    try:
        current = api_client.graph_get(
            f"/{ad_id}",
            fields=["id", "name", "status", "effective_status",
                     "adset_id", "campaign_id", "creative",
                     "tracking_specs", "account_id"],
        )
    except MetaAPIError as e:
        return {
            "error": f"Cannot read ad {ad_id} for pre-update snapshot: {e}",
            "blocked_at": "pre_snapshot",
        }

    account_id = current.get("account_id", "")
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    rollback_ref = f"update_ad_{ad_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # Extract current creative ID for rollback reference
    current_creative = current.get("creative", {})
    current_creative_id = current_creative.get("id") if isinstance(current_creative, dict) else None

    # --- Step 1: Naming enforcement (if name is being updated) ---
    effective_name = None
    naming_result = None
    if name is not None:
        from meta_ads_mcp.engine.naming_gate import enforce_naming

        naming_result = enforce_naming(
            proposed_name=name,
            object_type="ad",
            naming_inputs=None,
        )

        if naming_result["critical_block"]:
            return {
                "error": f"Naming enforcement BLOCKED: {naming_result.get('fix_suggestion', 'Invalid name')}",
                "naming_result": naming_result,
                "blocked_at": "naming_enforcement",
            }

        effective_name = naming_result["final_name"] or name

    # --- Step 2: Build update payload ---
    api_payload = {}

    if effective_name is not None:
        api_payload["name"] = effective_name
    if status is not None:
        api_payload["status"] = status
    if creative_id is not None:
        # Meta API expects creative as {"creative_id": "123"}
        api_payload["creative"] = _json.dumps({"creative_id": creative_id})

    # --- Step 3: Pre-write validation ---
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    action_class = ActionClass.ACTIVATE if status == "ACTIVE" else ActionClass.MODIFY_ACTIVE

    validation_result = run_validation(
        action_class=action_class,
        target_account_id=account_id,
        target_object_type="ad",
        target_object_id=ad_id,
        payload=api_payload,
        safety_tier=3,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Ad NOT updated.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    if validation_result.verdict.value == "requires_confirmation" and status == "ACTIVE":
        return {
            "status": "requires_confirmation",
            "message": "Activating an ad requires explicit confirmation. Review validation and re-submit.",
            "validation": validation_dict,
            "ad_id": ad_id,
            "current_status": current.get("status"),
            "requested_status": "ACTIVE",
        }

    # --- Step 4: API call - update ad ---
    try:
        result = api_client.graph_post(
            f"/{ad_id}",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during ad update: {e}",
            "validation": validation_dict,
            "blocked_at": "api_call",
            "rollback_reference": rollback_ref,
            "pre_update_state": {
                "name": current.get("name"),
                "status": current.get("status"),
                "creative_id": current_creative_id,
            },
        }

    # --- Step 5: Post-write verification ---
    verification = {
        "ad_id": ad_id,
        "fields_updated": list(api_payload.keys()),
        "mismatches": [],
    }

    try:
        updated = api_client.graph_get(
            f"/{ad_id}",
            fields=["id", "name", "status", "effective_status", "creative"],
        )

        if effective_name is not None:
            actual_name = updated.get("name", "")
            if actual_name != effective_name:
                verification["mismatches"].append({
                    "field": "name", "expected": effective_name, "actual": actual_name,
                })

        if status is not None:
            actual_status = updated.get("status", "")
            if actual_status != status:
                verification["mismatches"].append({
                    "field": "status", "expected": status, "actual": actual_status,
                })

        if creative_id is not None:
            updated_creative = updated.get("creative", {})
            actual_creative_id = updated_creative.get("id") if isinstance(updated_creative, dict) else None
            if actual_creative_id != creative_id:
                verification["mismatches"].append({
                    "field": "creative_id", "expected": creative_id, "actual": actual_creative_id,
                })

        verification["post_update_status"] = updated.get("status")
        verification["post_update_effective_status"] = updated.get("effective_status")
        verification["verified"] = len(verification["mismatches"]) == 0

    except MetaAPIError as e:
        verification["verification_error"] = str(e)
        verification["verified"] = False
        verification["note"] = "Ad was updated but post-verification read failed."

    # --- Step 6: Mutation log entry ---
    fields_summary = ", ".join(f"{k}={v}" for k, v in api_payload.items())
    log_entry = (
        f"### [{timestamp}] UPDATE ad\n"
        f"- **Ad ID:** {ad_id}\n"
        f"- **Account:** {account_id}\n"
        f"- **Fields:** {fields_summary}\n"
        f"- **Validation:** {validation_result.verdict.value}\n"
        f"- **Verification:** {'OK' if verification.get('verified') else 'MISMATCH'}\n"
        f"- **Rollback ref:** {rollback_ref}\n"
        f"- **Pre-update state:** name={current.get('name')}, status={current.get('status')}, "
        f"creative_id={current_creative_id}\n"
    )

    return {
        "ad_id": ad_id,
        "updated_fields": list(api_payload.keys()),
        "validation": validation_dict,
        "verification": verification,
        "pre_update_state": {
            "name": current.get("name"),
            "status": current.get("status"),
            "effective_status": current.get("effective_status"),
            "creative_id": current_creative_id,
            "adset_id": current.get("adset_id"),
            "campaign_id": current.get("campaign_id"),
        },
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
