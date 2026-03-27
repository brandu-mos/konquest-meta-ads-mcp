"""
Tests for safety tier classification.

Phase: v1.0 - these tests should pass immediately.
"""
import pytest
from meta_ads_mcp.safety.tiers import classify_action, SafetyTier


class TestSafetyTiers:
    def test_pause_is_tier_3(self):
        result = classify_action(action_type="pause")
        assert result["tier"] == 3

    def test_activate_is_tier_1(self):
        result = classify_action(action_type="activate")
        assert result["tier"] == 1
        assert result["requires_confirmation"] is True

    def test_create_paused_is_tier_3(self):
        result = classify_action(action_type="create", target_status="PAUSED")
        assert result["tier"] == 3

    def test_budget_decrease_is_tier_3(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            current_budget=20.0,
            proposed_budget=15.0,
        )
        assert result["tier"] == 3

    def test_large_budget_increase_is_tier_1(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            current_budget=20.0,
            proposed_budget=30.0,  # 50% increase
        )
        assert result["tier"] == 1

    def test_moderate_budget_increase_is_tier_2(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            current_budget=20.0,
            proposed_budget=24.0,  # 20% increase
        )
        assert result["tier"] == 2

    def test_small_budget_increase_is_tier_3(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            current_budget=20.0,
            proposed_budget=22.0,  # 10% increase
        )
        assert result["tier"] == 3

    def test_creative_swap_active_is_tier_1(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            is_creative_swap=True,
        )
        assert result["tier"] == 1

    def test_optimization_change_active_is_tier_1(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            is_optimization_change=True,
        )
        assert result["tier"] == 1

    def test_bulk_above_threshold_is_tier_1(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            object_count=10,
        )
        assert result["tier"] == 1

    def test_update_paused_is_tier_3(self):
        result = classify_action(
            action_type="update",
            target_status="PAUSED",
        )
        assert result["tier"] == 3

    def test_archive_is_tier_3(self):
        result = classify_action(action_type="archive")
        assert result["tier"] == 3

    def test_pixel_remap_active_is_tier_1(self):
        result = classify_action(
            action_type="update",
            target_status="ACTIVE",
            is_pixel_remap=True,
        )
        assert result["tier"] == 1

    def test_catalog_change_is_tier_1(self):
        result = classify_action(
            action_type="update",
            is_catalog_change=True,
        )
        assert result["tier"] == 1
