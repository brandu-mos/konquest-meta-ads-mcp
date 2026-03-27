"""
Naming Enforcement Gate.

Hard gate that validates or generates names for all Meta Ads objects
before any write reaches the API. No arbitrary names allowed.

## Name Source Hierarchy (priority order)
1. Account-specific naming rules (vault / account intelligence)
2. Learned pattern from real objects in the account
3. Canonical naming schema (fallback)

## Canonical Schema (learned from client accounts)
- Campaign: Objective | Product | Funnel | BudgetModel
- Ad Set:   AudienceType | AgeRange | Geo | ExclusionFlag
- Ad:       Hook | Format | Version

## Separator: ' | ' (space pipe space)
"""
import logging
import re
from typing import Optional

logger = logging.getLogger("meta-ads-mcp.naming_gate")

SEP = " | "

# ── Canonical segments ──────────────────────────────────────
CAMPAIGN_SEGMENTS = ["objective", "product", "funnel", "budget_model"]
ADSET_SEGMENTS = ["audience_type", "age_range", "geo", "exclusion_flag"]
AD_SEGMENTS = ["hook", "format", "version"]

SEGMENT_DEFS = {
    "campaign": {
        "segments": CAMPAIGN_SEGMENTS,
        "required": {"objective", "product", "funnel", "budget_model"},
        "pattern": "Objective | Product | Funnel | BudgetModel",
    },
    "adset": {
        "segments": ADSET_SEGMENTS,
        "required": {"audience_type", "age_range", "geo"},
        "pattern": "AudienceType | AgeRange | Geo | ExclusionFlag",
    },
    "ad": {
        "segments": AD_SEGMENTS,
        "required": {"hook", "format", "version"},
        "pattern": "Hook | Format | Version",
    },
}

# ── Valid token sets ────────────────────────────────────────
VALID_OBJECTIVES = {"Sales", "Traffic", "Leads", "Awareness", "Engagement"}
VALID_FUNNELS = {"TOFU", "MOFU", "BOFU", "RT"}
VALID_BUDGET_MODELS = {"ABO", "CBO"}
VALID_FORMATS = {"REEL", "VID", "IMG", "REEL+FEED", "CAROUSEL"}
VALID_GEOS = {
    "GR", "CY", "US", "UK", "DE", "FR", "NL", "NO", "SE", "DK", "FI",
    "IT", "ES", "AT", "CH", "BE", "AU", "CA", "CR",
}

# ── Objective mapping from Meta API values ──────────────────
OBJECTIVE_MAP = {
    "OUTCOME_SALES": "Sales",
    "OUTCOME_LEADS": "Leads",
    "OUTCOME_TRAFFIC": "Traffic",
    "OUTCOME_AWARENESS": "Awareness",
    "OUTCOME_ENGAGEMENT": "Engagement",
    "OUTCOME_APP_PROMOTION": "App",
}

FUNNEL_MAP = {
    "tofu": "TOFU", "mofu": "MOFU", "bofu": "BOFU",
    "prospecting": "TOFU", "consideration": "MOFU", "retarget": "RT",
    "cold": "TOFU", "warm": "MOFU", "hot": "BOFU",
}


def _detect_separator(name: str) -> str:
    """Detect the separator used in a name."""
    if " | " in name:
        return " | "
    if " - " in name:
        return " - "
    if " / " in name:
        return " / "
    if "|" in name:
        return "|"
    return " | "


def _split_name(name: str) -> list[str]:
    """Split a name into segments using detected separator."""
    sep = _detect_separator(name)
    return [s.strip() for s in name.split(sep)]


def learn_naming_pattern(names: list[str], object_type: str) -> dict:
    """
    Learn naming pattern from a list of real names.

    Args:
        names: List of real object names from the account.
        object_type: 'campaign', 'adset', 'ad'.

    Returns:
        {separator, num_segments, segment_labels, confidence,
         token_examples, pattern_string}
    """
    if not names:
        return {
            "learned": False,
            "confidence": "none",
            "reason": "No names provided",
        }

    # Detect separator consistency
    separators = [_detect_separator(n) for n in names]
    sep_counts = {}
    for s in separators:
        sep_counts[s] = sep_counts.get(s, 0) + 1
    dominant_sep = max(sep_counts, key=sep_counts.get)
    sep_consistency = sep_counts[dominant_sep] / len(names)

    # Split all names
    splits = [_split_name(n) for n in names]
    segment_counts = [len(s) for s in splits]

    if not segment_counts:
        return {"learned": False, "confidence": "none", "reason": "Could not split names"}

    # Find dominant segment count
    count_freq = {}
    for c in segment_counts:
        count_freq[c] = count_freq.get(c, 0) + 1
    dominant_count = max(count_freq, key=count_freq.get)
    count_consistency = count_freq[dominant_count] / len(names)

    # Collect token examples per position
    token_examples = {}
    for split in splits:
        if len(split) == dominant_count:
            for i, token in enumerate(split):
                if i not in token_examples:
                    token_examples[i] = []
                clean = token.strip().rstrip("[OLD]").strip()
                if clean and clean not in token_examples[i]:
                    token_examples[i].append(clean)

    # Try to label positions using canonical schema
    canonical = SEGMENT_DEFS.get(object_type, {})
    canonical_segments = canonical.get("segments", [])
    segment_labels = {}

    for pos, examples in token_examples.items():
        if pos < len(canonical_segments):
            segment_labels[pos] = canonical_segments[pos]
        else:
            segment_labels[pos] = f"segment_{pos}"

        # Validate examples against known token sets
        if segment_labels[pos] == "objective":
            if any(e in VALID_OBJECTIVES for e in examples):
                segment_labels[pos] = "objective"
        elif segment_labels[pos] == "budget_model":
            if any(e in VALID_BUDGET_MODELS for e in examples):
                segment_labels[pos] = "budget_model"

    confidence = "high" if (sep_consistency > 0.8 and count_consistency > 0.7) else \
                 "medium" if (sep_consistency > 0.5 and count_consistency > 0.5) else "low"

    return {
        "learned": True,
        "separator": dominant_sep,
        "num_segments": dominant_count,
        "segment_labels": segment_labels,
        "segment_examples": {pos: exs[:5] for pos, exs in token_examples.items()},
        "confidence": confidence,
        "consistency": {
            "separator": round(sep_consistency, 2),
            "segment_count": round(count_consistency, 2),
        },
        "pattern_string": dominant_sep.join(
            segment_labels.get(i, f"?") for i in range(dominant_count)
        ),
        "sample_names": names[:5],
        "total_names_analyzed": len(names),
    }


def build_name(
    object_type: str,
    inputs: dict,
    learned_pattern: Optional[dict] = None,
) -> dict:
    """
    Build a name from inputs, using learned pattern or canonical fallback.

    Args:
        object_type: 'campaign', 'adset', 'ad'.
        inputs: Dict with segment values (objective, product, funnel, etc.)
        learned_pattern: From learn_naming_pattern(). Uses canonical if None.

    Returns:
        {name, valid, pattern_source, parsed_segments, missing, errors}
    """
    canonical = SEGMENT_DEFS.get(object_type)
    if not canonical:
        return {"name": None, "valid": False, "errors": [f"Unknown object_type: {object_type}"]}

    segments = canonical["segments"]
    required = canonical["required"]
    sep = SEP

    if learned_pattern and learned_pattern.get("learned"):
        sep = learned_pattern.get("separator", SEP)

    # Normalize inputs
    normalized = {}
    for seg in segments:
        val = inputs.get(seg, "")

        # Auto-map common values
        if seg == "objective" and val in OBJECTIVE_MAP:
            val = OBJECTIVE_MAP[val]
        elif seg == "funnel" and val.lower() in FUNNEL_MAP:
            val = FUNNEL_MAP[val.lower()]
        elif seg == "budget_model" and val:
            val = val.upper()
        elif seg == "format" and val:
            val = val.upper()
        elif seg == "version" and val and not val.startswith("V"):
            val = f"V{val}"
        elif seg == "geo" and val:
            val = val.upper()
        elif seg == "exclusion_flag" and not val:
            val = "None"

        normalized[seg] = val.strip() if val else ""

    # Check required segments
    missing = [s for s in required if not normalized.get(s)]
    if missing:
        return {
            "name": None,
            "valid": False,
            "pattern_source": "canonical" if not learned_pattern else "learned",
            "parsed_segments": normalized,
            "missing_required_segments": missing,
            "errors": [f"Missing required segment(s): {missing}"],
        }

    # Validate known tokens
    warnings = []
    if object_type == "campaign":
        if normalized["objective"] not in VALID_OBJECTIVES:
            warnings.append(f"Non-standard objective: '{normalized['objective']}'")
        if normalized["funnel"] not in VALID_FUNNELS:
            warnings.append(f"Non-standard funnel: '{normalized['funnel']}'")
        if normalized["budget_model"] not in VALID_BUDGET_MODELS:
            warnings.append(f"Non-standard budget_model: '{normalized['budget_model']}'")
    elif object_type == "ad":
        if normalized["format"] not in VALID_FORMATS:
            warnings.append(f"Non-standard format: '{normalized['format']}'")
        if not normalized["version"].startswith("V"):
            warnings.append(f"Version should start with V: '{normalized['version']}'")

    # Build name
    parts = [normalized[s] for s in segments]
    name = sep.join(parts)

    return {
        "name": name,
        "valid": True,
        "pattern_source": "learned" if learned_pattern and learned_pattern.get("learned") else "canonical",
        "pattern_string": canonical["pattern"],
        "parsed_segments": normalized,
        "missing_required_segments": [],
        "warnings": warnings,
        "errors": [],
    }


def validate_name(
    name: str,
    object_type: str,
    learned_pattern: Optional[dict] = None,
) -> dict:
    """
    Validate a proposed name against the expected pattern.

    Returns:
        {valid, parsed_segments, issues, pattern_matched}
    """
    if not name or not name.strip():
        return {
            "valid": False,
            "issues": ["Name is empty"],
            "parsed_segments": {},
            "pattern_matched": False,
        }

    canonical = SEGMENT_DEFS.get(object_type)
    if not canonical:
        return {"valid": False, "issues": [f"Unknown object_type: {object_type}"]}

    segments = canonical["segments"]
    required = canonical["required"]
    expected_count = len(segments)

    parts = _split_name(name)
    issues = []

    # Check segment count
    if len(parts) < expected_count:
        issues.append(
            f"Expected {expected_count} segments ({canonical['pattern']}), "
            f"got {len(parts)}: {parts}"
        )

    # Parse into labeled segments
    parsed = {}
    for i, seg_name in enumerate(segments):
        if i < len(parts):
            parsed[seg_name] = parts[i]
        else:
            parsed[seg_name] = ""

    # Check required segments not empty
    for seg in required:
        if not parsed.get(seg):
            issues.append(f"Required segment '{seg}' is empty")

    # Token validation
    if object_type == "campaign":
        if parsed.get("objective") and parsed["objective"] not in VALID_OBJECTIVES:
            issues.append(f"Invalid objective: '{parsed['objective']}'. Valid: {sorted(VALID_OBJECTIVES)}")
        if parsed.get("funnel") and parsed["funnel"] not in VALID_FUNNELS:
            issues.append(f"Invalid funnel: '{parsed['funnel']}'. Valid: {sorted(VALID_FUNNELS)}")
        if parsed.get("budget_model") and parsed["budget_model"] not in VALID_BUDGET_MODELS:
            issues.append(f"Invalid budget_model: '{parsed['budget_model']}'. Valid: {sorted(VALID_BUDGET_MODELS)}")
    elif object_type == "ad":
        if parsed.get("format") and parsed["format"] not in VALID_FORMATS:
            issues.append(f"Non-standard format: '{parsed['format']}'. Valid: {sorted(VALID_FORMATS)}")
        if parsed.get("version") and not parsed["version"].startswith("V"):
            issues.append(f"Version must start with V: '{parsed['version']}'")

    # Check against learned pattern if available
    pattern_matched = False
    if learned_pattern and learned_pattern.get("learned"):
        learned_count = learned_pattern["num_segments"]
        if len(parts) == learned_count:
            pattern_matched = True
        else:
            issues.append(
                f"Learned pattern expects {learned_count} segments, "
                f"proposed name has {len(parts)}"
            )

    return {
        "valid": len(issues) == 0,
        "parsed_segments": parsed,
        "issues": issues,
        "pattern_matched": pattern_matched or len(issues) == 0,
        "name_analyzed": name,
        "segments_found": len(parts),
        "segments_expected": expected_count,
    }


def enforce_naming(
    proposed_name: Optional[str],
    object_type: str,
    naming_inputs: Optional[dict] = None,
    learned_pattern: Optional[dict] = None,
) -> dict:
    """
    Hard naming enforcement gate. Called before every write.

    Logic:
    A. If proposed_name exists and valid -> PASS
    B. If proposed_name invalid but inputs available -> auto-generate correct name
    C. If no proposed_name but inputs available -> auto-generate
    D. If no name and insufficient inputs -> BLOCK

    Args:
        proposed_name: The name to validate (can be None for auto-generation).
        object_type: 'campaign', 'adset', 'ad'.
        naming_inputs: Dict with segment values for generation.
        learned_pattern: From learn_naming_pattern().

    Returns:
        {naming_status, final_name, validation_passed, critical_block,
         pattern_source, parsed_segments, fix_suggestion, ...}
    """
    result = {
        "naming_status": "unknown",
        "final_name": None,
        "validation_passed": False,
        "critical_block": False,
        "pattern_source": "canonical",
        "pattern_confidence": "high",
        "matched_pattern": SEGMENT_DEFS.get(object_type, {}).get("pattern", "?"),
        "parsed_segments": {},
        "missing_required_segments": [],
        "generated_name": None,
        "fix_suggestion": None,
    }

    if learned_pattern and learned_pattern.get("learned"):
        result["pattern_source"] = "learned"
        result["pattern_confidence"] = learned_pattern.get("confidence", "medium")

    canonical = SEGMENT_DEFS.get(object_type)
    if not canonical:
        result["naming_status"] = "invalid_object_type"
        result["critical_block"] = True
        result["fix_suggestion"] = f"object_type must be 'campaign', 'adset', or 'ad'"
        return result

    # Case A: Proposed name exists - validate it
    if proposed_name and proposed_name.strip():
        val = validate_name(proposed_name, object_type, learned_pattern)

        if val["valid"]:
            result["naming_status"] = "valid"
            result["final_name"] = proposed_name
            result["validation_passed"] = True
            result["parsed_segments"] = val["parsed_segments"]
            return result

        # Name invalid - try auto-generation if inputs available
        if naming_inputs:
            gen = build_name(object_type, naming_inputs, learned_pattern)
            if gen["valid"]:
                result["naming_status"] = "auto_corrected"
                result["final_name"] = gen["name"]
                result["generated_name"] = gen["name"]
                result["validation_passed"] = True
                result["parsed_segments"] = gen["parsed_segments"]
                result["fix_suggestion"] = (
                    f"Proposed name '{proposed_name}' is invalid: {val['issues']}. "
                    f"Auto-generated: '{gen['name']}'"
                )
                return result

        # Name invalid and no inputs to auto-generate
        result["naming_status"] = "invalid"
        result["critical_block"] = True
        result["parsed_segments"] = val.get("parsed_segments", {})
        result["fix_suggestion"] = (
            f"Name '{proposed_name}' is invalid: {val['issues']}. "
            f"Expected pattern: {canonical['pattern']}. "
            f"Provide naming_inputs or fix the name."
        )
        return result

    # Case C: No proposed name - try auto-generation
    if naming_inputs:
        gen = build_name(object_type, naming_inputs, learned_pattern)
        if gen["valid"]:
            result["naming_status"] = "auto_generated"
            result["final_name"] = gen["name"]
            result["generated_name"] = gen["name"]
            result["validation_passed"] = True
            result["parsed_segments"] = gen["parsed_segments"]
            return result

        # Generation failed - missing inputs
        result["naming_status"] = "insufficient_inputs"
        result["critical_block"] = True
        result["missing_required_segments"] = gen.get("missing_required_segments", [])
        result["fix_suggestion"] = (
            f"Cannot generate name. Missing: {gen.get('missing_required_segments', [])}. "
            f"Pattern: {canonical['pattern']}"
        )
        return result

    # Case D: No name, no inputs
    result["naming_status"] = "no_name_no_inputs"
    result["critical_block"] = True
    result["missing_required_segments"] = list(canonical["required"])
    result["fix_suggestion"] = (
        f"No name provided and no naming_inputs for auto-generation. "
        f"Required: {canonical['pattern']}"
    )
    return result
