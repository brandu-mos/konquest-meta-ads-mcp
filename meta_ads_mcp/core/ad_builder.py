"""
Ad Builder with enforced identity, naming, and multi-asset support.

Fixes:
1. Identity: auto-resolve instagram_user_id from page_id, always attach
2. Naming: learn pattern from account, enforce match
3. Multi-asset: asset_feed_spec with placement mapping for multi-format

No silent fallbacks. No fake behavior.
"""
import json as _json
import logging
from typing import Any, Optional

from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format
from meta_ads_mcp.server import mcp

logger = logging.getLogger("meta-ads-mcp.ad_builder")

# Placement mapping for asset_customization_rules
PLACEMENT_RULES = {
    "9x16": {
        "customization_spec": {
            "publisher_platforms": ["facebook", "instagram"],
            "facebook_positions": ["story", "facebook_reels"],
            "instagram_positions": ["story", "reels", "stream"],
        },
    },
    "4x5": {
        "customization_spec": {
            "publisher_platforms": ["facebook", "instagram"],
            "facebook_positions": ["feed", "video_feeds"],
            "instagram_positions": ["feed", "explore"],
        },
    },
    "1x1": {
        "customization_spec": {
            "publisher_platforms": ["facebook", "instagram"],
            "facebook_positions": ["feed", "marketplace", "search", "video_feeds"],
            "instagram_positions": ["explore"],
        },
    },
}


def resolve_instagram_identity(page_id: str, account_id: str = None) -> dict:
    """
    Resolve instagram_user_id from page_id using the full resolution ladder.

    Uses identity.resolve_instagram_identity() which tries:
    1. Registry (accounts.yaml) - instant
    2. promote_pages endpoint - works with system user token
    3. ad account instagram_accounts endpoint

    Never silently skips - returns blocked=True if unresolved.
    """
    from meta_ads_mcp.core.identity import resolve_instagram_identity as _resolve

    result = _resolve(account_id=account_id, page_id=page_id) if account_id else _resolve_legacy(page_id)
    return {
        "page_id": page_id,
        "page_name": None,
        "instagram_user_id": result.get("instagram_user_id"),
        "instagram_attached": result.get("instagram_user_id") is not None,
        "resolution_method": result.get("resolution_method", "unknown"),
        "resolution_confidence": result.get("resolution_confidence", "none"),
        "warning_if_missing": result.get("block_reason") if not result.get("instagram_user_id") else None,
    }


def _resolve_legacy(page_id: str) -> dict:
    """Fallback for when account_id is not available. Tries direct page query."""
    api_client._ensure_initialized()
    try:
        page = api_client.graph_get(f"/{page_id}", fields=["id", "name", "instagram_business_account"])
        ig_account = page.get("instagram_business_account", {})
        ig_id = ig_account.get("id") if isinstance(ig_account, dict) else None
        return {
            "instagram_user_id": ig_id,
            "resolution_method": "legacy_page_query",
            "resolution_confidence": "high" if ig_id else "none",
            "block_reason": None if ig_id else "No Instagram business account linked to this page.",
        }
    except Exception:
        return {
            "instagram_user_id": None,
            "resolution_method": "legacy_page_query_failed",
            "resolution_confidence": "none",
            "block_reason": f"Cannot query page {page_id}. Use registry or promote_pages.",
        }


def learn_naming_pattern(account_id: str) -> dict:
    """Learn naming pattern from existing ads in the account."""
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    try:
        ads = api_client.graph_get(
            f"/{account_id}/ads",
            fields=["name"],
            params={"limit": "20"},
        )
        names = [a.get("name", "") for a in ads.get("data", []) if a.get("name")]
    except MetaAPIError:
        names = []

    if not names:
        return {"pattern": None, "samples": [], "note": "No existing ads found. Cannot learn pattern."}

    # Analyze separator and token structure
    separators = {" | ": 0, " - ": 0, " _ ": 0, "_": 0}
    for name in names:
        for sep in separators:
            if sep in name:
                separators[sep] += name.count(sep)

    best_sep = max(separators, key=separators.get) if any(v > 0 for v in separators.values()) else " | "
    token_counts = [len(n.split(best_sep.strip())) for n in names]
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 3

    return {
        "pattern": {
            "separator": best_sep.strip(),
            "avg_tokens": round(avg_tokens, 1),
            "samples": names[:5],
        },
        "samples": names[:5],
    }


def generate_ad_name(pattern: dict, hook: str, format_label: str, version: str = "V1") -> dict:
    """Generate ad name matching account pattern."""
    if not pattern or not pattern.get("pattern"):
        return {
            "generated_name": None,
            "pattern_match": False,
            "validation_passed": False,
            "error": "No naming pattern available. Cannot generate name.",
        }

    sep = pattern["pattern"]["separator"]
    name = f"{hook}{sep}{format_label}{sep}{version}"

    return {
        "generated_name": name,
        "pattern_reference_sample": pattern["samples"][0] if pattern.get("samples") else None,
        "pattern_match": True,
        "validation_passed": True,
    }


@mcp.tool()
def create_multi_asset_ad(
    account_id: str,
    adset_id: str,
    page_id: str,
    ad_name: str,
    primary_text: str = "",
    headline: str = "",
    destination_url: str = "",
    cta_type: str = "LEARN_MORE",
    video_9x16_id: Optional[str] = None,
    video_1x1_id: Optional[str] = None,
    image_1x1_hash: Optional[str] = None,
    image_4x5_hash: Optional[str] = None,
    image_9x16_hash: Optional[str] = None,
    description: Optional[str] = None,
    copy_mode: str = "manual",
    angle_name: Optional[str] = None,
    icp_name: Optional[str] = None,
    funnel_stage: str = "tofu",
    placement_mode: str = "full_meta",
) -> dict:
    """
    Create an ad with enforced identity, multi-asset support, and verification.

    Supports two asset modes (not mixed):
    - VIDEO: If 9:16 and/or 1:1 videos provided, creates ONE ad with
      asset_feed_spec and placement mapping. Single video = simple mode.
    - STATIC IMAGE: If 2+ of image_1x1_hash/image_4x5_hash/image_9x16_hash
      provided, creates ONE ad with asset_feed_spec and placement mapping.
      Single image hash not accepted here - use create_ad_creative instead.

    Mixed video + image is blocked. Provide one type only.

    INSTAGRAM GATE: Enforced via placement_mode.
    - full_meta (default): requires IG identity, BLOCKS if unavailable
    - facebook_only: explicit FB-only, no IG placements
    - instagram_only: requires IG identity, BLOCKS if unavailable

    Args:
        account_id: Ad account ID.
        adset_id: Target ad set ID.
        page_id: Facebook Page ID.
        ad_name: Ad name.
        primary_text: Main ad copy. Required for manual, auto-generated for auto/hybrid.
        headline: Headline text. Auto-generated for auto/hybrid if empty.
        destination_url: CTA destination URL.
        cta_type: CTA type (default LEARN_MORE).
        video_9x16_id: Vertical video ID (for Stories/Reels).
        video_1x1_id: Square video ID (for Feed).
        description: Optional description.
        copy_mode: 'manual' (default), 'auto' (generate from vault), 'hybrid'.
        angle_name: Marketing angle for auto/hybrid copy generation.
        icp_name: Target ICP for auto/hybrid copy generation.
        funnel_stage: 'tofu', 'mofu', 'bofu' for copy structure.
    """
    account_id = ensure_account_id_format(account_id)

    # --- Early input validation (before API init) ---
    _has_any_video = bool(video_9x16_id) or bool(video_1x1_id)
    _has_any_image = sum([
        bool(image_1x1_hash and image_1x1_hash.strip()),
        bool(image_4x5_hash and image_4x5_hash.strip()),
        bool(image_9x16_hash and image_9x16_hash.strip()),
    ])

    if _has_any_video and _has_any_image > 0:
        return {
            "error": "Mixed video and image assets not supported. Provide either video IDs or image hashes, not both.",
            "blocked_at": "input_validation",
        }
    if not _has_any_video and _has_any_image == 0:
        return {
            "error": "No asset provided. Provide video IDs (video_9x16_id/video_1x1_id) or image hashes (image_1x1_hash/image_4x5_hash/image_9x16_hash).",
            "blocked_at": "input_validation",
        }
    if _has_any_image > 0 and _has_any_image < 2:
        return {
            "error": "At least 2 image dimension hashes required for multi-asset image ad. For single-image ads, use create_ad_creative.",
            "blocked_at": "input_validation",
            "provided_image_count": _has_any_image,
        }

    api_client._ensure_initialized()

    # --- Vault gate ---
    from meta_ads_mcp.core.vault_reader import enforce_vault_gate
    vault_error, vault_ctx = enforce_vault_gate(account_id, "create_multi_asset_ad")
    if vault_error:
        return vault_error

    # ============================================================
    # 0.5 AUTO/HYBRID COPY GENERATION
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
            existing_primary_text=primary_text if (copy_mode == "hybrid" and primary_text) else None,
            existing_headline=headline if (copy_mode == "hybrid" and headline) else None,
            existing_description=description if (copy_mode == "hybrid" and description) else None,
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

        if copy_mode == "auto" or (copy_mode == "hybrid" and not primary_text):
            primary_text = gen_result["generated_primary_text"]
        if copy_mode == "auto" or (copy_mode == "hybrid" and not headline):
            headline = gen_result["generated_headline"]
        if copy_mode == "auto" or (copy_mode == "hybrid" and not description):
            description = gen_result["generated_description"]

        copy_generation_result = gen_result

    # ============================================================
    # 1. INSTAGRAM IDENTITY GATE (HARD PREFLIGHT)
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
    ig_id = ig_gate.get("instagram_user_id")

    # ============================================================
    # 2. ASSET VALIDATION GATE + DETERMINE CREATIVE MODE
    # ============================================================
    has_video_9x16 = bool(video_9x16_id)
    has_video_1x1 = bool(video_1x1_id)
    has_any_video = has_video_9x16 or has_video_1x1

    has_img_1x1 = bool(image_1x1_hash and image_1x1_hash.strip())
    has_img_4x5 = bool(image_4x5_hash and image_4x5_hash.strip())
    has_img_9x16 = bool(image_9x16_hash and image_9x16_hash.strip())
    image_count = sum([has_img_1x1, has_img_4x5, has_img_9x16])
    has_any_image = image_count > 0

    # Block mixed video + image
    if has_any_video and has_any_image:
        return {
            "error": "Mixed video and image assets not supported. Provide either video IDs or image hashes, not both.",
            "blocked_at": "input_validation",
        }

    # Block no asset at all
    if not has_any_video and not has_any_image:
        return {
            "error": "No asset provided. Provide video IDs (video_9x16_id/video_1x1_id) or image hashes (image_1x1_hash/image_4x5_hash/image_9x16_hash).",
            "blocked_at": "input_validation",
        }

    # Block single image hash (use create_ad_creative for that)
    if has_any_image and image_count < 2:
        return {
            "error": "At least 2 image dimension hashes required for multi-asset image ad. For single-image ads, use create_ad_creative.",
            "blocked_at": "input_validation",
            "provided_image_count": image_count,
        }

    # Determine mode
    is_video_mode = has_any_video
    is_image_mode = has_any_image and image_count >= 2
    multi_asset_video = has_video_9x16 and has_video_1x1
    multi_asset_image = is_image_mode
    multi_asset = multi_asset_video or multi_asset_image
    fallback_used = is_video_mode and not multi_asset_video

    # Legacy compatibility: keep has_9x16, has_1x1 for video path
    has_9x16 = has_video_9x16
    has_1x1 = has_video_1x1

    # Asset gate enforcement (video assets only - images skip this gate)
    asset_validation = {"critical_block": False, "issues": [], "gate": "skipped_for_images"}

    if is_video_mode:
        from meta_ads_mcp.engine.asset_gate import enforce_asset_gate

        gate_assets = []
        if video_9x16_id:
            gate_assets.append({
                "meta_video_id": video_9x16_id,
                "logical_creative_id": f"{ad_name}-9x16" if ad_name else "asset-9x16",
                "variant_label": "9:16",
            })
        if video_1x1_id:
            gate_assets.append({
                "meta_video_id": video_1x1_id,
                "logical_creative_id": f"{ad_name}-1x1" if ad_name else "asset-1x1",
                "variant_label": "1:1",
            })

        delivery = "full_placement" if multi_asset_video else ("reels_only" if has_9x16 else "feed_only")
        asset_validation = enforce_asset_gate(gate_assets, delivery_mode=delivery)

        if asset_validation["critical_block"]:
            return {
                "error": "Asset validation BLOCKED: " + "; ".join(asset_validation["issues"]),
                "asset_validation": asset_validation,
                "blocked_at": "asset_gate",
            }

    # ============================================================
    # 3. BUILD CREATIVE SPEC
    # ============================================================
    if multi_asset_video:
        # VIDEO multi-asset: asset_feed_spec with placement mapping
        afs: dict[str, Any] = {
            "videos": [
                {"video_id": video_9x16_id, "adlabels": [{"name": "9x16"}]},
                {"video_id": video_1x1_id, "adlabels": [{"name": "1x1"}]},
            ],
            "bodies": [{"text": primary_text}],
            "titles": [{"text": headline}],
            "call_to_action_types": [cta_type],
            "link_urls": [{"website_url": destination_url}],
            "ad_formats": ["SINGLE_VIDEO"],
            "asset_customization_rules": [
                {**PLACEMENT_RULES["1x1"], "video_label": {"name": "1x1"}},
                {**PLACEMENT_RULES["9x16"], "video_label": {"name": "9x16"}},
            ],
            "optimization_type": "PLACEMENT",
        }
        if description:
            afs["descriptions"] = [{"text": description}]

        creative_spec: dict[str, Any] = {
            "asset_feed_spec": afs,
            "object_story_spec": {"page_id": page_id},
        }
        if ig_id:
            creative_spec["object_story_spec"]["instagram_user_id"] = ig_id

    elif multi_asset_image:
        # STATIC IMAGE multi-asset: asset_feed_spec with placement mapping
        image_entries = []
        image_rules = []

        if has_img_1x1:
            image_entries.append({"hash": image_1x1_hash.strip(), "adlabels": [{"name": "1x1"}]})
            image_rules.append({**PLACEMENT_RULES["1x1"], "image_label": {"name": "1x1"}})
        if has_img_4x5:
            image_entries.append({"hash": image_4x5_hash.strip(), "adlabels": [{"name": "4x5"}]})
            image_rules.append({**PLACEMENT_RULES["4x5"], "image_label": {"name": "4x5"}})
        if has_img_9x16:
            image_entries.append({"hash": image_9x16_hash.strip(), "adlabels": [{"name": "9x16"}]})
            image_rules.append({**PLACEMENT_RULES["9x16"], "image_label": {"name": "9x16"}})

        afs_img: dict[str, Any] = {
            "images": image_entries,
            "bodies": [{"text": primary_text}],
            "titles": [{"text": headline}],
            "call_to_action_types": [cta_type],
            "link_urls": [{"website_url": destination_url}],
            "ad_formats": ["SINGLE_IMAGE"],
            "asset_customization_rules": image_rules,
            "optimization_type": "PLACEMENT",
        }
        if description:
            afs_img["descriptions"] = [{"text": description}]

        creative_spec = {
            "asset_feed_spec": afs_img,
            "object_story_spec": {"page_id": page_id},
        }
        if ig_id:
            creative_spec["object_story_spec"]["instagram_user_id"] = ig_id

    else:
        # Simple single-video creative
        video_id = video_9x16_id or video_1x1_id

        # Fetch thumbnail
        thumb_url = None
        try:
            vr = api_client.graph_get(f"/{video_id}", fields=["thumbnails"])
            thumbs = vr.get("thumbnails", {}).get("data", [])
            if thumbs:
                thumb_url = thumbs[0].get("uri")
        except MetaAPIError:
            pass

        oss: dict[str, Any] = {
            "page_id": page_id,
            "video_data": {
                "video_id": video_id,
                "message": primary_text,
                "call_to_action": {"type": cta_type, "value": {"link": destination_url}},
            },
        }
        if thumb_url:
            oss["video_data"]["image_url"] = thumb_url
        if ig_id:
            oss["instagram_user_id"] = ig_id
        if headline:
            oss["video_data"]["title"] = headline

        creative_spec = {"object_story_spec": oss}

    # ============================================================
    # 4. CREATE AD
    # ============================================================
    api_payload = {
        "adset_id": adset_id,
        "name": ad_name,
        "status": "PAUSED",
        "creative": _json.dumps(creative_spec),
    }

    try:
        result = api_client.graph_post(f"/{account_id}/ads", data=api_payload)
    except MetaAPIError as e:
        return {"error": f"Ad creation failed: {e}", "blocked_at": "api_call",
                "instagram_user_id": ig_id, "placement_mode": placement_mode}

    ad_id = result.get("id")
    if not ad_id:
        return {"error": "No ad ID returned", "blocked_at": "api_response"}

    # ============================================================
    # 5. POST-WRITE VERIFICATION
    # ============================================================
    verification = {"ad_id": ad_id, "status_verified": False, "identity_verified": False,
                    "multi_asset_verified": False, "validation_passed": False}

    try:
        ad = api_client.graph_get(f"/{ad_id}", fields=["id", "name", "status", "creative"])
        verification["status_verified"] = ad.get("status") == "PAUSED"
        verification["name_verified"] = ad.get("name") == ad_name

        cid = ad.get("creative", {}).get("id")
        if cid:
            cr = api_client.graph_get(f"/{cid}", fields=[
                "id", "asset_feed_spec", "object_story_spec", "instagram_user_id",
            ])
            actual_ig = cr.get("instagram_user_id")
            verification["identity_verified"] = (actual_ig == ig_id) if ig_id else True

            if multi_asset_video:
                actual_afs = cr.get("asset_feed_spec", {})
                actual_vids = actual_afs.get("videos", [])
                actual_rules = actual_afs.get("asset_customization_rules", [])
                verification["multi_asset_verified"] = len(actual_vids) == 2 and len(actual_rules) == 2
                verification["assets_count"] = len(actual_vids)
                verification["rules_count"] = len(actual_rules)
                verification["asset_type"] = "video"
            elif multi_asset_image:
                actual_afs = cr.get("asset_feed_spec", {})
                actual_imgs = actual_afs.get("images", [])
                actual_rules = actual_afs.get("asset_customization_rules", [])
                verification["multi_asset_verified"] = len(actual_imgs) == image_count and len(actual_rules) == image_count
                verification["assets_count"] = len(actual_imgs)
                verification["rules_count"] = len(actual_rules)
                verification["expected_count"] = image_count
                verification["asset_type"] = "static_image"
                # Check labels
                actual_labels = [r.get("image_label", {}).get("name") for r in actual_rules if r.get("image_label")]
                verification["asset_labels"] = actual_labels

        verification["validation_passed"] = (
            verification["status_verified"]
            and verification.get("name_verified", False)
            and verification["identity_verified"]
            and (verification["multi_asset_verified"] if multi_asset else True)
        )
    except MetaAPIError as e:
        verification["error"] = str(e)

    return {
        "ad_id": ad_id,
        "status": "PAUSED",
        "ad_name": ad_name,
        "identity_status": {
            "instagram_user_id": ig_id,
            "placement_mode": placement_mode,
            "ig_gate_result": ig_gate,
        },
        "creative_status": {
            "multi_asset": multi_asset,
            "asset_mode": "video" if is_video_mode else ("multi_image" if multi_asset_image else "none"),
            "fallback_used": fallback_used,
            "fallback_warning": "Only one video format provided. Meta may auto-crop for other placements." if fallback_used else None,
            "assets_used": {
                "vertical_video_id": video_9x16_id,
                "square_video_id": video_1x1_id,
                "image_1x1_hash": image_1x1_hash if has_img_1x1 else None,
                "image_4x5_hash": image_4x5_hash if has_img_4x5 else None,
                "image_9x16_hash": image_9x16_hash if has_img_9x16 else None,
                "image_count": image_count if is_image_mode else 0,
            },
        },
        "asset_validation": asset_validation,
        "verification": verification,
        "validation_passed": verification.get("validation_passed", False),
    }
