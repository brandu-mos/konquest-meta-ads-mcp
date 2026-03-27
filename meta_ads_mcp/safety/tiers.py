"""
Safety tier classification system.

Classifies every write operation into one of three tiers:
  Tier 1: Mandatory confirmation (high risk)
  Tier 2: Dry-run preview (moderate risk)
  Tier 3: Unrestricted (low risk)

Loads configurable thresholds from config/thresholds.yaml.

Phase: v1.0 (Foundation) - fully implemented.
"""
import logging
import os
from enum import IntEnum
from typing import Optional

import yaml

logger = logging.getLogger("meta-ads-mcp.safety.tiers")


class SafetyTier(IntEnum):
    """Safety tier levels. Lower number = higher risk = more gates."""
    TIER_1 = 1  # Mandatory confirmation
    TIER_2 = 2  # Dry-run preview then confirm
    TIER_3 = 3  # Unrestricted


# Default thresholds (overridden by config/thresholds.yaml)
DEFAULT_THRESHOLDS = {
    "budget_increase_confirm_pct": 30,
    "budget_increase_preview_pct": 15,
    "bulk_mutation_confirm_count": 5,
    "high_spend_daily_threshold_eur": 100,
}

_loaded_thresholds: Optional[dict] = None


def _load_thresholds() -> dict:
    """Load thresholds from config file, falling back to defaults."""
    global _loaded_thresholds
    if _loaded_thresholds is not None:
        return _loaded_thresholds

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config", "thresholds.yaml"
    )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        _loaded_thresholds = config.get("safety", DEFAULT_THRESHOLDS)
        logger.info("Loaded safety thresholds from %s", config_path)
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.warning("Could not load thresholds from %s: %s. Using defaults.", config_path, e)
        _loaded_thresholds = DEFAULT_THRESHOLDS

    return _loaded_thresholds


def classify_action(
    action_type: str,
    target_status: str = "PAUSED",
    current_budget: Optional[float] = None,
    proposed_budget: Optional[float] = None,
    object_count: int = 1,
    is_creative_swap: bool = False,
    is_optimization_change: bool = False,
    is_pixel_remap: bool = False,
    is_catalog_change: bool = False,
) -> dict:
    """
    Classify a write action into a safety tier.

    Args:
        action_type: Type of action ('create', 'update', 'activate', 'pause', 'delete', 'archive').
        target_status: Current status of the target object ('ACTIVE', 'PAUSED').
        current_budget: Current budget in currency units (e.g., EUR).
        proposed_budget: Proposed new budget in currency units.
        object_count: Number of objects affected (for bulk operations).
        is_creative_swap: Whether this is a creative replacement on active ad.
        is_optimization_change: Whether this changes the optimization event.
        is_pixel_remap: Whether this remaps pixel/dataset.
        is_catalog_change: Whether this changes catalog connections.

    Returns:
        dict with:
        - tier: SafetyTier value (1, 2, or 3)
        - reason: Human-readable reason for the classification
        - requires_confirmation: bool
        - requires_preview: bool
    """
    thresholds = _load_thresholds()
    confirm_pct = thresholds.get("budget_increase_confirm_pct", 30)
    preview_pct = thresholds.get("budget_increase_preview_pct", 15)
    bulk_threshold = thresholds.get("bulk_mutation_confirm_count", 5)

    # --- Always Tier 3 (safe) ---

    # Pausing is always safe (stops spend)
    if action_type == "pause":
        return _result(SafetyTier.TIER_3, "Pausing stops spend - always safe")

    # Budget decreases are always safe
    if current_budget and proposed_budget and proposed_budget < current_budget:
        return _result(SafetyTier.TIER_3, "Budget decrease - reduces spend")

    # All reads are safe (handled elsewhere, but included for completeness)
    if action_type in ("read", "get", "list"):
        return _result(SafetyTier.TIER_3, "Read operation")

    # --- Tier 1 checks that apply regardless of status ---

    # Catalog connection changes are always Tier 1 (affects data pipeline)
    if is_catalog_change:
        return _result(SafetyTier.TIER_1, "Catalog connection change affects product delivery")

    # Pixel/dataset remap is always Tier 1 (affects attribution)
    if is_pixel_remap:
        return _result(SafetyTier.TIER_1, "Pixel/dataset remapping breaks attribution chain")

    # Bulk operations above threshold are always Tier 1
    if object_count > bulk_threshold:
        return _result(
            SafetyTier.TIER_1,
            f"Bulk mutation affecting {object_count} objects (threshold: {bulk_threshold})"
        )

    # Creating as PAUSED is safe
    if action_type == "create" and target_status == "PAUSED":
        return _result(SafetyTier.TIER_3, "Creating as PAUSED - no live impact")

    # Updates to PAUSED objects are safe
    if action_type == "update" and target_status == "PAUSED":
        return _result(SafetyTier.TIER_3, "Updating PAUSED object - no live impact")

    # Archive is safe
    if action_type == "archive":
        return _result(SafetyTier.TIER_3, "Archiving - reversible, no live impact")

    # --- Tier 1 (mandatory confirmation) ---

    # Activation gate
    if action_type == "activate":
        return _result(SafetyTier.TIER_1, "PAUSED -> ACTIVE requires user confirmation")

    # Budget increase > confirm_pct on active
    if (current_budget and proposed_budget and target_status == "ACTIVE"):
        increase_pct = ((proposed_budget - current_budget) / current_budget) * 100
        if increase_pct > confirm_pct:
            return _result(
                SafetyTier.TIER_1,
                f"Budget increase of {increase_pct:.1f}% exceeds {confirm_pct}% threshold on active object"
            )
        if increase_pct > preview_pct:
            return _result(
                SafetyTier.TIER_2,
                f"Budget increase of {increase_pct:.1f}% between {preview_pct}-{confirm_pct}% on active object"
            )
        # Below preview threshold
        return _result(SafetyTier.TIER_3, f"Budget increase of {increase_pct:.1f}% below {preview_pct}% threshold")

    # Creative swap on active
    if is_creative_swap and target_status == "ACTIVE":
        return _result(SafetyTier.TIER_1, "Creative replacement on active ad")

    # Optimization event change on active
    if is_optimization_change and target_status == "ACTIVE":
        return _result(SafetyTier.TIER_1, "Optimization event change on active ad set - resets learning phase")

    # --- Tier 2 (dry-run preview) ---

    # Targeting changes on active
    if action_type == "update" and target_status == "ACTIVE":
        return _result(SafetyTier.TIER_2, "Updating active object - preview recommended")

    # --- Default: Tier 3 ---
    return _result(SafetyTier.TIER_3, "Standard operation - no additional gates required")


def _result(tier: SafetyTier, reason: str) -> dict:
    """Build a classification result dict."""
    return {
        "tier": int(tier),
        "tier_name": f"Tier {int(tier)}",
        "reason": reason,
        "requires_confirmation": tier == SafetyTier.TIER_1,
        "requires_preview": tier == SafetyTier.TIER_2,
    }
