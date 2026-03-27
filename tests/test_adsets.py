"""
Tests for ad set update tool (Phase C.2).

Tests input validation logic without Meta API calls.
"""
import pytest


class TestUpdateAdsetInputValidation:
    """Verify update_adset input validation gates."""

    def test_no_fields_provided_returns_error(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(adset_id="123456789")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "No update fields" in result["error"]

    def test_no_fields_lists_supported_fields(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(adset_id="123456789")
        assert "supported_fields" in result
        assert "name" in result["supported_fields"]
        assert "daily_budget" in result["supported_fields"]
        assert "targeting_json" in result["supported_fields"]

    def test_both_budgets_rejected(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(
            adset_id="123456789",
            daily_budget=15.0,
            lifetime_budget=500.0,
        )
        assert "error" in result
        assert "both" in result["error"].lower()
        assert result["blocked_at"] == "input_validation"

    def test_invalid_status_rejected(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(
            adset_id="123456789",
            status="DELETED",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_statuses_pass_input_validation(self):
        """Valid statuses pass input validation (fail at API stage)."""
        from meta_ads_mcp.core.adsets import update_adset
        from meta_ads_mcp.core.api import MetaAPIError
        for valid_status in ["PAUSED", "ACTIVE", "ARCHIVED"]:
            try:
                result = update_adset(
                    adset_id="123456789",
                    status=valid_status,
                )
                assert result.get("blocked_at") != "input_validation"
            except MetaAPIError:
                pass  # Expected - no token

    def test_status_case_insensitive(self):
        from meta_ads_mcp.core.adsets import update_adset
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_adset(
                adset_id="123456789",
                status="paused",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_malformed_targeting_json_rejected(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(
            adset_id="123456789",
            targeting_json="not valid json{{{",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "Malformed" in result["error"]

    def test_targeting_must_be_object(self):
        from meta_ads_mcp.core.adsets import update_adset
        result = update_adset(
            adset_id="123456789",
            targeting_json='["array", "not", "object"]',
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "object" in result["error"].lower()

    def test_valid_targeting_passes_input_validation(self):
        from meta_ads_mcp.core.adsets import update_adset
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_adset(
                adset_id="123456789",
                targeting_json='{"geo_locations":{"countries":["GR"]},"age_min":25}',
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass


class TestUpdateAdsetRegistration:
    """Verify update_adset is properly registered."""

    def test_function_exists_and_is_callable(self):
        from meta_ads_mcp.core.adsets import update_adset
        assert callable(update_adset)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import adsets
        source = inspect.getsource(adsets)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def update_adset(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("update_adset is not registered with @mcp.tool()")
