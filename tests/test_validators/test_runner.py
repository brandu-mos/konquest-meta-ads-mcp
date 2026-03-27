"""
Tests for the validation runner.

Phase: v1.0 - these tests should pass immediately.
"""
import pytest
from meta_ads_mcp.validators.runner import (
    run_validation,
    ActionClass,
    ValidationVerdict,
    CheckStatus,
)


class TestValidationRunner:
    def test_create_paused_passes(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "PAUSED", "name": "Test Campaign"},
            safety_tier=3,
        )
        assert result.verdict in (ValidationVerdict.PASS, ValidationVerdict.PASS_WITH_WARNINGS)

    def test_create_active_fails(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "ACTIVE"},
            safety_tier=3,
        )
        assert result.verdict == ValidationVerdict.FAIL
        assert any("ACTIVE" in issue for issue in result.blocking_issues)

    def test_activation_requires_confirmation(self):
        result = run_validation(
            action_class=ActionClass.ACTIVATE,
            target_account_id="act_123",
            target_object_type="campaign",
            target_object_id="123456",
            safety_tier=1,
        )
        assert result.confirmation_required is True

    def test_greek_text_validation(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="ad",
            payload={"name": "Ελληνική Διαφήμιση", "status": "PAUSED"},
            safety_tier=3,
        )
        # Should pass - valid Greek text
        greek_checks = [c for c in result.checks if c.category == "F"]
        assert len(greek_checks) > 0

    def test_corrupted_greek_fails(self):
        # Use text with replacement character mixed with Greek - this IS detectable
        # because contains_greek() returns True (real Greek chars present alongside corruption)
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="ad",
            payload={"name": "Ελληνικ\ufffdα", "status": "PAUSED"},
            safety_tier=3,
        )
        # Should have Greek text issues (replacement character in Greek text)
        greek_fails = [c for c in result.checks if c.category == "F" and c.status == CheckStatus.FAIL]
        assert len(greek_fails) > 0

    def test_mojibake_detected_directly(self):
        """Mojibake without Greek chars is caught by validate_greek_text directly."""
        from meta_ads_mcp.validators.greek_text import validate_greek_text
        result = validate_greek_text("Î•Î»Î»Î·Î½Î¹ÎºÎ¬", "test")
        assert result.is_safe is False
        assert result.has_critical is True

    def test_validation_id_generated(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "PAUSED"},
            safety_tier=3,
        )
        assert result.validation_id is not None
        assert len(result.validation_id) > 0

    def test_to_dict(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "PAUSED"},
            safety_tier=3,
        )
        d = result.to_dict()
        assert "validation_id" in d
        assert "result" in d
        assert "checks" in d


class TestSkippedCategories:
    """Verify that unimplemented validator categories are honestly reported."""

    def test_activation_reports_skipped_categories(self):
        """ACTIVATE runs all 6 categories - A, C, D should report SKIPPED."""
        result = run_validation(
            action_class=ActionClass.ACTIVATE,
            target_account_id="act_123",
            target_object_type="campaign",
            target_object_id="123",
            safety_tier=1,
        )
        check_messages = [c.message for c in result.checks]
        skipped_msgs = [m for m in check_messages if "SKIPPED" in m]
        # Categories A, C, D should all report SKIPPED
        assert len(skipped_msgs) >= 3, f"Expected 3+ SKIPPED categories, got {len(skipped_msgs)}: {skipped_msgs}"

    def test_skipped_categories_are_warnings_not_passes(self):
        """Unimplemented categories must be WARN, never PASS."""
        result = run_validation(
            action_class=ActionClass.ACTIVATE,
            target_account_id="act_123",
            target_object_type="campaign",
            target_object_id="123",
            safety_tier=1,
        )
        for check in result.checks:
            if "SKIPPED" in check.message:
                assert check.status == CheckStatus.WARN, (
                    f"SKIPPED category {check.category} has status {check.status.value} - should be WARN"
                )

    def test_create_reports_skipped_tracking(self):
        """CREATE runs categories B, C, E, F - C should be SKIPPED."""
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "PAUSED"},
            safety_tier=3,
        )
        c_checks = [c for c in result.checks if c.category == "C"]
        assert len(c_checks) > 0
        assert "SKIPPED" in c_checks[0].message


class TestToLogEntry:
    def test_log_entry_format(self):
        result = run_validation(
            action_class=ActionClass.CREATE,
            target_account_id="act_123",
            target_object_type="campaign",
            payload={"status": "PAUSED"},
            safety_tier=3,
        )
        log = result.to_log_entry()
        assert "Validation:" in log
        assert "CREATE" in log
        assert "campaign" in log
