"""
Creative management tools.

Handles ad creatives including three creation modes:
  1. Simple: single image/video with object_story_spec
  2. Dynamic Creative: multiple text/media variants via asset_feed_spec
  3. FLEX/DOF: Advantage+ Creative with degrees_of_freedom

Supports asset_feed_spec, asset_customization_rules, and
placement-specific asset assignment.

Phase: v1.1 (read) / v1.3 (write).
"""
import logging
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.creatives")


# Placement group translation (human-readable -> Meta API)
PLACEMENT_GROUP_MAP = {
    "FEED": {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "marketplace", "search"],
        "instagram_positions": ["stream", "explore"],
    },
    "STORY": {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["story"],
        "instagram_positions": ["story"],
    },
    "REELS": {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["reels"],
        "instagram_positions": ["reels"],
    },
    "INSTREAM_VIDEO": {
        "publisher_platforms": ["facebook"],
        "facebook_positions": ["instream_video"],
    },
    "MESSENGER": {
        "publisher_platforms": ["messenger"],
        "messenger_positions": ["story"],
    },
    "SEARCH": {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["search"],
        "instagram_positions": ["explore"],
    },
    "AUDIENCE_NETWORK": {
        "publisher_platforms": ["audience_network"],
        "audience_network_positions": ["classic", "rewarded_video"],
    },
}

# Fields for creative list (compact)
CREATIVE_LIST_FIELDS = [
    "id", "name", "status", "title", "body",
    "thumbnail_url", "image_url",
    "call_to_action_type",
    "effective_object_story_id",
]

# Fields for creative detail (full)
CREATIVE_DETAIL_FIELDS = [
    "id", "name", "status", "title", "body",
    "thumbnail_url", "image_url", "image_hash",
    "object_story_spec", "asset_feed_spec",
    "degrees_of_freedom_spec",
    "url_tags", "call_to_action_type",
    "effective_object_story_id",
    "object_url", "link_url",
    "video_id",
    "instagram_user_id", "instagram_actor_id",
    "source_instagram_media_id",
    "object_type",
]


def _classify_creative_mode(creative: dict) -> str:
    """Classify creative into simple/dynamic/dof based on spec presence."""
    if creative.get("degrees_of_freedom_spec"):
        return "dof"
    if creative.get("asset_feed_spec"):
        return "dynamic"
    return "simple"


def _resolve_image_hashes(account_id: str, image_hashes: list[str]) -> dict:
    """Resolve image hashes to URLs via the account's ad images endpoint."""
    resolved = {}
    if not image_hashes:
        return resolved

    try:
        # Batch lookup: get images by hash
        hash_filter = ",".join(image_hashes)
        result = api_client.graph_get(
            f"/{account_id}/adimages",
            fields=["hash", "url", "url_128", "name", "width", "height"],
            params={"hashes": hash_filter},
        )
        images = result.get("data", {})
        # adimages returns a dict keyed by hash, not an array
        if isinstance(images, dict):
            resolved = images
        elif isinstance(images, list):
            for img in images:
                h = img.get("hash")
                if h:
                    resolved[h] = img
    except MetaAPIError as e:
        logger.warning("Could not resolve image hashes: %s", e)

    return resolved


def _extract_media_urls(creative: dict, account_id: Optional[str] = None) -> dict:
    """
    Extract all media URLs from a creative, resolving hashes where needed.

    Returns a structured media summary.
    """
    media = {
        "thumbnail_url": creative.get("thumbnail_url"),
        "image_url": creative.get("image_url"),
        "video_id": creative.get("video_id"),
        "images": [],
        "videos": [],
    }

    # From object_story_spec
    oss = creative.get("object_story_spec", {})
    if oss:
        # Video data
        video_data = oss.get("video_data", {})
        if video_data:
            media["videos"].append({
                "video_id": video_data.get("video_id"),
                "image_url": video_data.get("image_url"),
                "title": video_data.get("title"),
                "message": video_data.get("message"),
                "call_to_action": video_data.get("call_to_action"),
            })

        # Link data (image ads)
        link_data = oss.get("link_data", {})
        if link_data:
            img_hash = link_data.get("image_hash")
            img_url = link_data.get("picture") or link_data.get("image_url")
            if img_hash and account_id:
                resolved = _resolve_image_hashes(account_id, [img_hash])
                if img_hash in resolved:
                    img_url = resolved[img_hash].get("url", img_url)
            media["images"].append({
                "image_hash": img_hash,
                "image_url": img_url,
                "link": link_data.get("link"),
                "message": link_data.get("message"),
                "name": link_data.get("name"),
                "description": link_data.get("description"),
                "call_to_action": link_data.get("call_to_action"),
            })

            # Carousel child attachments
            children = link_data.get("child_attachments", [])
            for child in children:
                child_hash = child.get("image_hash")
                child_url = child.get("picture")
                if child_hash and account_id:
                    resolved = _resolve_image_hashes(account_id, [child_hash])
                    if child_hash in resolved:
                        child_url = resolved[child_hash].get("url", child_url)
                media["images"].append({
                    "image_hash": child_hash,
                    "image_url": child_url,
                    "link": child.get("link"),
                    "name": child.get("name"),
                    "description": child.get("description"),
                    "video_id": child.get("video_id"),
                })

    # From asset_feed_spec (dynamic creative)
    afs = creative.get("asset_feed_spec", {})
    if afs:
        for img in afs.get("images", []):
            img_hash = img.get("hash")
            img_url = img.get("url")
            if img_hash and not img_url and account_id:
                resolved = _resolve_image_hashes(account_id, [img_hash])
                if img_hash in resolved:
                    img_url = resolved[img_hash].get("url")
            media["images"].append({
                "image_hash": img_hash,
                "image_url": img_url,
            })
        for vid in afs.get("videos", []):
            media["videos"].append({
                "video_id": vid.get("video_id"),
                "thumbnail_url": vid.get("thumbnail_url"),
            })

    return media


@mcp.tool()
def get_ad_creatives(
    account_id: str,
    ad_id: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    List ad creatives for an account or specific ad, with image hash resolution.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789'). Used for image hash resolution.
        ad_id: Optional ad ID. If provided, returns the creative for that specific ad.
        limit: Max results when listing account creatives (default 50).
    """
    api_client._ensure_initialized()

    from meta_ads_mcp.core.utils import ensure_account_id_format
    account_id = ensure_account_id_format(account_id)

    if ad_id:
        # Get the creative for a specific ad
        try:
            ad_result = api_client.graph_get(
                f"/{ad_id}",
                fields=["creative"],
            )
            creative_ref = ad_result.get("creative", {})
            creative_id = creative_ref.get("id") if isinstance(creative_ref, dict) else None
            if not creative_id:
                return {"error": f"No creative found for ad {ad_id}"}

            detail = api_client.graph_get(
                f"/{creative_id}",
                fields=CREATIVE_DETAIL_FIELDS,
            )
            detail["creative_mode"] = _classify_creative_mode(detail)
            detail["media"] = _extract_media_urls(detail, account_id)

            return {
                "total": 1,
                "creatives": [detail],
                "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
            }
        except MetaAPIError:
            raise

    # List all creatives for account
    try:
        result = api_client.graph_get(
            f"/{account_id}/adcreatives",
            fields=CREATIVE_LIST_FIELDS,
            params={"limit": str(min(limit, 100))},
        )

        creatives = result.get("data", [])

        # Paginate
        all_creatives = list(creatives)
        paging = result.get("paging", {})
        while paging.get("next") and len(all_creatives) < 200:
            after = paging.get("cursors", {}).get("after")
            if not after:
                break
            result = api_client.graph_get(
                f"/{account_id}/adcreatives",
                fields=CREATIVE_LIST_FIELDS,
                params={"limit": str(min(limit, 100)), "after": after},
            )
            next_batch = result.get("data", [])
            if not next_batch:
                break
            all_creatives.extend(next_batch)
            paging = result.get("paging", {})

        return {
            "total": len(all_creatives),
            "creatives": all_creatives,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def get_creative_details(
    creative_id: str,
    account_id: Optional[str] = None,
) -> dict:
    """
    Get full creative details including mode classification, media URLs,
    object_story_spec, asset_feed_spec, and degrees_of_freedom_spec.

    Args:
        creative_id: Creative ID (numeric string).
        account_id: Optional account ID for image hash resolution. If not provided,
            image hashes will not be resolved to URLs.
    """
    api_client._ensure_initialized()

    if account_id:
        from meta_ads_mcp.core.utils import ensure_account_id_format
        account_id = ensure_account_id_format(account_id)

    try:
        result = api_client.graph_get(
            f"/{creative_id}",
            fields=CREATIVE_DETAIL_FIELDS,
        )

        # Classify mode
        result["creative_mode"] = _classify_creative_mode(result)

        # Extract and resolve media
        result["media"] = _extract_media_urls(result, account_id)

        # Extract copy elements for easy access
        copy = {}
        oss = result.get("object_story_spec", {})
        if oss:
            link_data = oss.get("link_data", {})
            video_data = oss.get("video_data", {})
            data = link_data or video_data
            if data:
                copy["message"] = data.get("message")
                copy["headline"] = data.get("name") or result.get("title")
                copy["description"] = data.get("description")
                copy["link"] = data.get("link")
                cta = data.get("call_to_action", {})
                if cta:
                    copy["cta_type"] = cta.get("type")
                    cta_value = cta.get("value", {})
                    if isinstance(cta_value, dict):
                        copy["cta_link"] = cta_value.get("link")

        afs = result.get("asset_feed_spec", {})
        if afs:
            copy["bodies"] = [b.get("text") for b in afs.get("bodies", [])]
            copy["titles"] = [t.get("text") for t in afs.get("titles", [])]
            copy["descriptions"] = [d.get("text") for d in afs.get("descriptions", [])]
            copy["link_urls"] = [l.get("website_url") for l in afs.get("link_urls", [])]

        if copy:
            result["copy"] = copy

        # Identity info
        ig_user = result.get("instagram_user_id")
        ig_actor = result.get("instagram_actor_id")
        if ig_user or ig_actor:
            result["identity"] = {
                "instagram_user_id": ig_user,
                "instagram_actor_id_deprecated": ig_actor,
                "note": "Use instagram_user_id as canonical. instagram_actor_id is deprecated." if ig_actor else None,
            }

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except MetaAPIError:
        raise


# --- Wave 1.3: Standalone Creative Creation ---

VALID_CTA_TYPES = [
    "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "CONTACT_US",
    "GET_OFFER", "BOOK_TRAVEL", "DOWNLOAD", "APPLY_NOW", "WATCH_MORE",
    "GET_QUOTE", "SEND_MESSAGE", "ORDER_NOW", "NO_BUTTON",
]


@mcp.tool()
def create_ad_creative(
    account_id: str,
    page_id: str,
    image_hash: str,
    link_url: str,
    primary_text: str,
    headline: Optional[str] = None,
    description: Optional[str] = None,
    cta_type: str = "LEARN_MORE",
    name: Optional[str] = None,
) -> dict:
    """
    Create a standalone single-image ad creative.

    Returns creative_id for use in ad creation (create_ad_from_manifest)
    or ad update (update_ad creative swap).

    Requires a Facebook Page ID. Instagram identity is auto-resolved
    from the page - if unavailable, creative is created for Facebook only.

    Single-image creatives only in v1. For video, carousel, or dynamic
    creatives, use create_multi_asset_ad.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        page_id: Facebook Page ID for the creative.
        image_hash: Image hash from upload_ad_image.
        link_url: CTA destination URL.
        primary_text: Main ad copy text (the "message").
        headline: Optional headline (appears below image).
        description: Optional description text.
        cta_type: Call-to-action type. Default 'LEARN_MORE'.
            Valid: LEARN_MORE, SHOP_NOW, SIGN_UP, SUBSCRIBE, CONTACT_US,
            GET_OFFER, BOOK_TRAVEL, DOWNLOAD, APPLY_NOW, WATCH_MORE,
            GET_QUOTE, SEND_MESSAGE, ORDER_NOW, NO_BUTTON.
        name: Optional creative name. Subject to naming enforcement.
    """
    # Input validation
    if not image_hash or not image_hash.strip():
        return {
            "error": "image_hash is required. Use upload_ad_image to get one.",
            "blocked_at": "input_validation",
        }

    if not link_url or not link_url.strip():
        return {
            "error": "link_url is required.",
            "blocked_at": "input_validation",
        }

    if not primary_text or not primary_text.strip():
        return {
            "error": "primary_text is required.",
            "blocked_at": "input_validation",
        }

    if not page_id or not page_id.strip():
        return {
            "error": "page_id is required.",
            "blocked_at": "input_validation",
        }

    cta_upper = cta_type.upper().strip()
    if cta_upper not in VALID_CTA_TYPES:
        return {
            "error": f"Invalid cta_type: '{cta_type}'. Valid: {VALID_CTA_TYPES}",
            "blocked_at": "input_validation",
        }

    account_id = ensure_account_id_format(account_id)
    image_hash = image_hash.strip()
    link_url = link_url.strip()
    primary_text = primary_text.strip()

    api_client._ensure_initialized()

    # Resolve Instagram identity (best-effort, not blocking)
    ig_id = None
    try:
        from meta_ads_mcp.core.ad_builder import resolve_instagram_identity
        ig_result = resolve_instagram_identity(page_id, account_id)
        ig_id = ig_result.get("instagram_user_id")
    except Exception:
        logger.warning("Could not resolve Instagram identity for page %s", page_id)

    # Naming enforcement (if name provided)
    effective_name = None
    if name:
        from meta_ads_mcp.engine.naming_gate import enforce_naming
        naming_result = enforce_naming(
            proposed_name=name,
            object_type="ad",  # creatives follow ad naming convention
            naming_inputs=None,
        )
        if naming_result["critical_block"]:
            return {
                "error": f"Naming enforcement blocked: {naming_result.get('fix_suggestion', '')}",
                "naming_result": naming_result,
                "blocked_at": "naming_enforcement",
            }
        effective_name = naming_result["final_name"] or name

    # Build object_story_spec
    link_data = {
        "link": link_url,
        "message": primary_text,
        "image_hash": image_hash,
    }

    if headline:
        link_data["name"] = headline.strip()
    if description:
        link_data["description"] = description.strip()

    if cta_upper != "NO_BUTTON":
        link_data["call_to_action"] = {
            "type": cta_upper,
            "value": {"link": link_url},
        }

    object_story_spec = {
        "page_id": page_id,
        "link_data": link_data,
    }

    if ig_id:
        object_story_spec["instagram_user_id"] = ig_id

    # Build creative payload
    import json as _json

    payload = {
        "object_story_spec": _json.dumps(object_story_spec, ensure_ascii=False),
    }
    if effective_name:
        payload["name"] = effective_name

    # Validation
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="creative",
        target_object_id=None,
        payload=payload,
        safety_tier=3,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Validation failed. Creative NOT created.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    # Create via Meta API
    try:
        result = api_client.graph_post(
            f"/{account_id}/adcreatives",
            data=payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during creative creation: {e}",
            "blocked_at": "api_call",
        }

    creative_id = result.get("id")
    if not creative_id:
        return {
            "error": "Creative creation returned no ID.",
            "api_response": result,
            "blocked_at": "api_response",
        }

    # Post-write verification
    verified = False
    try:
        created = api_client.graph_get(
            f"/{creative_id}",
            fields=["id", "name", "status", "object_story_spec", "thumbnail_url"],
        )
        verified = created.get("id") == creative_id
    except MetaAPIError:
        pass

    return {
        "creative_id": creative_id,
        "account_id": account_id,
        "page_id": page_id,
        "instagram_user_id": ig_id,
        "image_hash": image_hash,
        "link_url": link_url,
        "cta_type": cta_upper,
        "name": effective_name,
        "verified": verified,
        "validation": validation_dict,
        "usage": {
            "ad_creation": f"Use creative_id '{creative_id}' in create_ad_from_manifest",
            "ad_update": f"Use creative_id '{creative_id}' in update_ad to swap creative",
        },
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }



# --- Gap Closure: Creative Update ---
# NOTE: Meta API does NOT allow updating object_story_spec (copy, headline,
# CTA, link URL) on existing creatives. Only name and status can be updated.
# To change ad copy, create a NEW creative via create_ad_creative, then swap
# it on the ad via update_ad(creative_id=new_id).

@mcp.tool()
def update_ad_creative(
    creative_id: str,
    name: Optional[str] = None,
) -> dict:
    """
    Update an existing ad creative's name.

    IMPORTANT: Meta API does NOT allow changing copy, headline, CTA, or link URL
    on existing creatives. Creative content is immutable after creation.

    To change ad copy: create a NEW creative with create_ad_creative, then swap
    it on the ad with update_ad(creative_id=new_creative_id).

    Args:
        creative_id: Creative ID to update.
        name: New creative name.
    """
    if name is None or not name.strip():
        return {
            "error": "name is required. Meta only allows updating creative name (not copy/headline/CTA).",
            "note": "To change ad copy, create a NEW creative with create_ad_creative, then swap via update_ad.",
            "blocked_at": "input_validation",
        }

    api_client._ensure_initialized()

    try:
        current = api_client.graph_get(
            f"/{creative_id}",
            fields=["id", "name"],
        )
    except MetaAPIError as e:
        return {"error": f"Cannot read creative {creative_id}: {e}", "blocked_at": "pre_snapshot"}

    try:
        api_client.graph_post(
            f"/{creative_id}",
            data={"name": name.strip()},
        )
    except MetaAPIError as e:
        return {"error": f"Meta API error: {e}", "blocked_at": "api_call"}

    return {
        "creative_id": creative_id,
        "updated_name": name.strip(),
        "previous_name": current.get("name"),
        "note": "Only name updated. Creative content (copy, headline, CTA, image) is immutable. To change copy, create a new creative and swap via update_ad.",
    }
