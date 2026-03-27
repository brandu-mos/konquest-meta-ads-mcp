"""
Advantage+ Audience Strategy Layer.

Enforces Advantage+ audience as default for performance campaigns.
Maps ICP signals into flexible targeting suggestions (not strict constraints).

## Rules
- Advantage+ ON by default for all performance campaigns
- Detailed targeting = suggestions, not restrictions
- Age/geo constraints preserved, but not overly narrowed
- ICP signals from concept layer drive audience inputs
- Only disable Advantage+ for explicit strict_audience_test or audience_mode="restricted"

## Meta API mapping
- targeting_automation.advantage_audience = 1 -> Advantage+ ON (suggestions mode)
- targeting_automation.advantage_audience = 0 -> Advantage+ OFF (strict mode)
"""
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("meta-ads-mcp.engine.audience")

# Minimum audience size thresholds (estimated reach)
# Below these, targeting is considered overly narrow
NARROWING_THRESHOLDS = {
    "min_age_range": 10,          # age_max - age_min must be >= 10
    "max_interest_count": 15,     # too many interests = over-specification
    "max_exclusion_count": 5,     # too many exclusions = over-restriction
    "min_countries": 1,           # at least one country
}

# ICP-to-interest keyword mapping for common Greek market verticals
ICP_SIGNAL_MAP = {
    # Business/consulting
    "business owner": ["Business administration", "Entrepreneurship", "Small business"],
    "entrepreneur": ["Entrepreneurship", "Startup company", "Business"],
    "manager": ["Management", "Leadership", "Human resources"],
    "overwhelmed owner": ["Small business", "Entrepreneurship", "Business consulting"],
    "growth-stalled": ["Business growth", "Business consulting", "Marketing"],

    # Beauty/skincare
    "skincare": ["Skin care", "Beauty", "Cosmetics"],
    "hair care": ["Hair care", "Beauty salons", "Hairstyle"],
    "luxury buyer": ["Luxury goods", "Online shopping", "Premium brands"],
    "damaged hair": ["Hair care", "Beauty", "Salon"],

    # Real estate
    "property buyer": ["Real estate", "Property", "Investment"],
    "international buyer": ["Real estate", "Travel", "Relocation"],

    # HVAC/construction
    "contractor": ["Construction", "Building materials", "Architecture"],
    "homeowner": ["Home improvement", "Real estate", "Interior design"],

    # Fitness/personal development
    "self improvement": ["Personal development", "Self-help", "Motivation"],
    "personal development": ["Personal development", "Self-help", "Coaching"],
}


def build_audience_spec(
    targeting_input: Optional[dict] = None,
    audience_mode: str = "advantage_plus",
    icp_name: Optional[str] = None,
    icp_signals: Optional[dict] = None,
    geo_countries: Optional[list[str]] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    experiment_type: Optional[str] = None,
) -> dict:
    """
    Build a complete audience targeting spec with Advantage+ enforcement.

    Args:
        targeting_input: Raw targeting dict (if provided by caller).
        audience_mode: 'advantage_plus' (default), 'restricted' (explicit opt-out).
        icp_name: ICP name from concept selection (for signal derivation).
        icp_signals: Pre-built ICP signals dict with interests/behaviors/demographics.
        geo_countries: Country codes (default ['GR']).
        age_min: Minimum age (optional).
        age_max: Maximum age (optional).
        experiment_type: If 'strict_audience_test', allows Advantage+ OFF.

    Returns:
        Dict with:
            targeting: Final targeting spec for Meta API
            audience_strategy: Metadata about the audience approach
            warnings: Any issues detected
            blocked: True if targeting is invalid and should be blocked
    """
    warnings = []
    countries = geo_countries or ["GR"]

    # Determine if Advantage+ should be ON or OFF
    advantage_plus_on = True
    advantage_reason = "Default: Advantage+ enabled for performance optimization"

    if audience_mode == "restricted":
        advantage_plus_on = False
        advantage_reason = "User explicitly set audience_mode='restricted'"
    elif experiment_type == "strict_audience_test":
        advantage_plus_on = False
        advantage_reason = "Experiment type 'strict_audience_test' requires strict targeting"

    # Start building targeting spec
    targeting = targeting_input.copy() if targeting_input else {}

    # Ensure geo_locations
    if "geo_locations" not in targeting:
        targeting["geo_locations"] = {"countries": countries}

    # Set Advantage+ flag
    targeting["targeting_automation"] = {
        "advantage_audience": 1 if advantage_plus_on else 0
    }

    # If Advantage+ was OFF in input but should be ON, auto-correct
    if targeting_input and "targeting_automation" in targeting_input:
        input_aa = targeting_input["targeting_automation"].get("advantage_audience", 0)
        if input_aa == 0 and advantage_plus_on:
            warnings.append(
                "Auto-corrected: targeting_automation.advantage_audience was 0 (OFF). "
                "Set to 1 (ON) because Advantage+ is required for performance campaigns. "
                "To disable, set audience_mode='restricted' or experiment_type='strict_audience_test'."
            )

    # Map ICP signals into flexible targeting suggestions
    icp_derived_signals = {}
    if icp_name and advantage_plus_on:
        icp_derived_signals = _derive_icp_signals(icp_name)
        if icp_derived_signals.get("interests"):
            # Add as flexible_spec (suggestions, not constraints)
            if "flexible_spec" not in targeting:
                targeting["flexible_spec"] = []
            targeting["flexible_spec"].append({
                "interests": [{"name": i} for i in icp_derived_signals["interests"][:6]],
            })

    # Merge explicit ICP signals if provided
    if icp_signals and advantage_plus_on:
        if icp_signals.get("interests"):
            if "flexible_spec" not in targeting:
                targeting["flexible_spec"] = []
            targeting["flexible_spec"].append({
                "interests": [{"name": i} if isinstance(i, str) else i for i in icp_signals["interests"][:6]],
            })
        if icp_signals.get("behaviors"):
            if "flexible_spec" not in targeting:
                targeting["flexible_spec"] = []
            targeting["flexible_spec"].append({
                "behaviors": [{"name": b} if isinstance(b, str) else b for b in icp_signals["behaviors"][:4]],
            })

    # Apply age constraints (keep these even with Advantage+)
    if age_min is not None:
        targeting["age_min"] = age_min
    if age_max is not None:
        targeting["age_max"] = age_max

    # Narrowing detection
    narrowing_issues = _detect_narrowing(targeting)
    if narrowing_issues:
        for issue in narrowing_issues:
            warnings.append(f"Narrowing detected: {issue}")

    # Determine strategy label
    if advantage_plus_on:
        if targeting.get("flexible_spec"):
            strategy = "signal_based"
        else:
            strategy = "signal_based"  # Even without signals, A+ uses ML
    else:
        strategy = "strict"

    return {
        "targeting": targeting,
        "audience_strategy": {
            "advantage_plus_status": "enabled" if advantage_plus_on else "disabled",
            "advantage_plus_reason": advantage_reason,
            "audience_mode": "suggestion" if advantage_plus_on else "restricted",
            "targeting_strategy": strategy,
            "icp_signals_applied": bool(icp_derived_signals or icp_signals),
            "icp_name": icp_name,
            "icp_derived_interests": icp_derived_signals.get("interests", []),
            "expansion_allowed": advantage_plus_on,
        },
        "warnings": warnings,
        "blocked": False,
    }


def enforce_advantage_plus(
    targeting_dict: dict,
    audience_mode: str = "advantage_plus",
    experiment_type: Optional[str] = None,
) -> tuple[dict, list[str]]:
    """
    Enforce Advantage+ on an existing targeting dict.
    Returns (corrected_targeting, warnings).

    Use this for quick inline enforcement in create_adset.
    """
    warnings = []
    targeting = targeting_dict.copy() if targeting_dict else {}

    # Check if Advantage+ should be exempt
    is_exempt = (
        audience_mode == "restricted"
        or experiment_type == "strict_audience_test"
    )

    current_aa = targeting.get("targeting_automation", {}).get("advantage_audience")

    if is_exempt:
        # Ensure flag is explicitly set to OFF
        if "targeting_automation" not in targeting:
            targeting["targeting_automation"] = {"advantage_audience": 0}
        return targeting, warnings

    # Enforce ON
    if current_aa == 0 or current_aa is None:
        if current_aa == 0:
            warnings.append(
                "Advantage+ audience auto-enabled. Was explicitly OFF but no valid exemption. "
                "Use audience_mode='restricted' or experiment_type='strict_audience_test' to disable."
            )
        targeting["targeting_automation"] = {"advantage_audience": 1}

    # Check for narrowing issues
    narrowing = _detect_narrowing(targeting)
    for issue in narrowing:
        warnings.append(f"Narrowing warning: {issue}")

    return targeting, warnings


def _derive_icp_signals(icp_name: str) -> dict:
    """Derive targeting signals from ICP name using keyword matching."""
    signals = {"interests": [], "source": "icp_keyword_match"}

    icp_lower = icp_name.lower()
    matched_keys = []

    for key, interests in ICP_SIGNAL_MAP.items():
        # Check if any key words appear in the ICP name
        key_words = key.split()
        if any(w in icp_lower for w in key_words if len(w) > 3):
            signals["interests"].extend(interests)
            matched_keys.append(key)

    # Deduplicate
    signals["interests"] = list(dict.fromkeys(signals["interests"]))
    signals["matched_keys"] = matched_keys

    return signals


def _detect_narrowing(targeting: dict) -> list[str]:
    """Detect overly narrow targeting that harms delivery."""
    issues = []

    # Age range too narrow
    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    if age_min and age_max:
        age_range = age_max - age_min
        if age_range < NARROWING_THRESHOLDS["min_age_range"]:
            issues.append(
                f"Age range too narrow: {age_min}-{age_max} (span={age_range}). "
                f"Minimum recommended span: {NARROWING_THRESHOLDS['min_age_range']}."
            )

    # Too many interests (over-specification)
    flex_specs = targeting.get("flexible_spec", [])
    total_interests = 0
    for spec in flex_specs:
        if isinstance(spec, dict):
            total_interests += len(spec.get("interests", []))
    if total_interests > NARROWING_THRESHOLDS["max_interest_count"]:
        issues.append(
            f"Too many interest signals: {total_interests} > {NARROWING_THRESHOLDS['max_interest_count']}. "
            f"Consider reducing to top signals only."
        )

    # Too many exclusions
    exclusions = targeting.get("exclusions", {})
    total_exclusions = (
        len(exclusions.get("interests", []))
        + len(exclusions.get("behaviors", []))
        + len(exclusions.get("custom_audiences", []))
    )
    if total_exclusions > NARROWING_THRESHOLDS["max_exclusion_count"]:
        issues.append(
            f"Too many exclusions: {total_exclusions} > {NARROWING_THRESHOLDS['max_exclusion_count']}. "
            f"Over-excluding limits Meta's optimization ability."
        )

    # No geo at all
    geo = targeting.get("geo_locations", {})
    if not geo.get("countries") and not geo.get("regions") and not geo.get("cities"):
        issues.append("No geographic targeting set. At least one country is required.")

    return issues


def validate_audience_for_api(targeting: dict, audience_mode: str = "advantage_plus") -> dict:
    """
    Final validation before API call. Returns pass/fail with debug info.
    """
    issues = []
    aa_value = targeting.get("targeting_automation", {}).get("advantage_audience")

    is_exempt = audience_mode == "restricted"

    # Check Advantage+ status
    if not is_exempt and aa_value != 1:
        issues.append({
            "severity": "block",
            "message": "Advantage+ audience must be enabled for performance campaigns",
            "fix": "Set targeting_automation.advantage_audience = 1",
        })

    # Check narrowing
    narrowing = _detect_narrowing(targeting)
    for n in narrowing:
        issues.append({"severity": "warning", "message": n})

    # Check geo exists
    geo = targeting.get("geo_locations", {})
    if not geo:
        issues.append({
            "severity": "block",
            "message": "Missing geo_locations in targeting",
        })

    blockers = [i for i in issues if i["severity"] == "block"]

    return {
        "validation_passed": len(blockers) == 0,
        "issues": issues,
        "blocker_count": len(blockers),
        "warning_count": len(issues) - len(blockers),
        "advantage_plus_status": "enabled" if aa_value == 1 else "disabled",
        "audience_mode": "suggestion" if aa_value == 1 else "restricted",
        "targeting_strategy": "signal_based" if aa_value == 1 else "strict",
    }
