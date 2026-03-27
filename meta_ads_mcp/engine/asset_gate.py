"""
Asset Validation Gate.

Deterministic gate that validates video/image assets before ad creation.
Ensures correct aspect ratios, variant families, placement coverage,
and concept consistency.

## Rules
- Same concept with 9:16 + 1:1 = ONE ad (multi-asset, placement mapping)
- Different concepts = separate ads (never grouped)
- Full placement intent requires 9:16 + 1:1
- Wrong dimensions = BLOCK
- Wrong family grouping = BLOCK
"""
import logging
import os
import re
import struct
from typing import Any, Optional

logger = logging.getLogger("meta-ads-mcp.asset_gate")

# ── Aspect ratio classification ─────────────────────────────
RATIO_LABELS = {
    (9, 16): "9:16",
    (16, 9): "16:9",
    (1, 1): "1:1",
    (4, 5): "4:5",
    (5, 4): "5:4",
}

# Tolerance for ratio matching (e.g., 1080x1920 = 9:16 within tolerance)
RATIO_TOLERANCE = 0.05

# ── Placement fitness ───────────────────────────────────────
VARIANT_PLACEMENT_FIT = {
    "9:16": {
        "placements": ["reels", "stories", "stream"],
        "fit": "reels_stories",
        "orientation": "portrait",
    },
    "1:1": {
        "placements": ["feed", "marketplace", "search", "explore"],
        "fit": "feed",
        "orientation": "square",
    },
    "4:5": {
        "placements": ["feed"],
        "fit": "feed",
        "orientation": "portrait",
    },
    "16:9": {
        "placements": ["video_feeds", "in_stream"],
        "fit": "landscape",
        "orientation": "landscape",
    },
}

# ── Delivery modes ──────────────────────────────────────────
DELIVERY_MODES = {
    "full_placement": {
        "required_variants": ["9:16", "1:1"],
        "description": "Full placement coverage: Stories/Reels + Feed",
    },
    "reels_only": {
        "required_variants": ["9:16"],
        "description": "Reels/Stories only",
    },
    "feed_only": {
        "required_variants": ["1:1"],
        "description": "Feed only (square or 4:5)",
    },
    "single_asset": {
        "required_variants": [],
        "description": "Single asset, Meta handles placement",
    },
}


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def classify_dimensions(width: int, height: int) -> dict:
    """
    Classify asset dimensions into variant label and placement fit.

    Args:
        width: Asset width in pixels.
        height: Asset height in pixels.

    Returns:
        {width, height, aspect_ratio, variant_label, orientation, placement_fit}
    """
    if width <= 0 or height <= 0:
        return {
            "width": width, "height": height,
            "aspect_ratio": "invalid", "variant_label": "unknown",
            "orientation": "unknown", "placement_fit": "invalid",
        }

    # Compute ratio
    g = _gcd(width, height)
    ratio_w = width // g
    ratio_h = height // g

    # Match against known ratios
    ratio_float = width / height
    variant_label = "unknown"

    for (rw, rh), label in RATIO_LABELS.items():
        target = rw / rh
        if abs(ratio_float - target) < RATIO_TOLERANCE:
            variant_label = label
            break

    # If no exact match, classify by range
    if variant_label == "unknown":
        if ratio_float < 0.65:
            variant_label = "9:16"  # Close to portrait
        elif 0.65 <= ratio_float < 0.85:
            variant_label = "4:5"
        elif 0.85 <= ratio_float < 1.15:
            variant_label = "1:1"
        elif ratio_float >= 1.5:
            variant_label = "16:9"

    # Orientation
    if width > height * 1.1:
        orientation = "landscape"
    elif height > width * 1.1:
        orientation = "portrait"
    else:
        orientation = "square"

    # Placement fit
    fit_info = VARIANT_PLACEMENT_FIT.get(variant_label, {})
    placement_fit = fit_info.get("fit", "unknown")

    return {
        "width": width,
        "height": height,
        "aspect_ratio": f"{ratio_w}:{ratio_h}",
        "variant_label": variant_label,
        "orientation": orientation,
        "placement_fit": placement_fit,
    }


def inspect_asset_file(file_path: str) -> dict:
    """
    Inspect a local file to extract real dimensions.

    Supports: MP4/MOV (video), PNG, JPEG.
    Falls back to filename hints if file unreadable.
    """
    result = {
        "file_path": file_path,
        "file_exists": False,
        "asset_type": "unknown",
        "width": 0,
        "height": 0,
        "file_size_mb": 0,
        "inspection_method": "none",
    }

    if not file_path or not os.path.exists(file_path):
        result["error"] = f"File not found: {file_path}"
        # Try filename hints - but mark as UNVERIFIED
        dims = _dims_from_filename(file_path or "")
        if dims:
            result.update(dims)
            result["inspection_method"] = "filename_hint"
            result["dimension_confidence"] = "unverified"
            result["dimension_warning"] = "Dimensions from filename only - file not inspected"
        return result

    result["file_exists"] = True
    result["file_size_mb"] = round(os.path.getsize(file_path) / (1024 * 1024), 2)

    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".mp4", ".mov", ".m4v"):
        result["asset_type"] = "video"
        dims = _read_mp4_dimensions(file_path)
        if dims:
            result.update(dims)
            result["inspection_method"] = "mp4_moov"
    elif ext in (".png",):
        result["asset_type"] = "image"
        dims = _read_png_dimensions(file_path)
        if dims:
            result.update(dims)
            result["inspection_method"] = "png_header"
    elif ext in (".jpg", ".jpeg"):
        result["asset_type"] = "image"
        dims = _read_jpeg_dimensions(file_path)
        if dims:
            result.update(dims)
            result["inspection_method"] = "jpeg_header"

    # Fallback to filename hints - mark as UNVERIFIED
    if result["width"] == 0:
        dims = _dims_from_filename(file_path)
        if dims:
            result.update(dims)
            result["inspection_method"] = "filename_hint"
            result["dimension_confidence"] = "unverified"
            result["dimension_warning"] = (
                f"Header inspection failed for {os.path.basename(file_path)}. "
                "Dimensions from filename only - may be inaccurate."
            )
            logger.warning(f"Asset dimensions from filename hint only: {file_path}")
        else:
            result["dimension_confidence"] = "unknown"
            result["dimension_warning"] = f"Cannot determine dimensions for {os.path.basename(file_path)}"
    else:
        result["dimension_confidence"] = "verified"

    # Classify
    if result["width"] > 0:
        classification = classify_dimensions(result["width"], result["height"])
        result.update(classification)

    return result


def _dims_from_filename(filename: str) -> Optional[dict]:
    """Extract dimension hints from filename patterns like 1080x1920 or 9x16."""
    # Look for WxH pattern
    m = re.search(r'(\d{3,4})\s*[xX]\s*(\d{3,4})', filename)
    if m:
        return {"width": int(m.group(1)), "height": int(m.group(2))}
    # Look for ratio hint
    if "9x16" in filename or "9-16" in filename or "916" in filename:
        return {"width": 1080, "height": 1920}
    if "1x1" in filename or "1-1" in filename:
        return {"width": 1080, "height": 1080}
    if "4x5" in filename or "4-5" in filename:
        return {"width": 1080, "height": 1350}
    return None


def _read_png_dimensions(path: str) -> Optional[dict]:
    try:
        with open(path, 'rb') as f:
            sig = f.read(8)
            if sig[:4] != b'\x89PNG':
                return None
            f.read(4)  # chunk length
            chunk_type = f.read(4)
            if chunk_type != b'IHDR':
                return None
            w = struct.unpack('>I', f.read(4))[0]
            h = struct.unpack('>I', f.read(4))[0]
            return {"width": w, "height": h}
    except Exception:
        return None


def _read_jpeg_dimensions(path: str) -> Optional[dict]:
    try:
        with open(path, 'rb') as f:
            if f.read(2) != b'\xff\xd8':
                return None
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    return None
                if marker[0] != 0xFF:
                    return None
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)  # length + precision
                    h = struct.unpack('>H', f.read(2))[0]
                    w = struct.unpack('>H', f.read(2))[0]
                    return {"width": w, "height": h}
                length = struct.unpack('>H', f.read(2))[0]
                f.seek(length - 2, 1)
    except Exception:
        return None


def _read_mp4_dimensions(path: str) -> Optional[dict]:
    """Read dimensions from MP4/MOV moov/trak/tkhd atom."""
    try:
        with open(path, 'rb') as f:
            data = f.read(min(os.path.getsize(path), 10 * 1024 * 1024))  # Max 10MB scan

        # Find tkhd atom (track header)
        pos = data.find(b'tkhd')
        if pos < 4:
            return None

        # tkhd has width/height at fixed offsets from start
        # Version 0: offset 76-84 from atom start
        # Version 1: offset 88-96 from atom start
        atom_start = pos - 4  # Account for size field
        version = data[pos + 4] if pos + 4 < len(data) else 0

        if version == 0:
            wh_offset = atom_start + 4 + 4 + 72  # size + type + 72 bytes
        else:
            wh_offset = atom_start + 4 + 4 + 84

        if wh_offset + 8 > len(data):
            return None

        # Width and height are fixed-point 16.16
        w_fixed = struct.unpack('>I', data[wh_offset:wh_offset+4])[0]
        h_fixed = struct.unpack('>I', data[wh_offset+4:wh_offset+8])[0]
        w = w_fixed >> 16
        h = h_fixed >> 16

        if w > 0 and h > 0:
            return {"width": w, "height": h}
    except (OSError, struct.error, ValueError, IndexError) as e:
        logger.debug(f"MP4 dimension read failed for {path}: {e}")
        return None
    return None


def classify_asset_variant(
    meta_video_id: Optional[str] = None,
    file_path: Optional[str] = None,
    width: int = 0,
    height: int = 0,
    logical_creative_id: str = "",
    label_hint: str = "",
) -> dict:
    """
    Classify a single asset into variant label and placement fit.

    Uses file inspection if path available, falls back to dimensions,
    then to label hints.
    """
    # Priority 1: Real file inspection
    if file_path:
        info = inspect_asset_file(file_path)
        if info.get("width", 0) > 0:
            return {
                "meta_video_id": meta_video_id,
                "logical_creative_id": logical_creative_id,
                "source": "file_inspection",
                **info,
            }

    # Priority 2: Explicit dimensions
    if width > 0 and height > 0:
        classification = classify_dimensions(width, height)
        return {
            "meta_video_id": meta_video_id,
            "logical_creative_id": logical_creative_id,
            "source": "explicit_dimensions",
            **classification,
        }

    # Priority 3: Label hints from logical_creative_id or label_hint
    hint = label_hint or logical_creative_id or ""
    hint_lower = hint.lower().replace(":", "x")  # Normalize 9:16 -> 9x16
    if "9x16" in hint_lower or "9-16" in hint_lower or "916" in hint_lower or "vertical" in hint_lower:
        return {"meta_video_id": meta_video_id, "logical_creative_id": logical_creative_id,
                "source": "label_hint", "variant_label": "9:16", "orientation": "portrait",
                "placement_fit": "reels_stories", "width": 0, "height": 0}
    if "1x1" in hint_lower or "1-1" in hint_lower or "square" in hint_lower:
        return {"meta_video_id": meta_video_id, "logical_creative_id": logical_creative_id,
                "source": "label_hint", "variant_label": "1:1", "orientation": "square",
                "placement_fit": "feed", "width": 0, "height": 0}
    if "4x5" in hint_lower or "4-5" in hint_lower:
        return {"meta_video_id": meta_video_id, "logical_creative_id": logical_creative_id,
                "source": "label_hint", "variant_label": "4:5", "orientation": "portrait",
                "placement_fit": "feed", "width": 0, "height": 0}

    return {
        "meta_video_id": meta_video_id,
        "logical_creative_id": logical_creative_id,
        "source": "unknown",
        "variant_label": "unknown",
        "orientation": "unknown",
        "placement_fit": "unknown",
        "width": 0, "height": 0,
    }


def group_into_variant_families(assets: list[dict]) -> dict:
    """
    Group assets by concept into variant families.

    Each family = one logical concept that may have multiple format variants
    (e.g., 9:16 + 1:1 of the same hook).

    Assets are grouped by `concept_key` which is derived from:
    - logical_creative_id (without format suffix)
    - hook name
    - explicit family_id

    Returns:
        {families: {key: [assets]}, ungrouped: [assets], issues: []}
    """
    families = {}
    ungrouped = []
    issues = []

    for asset in assets:
        # Determine concept key
        lcid = asset.get("logical_creative_id", "")
        hook = asset.get("hook", "")
        family_id = asset.get("family_id", "")

        # Strip format suffixes from logical_creative_id to find the concept
        concept_key = family_id
        if not concept_key:
            # Remove common format suffixes
            clean = re.sub(r'[-_](9x16|1x1|4x5|16x9|vertical|square|feed|reel)$', '', lcid, flags=re.I)
            concept_key = clean or hook or lcid

        if not concept_key:
            ungrouped.append(asset)
            issues.append(f"Asset has no concept key: {asset}")
            continue

        concept_key = concept_key.lower().strip()
        if concept_key not in families:
            families[concept_key] = []
        families[concept_key].append(asset)

    return {"families": families, "ungrouped": ungrouped, "issues": issues}


def validate_variant_family(
    family_assets: list[dict],
    delivery_mode: str = "full_placement",
) -> dict:
    """
    Validate a variant family for placement coverage and consistency.

    Args:
        family_assets: List of classified assets in the same concept family.
        delivery_mode: 'full_placement', 'reels_only', 'feed_only', 'single_asset'.

    Returns:
        {family_valid, delivery_mode, detected_variants, missing_variants,
         placement_coverage, recommended_ad_mode, issues, fix_suggestions}
    """
    mode_spec = DELIVERY_MODES.get(delivery_mode, DELIVERY_MODES["single_asset"])
    required = set(mode_spec["required_variants"])

    detected = {}
    for asset in family_assets:
        vl = asset.get("variant_label", "unknown")
        if vl not in detected:
            detected[vl] = []
        detected[vl].append(asset)

    detected_labels = set(detected.keys()) - {"unknown"}
    missing = required - detected_labels

    issues = []
    fix_suggestions = []

    # Check: required variants present
    if missing:
        issues.append(
            f"Missing required variant(s) for {delivery_mode}: {sorted(missing)}. "
            f"Have: {sorted(detected_labels)}"
        )
        for m in missing:
            fix_suggestions.append(f"Add a {m} variant of this concept")

    # Check: no unknown variants in strict modes
    if "unknown" in detected and delivery_mode != "single_asset":
        issues.append(
            f"Asset with unknown variant label in family. "
            f"Cannot determine placement fit."
        )
        fix_suggestions.append("Provide width/height or label hint for all assets")

    # Check: no duplicate variants (same label twice = probably wrong grouping)
    for label, assets_in_label in detected.items():
        if len(assets_in_label) > 1 and label != "unknown":
            # Check if they're actually different files
            ids = [a.get("meta_video_id", a.get("file_path", "?")) for a in assets_in_label]
            if len(set(ids)) > 1:
                issues.append(
                    f"Multiple {label} assets in same family: {ids}. "
                    f"This may indicate wrong grouping (different concepts mixed)."
                )

    # Determine recommended ad mode
    if "9:16" in detected_labels and "1:1" in detected_labels:
        recommended = "multi_asset"
        placement_coverage = "full"
    elif "9:16" in detected_labels:
        recommended = "single_vertical"
        placement_coverage = "reels_stories_only"
    elif "1:1" in detected_labels:
        recommended = "single_square"
        placement_coverage = "feed_only"
    else:
        recommended = "single_asset"
        placement_coverage = "unknown"

    # Build placement mapping
    placement_mapping = {}
    if "9:16" in detected:
        a = detected["9:16"][0]
        placement_mapping["9:16"] = {
            "asset_id": a.get("meta_video_id", ""),
            "placements": ["stories", "reels", "stream"],
        }
    if "1:1" in detected:
        a = detected["1:1"][0]
        placement_mapping["1:1"] = {
            "asset_id": a.get("meta_video_id", ""),
            "placements": ["feed", "marketplace", "search", "explore"],
        }

    family_valid = len(issues) == 0

    return {
        "family_valid": family_valid,
        "delivery_mode": delivery_mode,
        "detected_variants": {k: len(v) for k, v in detected.items()},
        "detected_labels": sorted(detected_labels),
        "missing_variants": sorted(missing),
        "placement_coverage": placement_coverage,
        "recommended_ad_mode": recommended,
        "placement_mapping": placement_mapping,
        "issues": issues,
        "fix_suggestions": fix_suggestions,
    }


def enforce_asset_gate(
    assets: list[dict],
    delivery_mode: str = "full_placement",
    expected_families: Optional[int] = None,
) -> dict:
    """
    Full asset validation gate. Called before ad creation.

    Args:
        assets: List of asset dicts, each with at least:
            logical_creative_id, and one of:
            - meta_video_id + (width, height) or label hint
            - file_path for local inspection
        delivery_mode: Expected delivery mode.
        expected_families: If set, validates family count matches.

    Returns:
        {asset_gate_status, families, family_validations,
         concept_consistency_verified, critical_block, issues, fix_suggestions}
    """
    if not assets:
        return {
            "asset_gate_status": "blocked",
            "critical_block": True,
            "issues": ["No assets provided"],
            "fix_suggestions": ["Provide at least one asset with logical_creative_id"],
            "families": {},
            "family_validations": {},
        }

    # Classify all assets
    classified = []
    classification_issues = []
    for asset in assets:
        c = classify_asset_variant(
            meta_video_id=asset.get("meta_video_id"),
            file_path=asset.get("file_path"),
            width=asset.get("width", 0),
            height=asset.get("height", 0),
            logical_creative_id=asset.get("logical_creative_id", ""),
            label_hint=asset.get("label_hint", asset.get("variant_label", "")),
        )
        # Carry through original fields
        c["hook"] = asset.get("hook", "")
        c["family_id"] = asset.get("family_id", "")
        classified.append(c)

        if c.get("variant_label") == "unknown" and c.get("source") == "unknown":
            classification_issues.append(
                f"Cannot classify asset '{asset.get('logical_creative_id', '?')}': "
                f"no dimensions, file, or label hint"
            )

    # Group into families
    grouping = group_into_variant_families(classified)
    families = grouping["families"]

    # Validate each family
    family_validations = {}
    all_issues = list(classification_issues) + grouping["issues"]
    all_fix = []

    for family_key, family_assets in families.items():
        fv = validate_variant_family(family_assets, delivery_mode)
        family_validations[family_key] = fv
        if not fv["family_valid"]:
            all_issues.extend(fv["issues"])
            all_fix.extend(fv["fix_suggestions"])

    # Check expected family count
    if expected_families is not None and len(families) != expected_families:
        all_issues.append(
            f"Expected {expected_families} concept families, found {len(families)}: "
            f"{sorted(families.keys())}"
        )

    # Concept consistency: no mixed concepts in any family
    concept_consistent = all(
        fv.get("family_valid", False) or not fv.get("issues")
        for fv in family_validations.values()
    )

    # Check for unverified dimensions in any classified asset
    unverified_assets = [c for c in classified if c.get("dimension_confidence") == "unverified"]
    if unverified_assets:
        for ua in unverified_assets:
            all_issues.append(
                f"Asset '{ua.get('logical_creative_id', '?')}' has UNVERIFIED dimensions "
                f"(filename hint only). Use explicit width/height or provide inspectable file."
            )

    critical_block = len(all_issues) > 0

    return {
        "asset_gate_status": "passed" if not critical_block else "blocked",
        "critical_block": critical_block,
        "dimension_confidence": "verified" if not unverified_assets else "unverified",
        "total_assets": len(assets),
        "total_families": len(families),
        "family_keys": sorted(families.keys()),
        "families": {k: [a.get("logical_creative_id", "?") for a in v] for k, v in families.items()},
        "family_validations": family_validations,
        "concept_consistency_verified": concept_consistent,
        "issues": all_issues,
        "fix_suggestions": all_fix,
    }
