"""
Tests for ad update tool (Phase C.3).

Tests input validation logic without Meta API calls.
"""
import pytest


class TestUpdateAdInputValidation:
    """Verify update_ad input validation gates."""

    def test_no_fields_provided_returns_error(self):
        from meta_ads_mcp.core.ads import update_ad
        result = update_ad(ad_id="123456789")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "No update fields" in result["error"]

    def test_no_fields_lists_supported_fields(self):
        from meta_ads_mcp.core.ads import update_ad
        result = update_ad(ad_id="123456789")
        assert "supported_fields" in result
        assert "name" in result["supported_fields"]
        assert "status" in result["supported_fields"]
        assert "creative_id" in result["supported_fields"]

    def test_invalid_status_rejected(self):
        from meta_ads_mcp.core.ads import update_ad
        result = update_ad(ad_id="123456789", status="DELETED")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_statuses_pass_input_validation(self):
        from meta_ads_mcp.core.ads import update_ad
        from meta_ads_mcp.core.api import MetaAPIError
        for valid_status in ["PAUSED", "ACTIVE", "ARCHIVED"]:
            try:
                result = update_ad(ad_id="123456789", status=valid_status)
                assert result.get("blocked_at") != "input_validation"
            except MetaAPIError:
                pass  # Expected - no token

    def test_status_case_insensitive(self):
        from meta_ads_mcp.core.ads import update_ad
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_ad(ad_id="123456789", status="paused")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_non_numeric_creative_id_rejected(self):
        from meta_ads_mcp.core.ads import update_ad
        result = update_ad(ad_id="123456789", creative_id="not-a-number")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "numeric" in result["error"].lower()

    def test_numeric_creative_id_passes_input(self):
        from meta_ads_mcp.core.ads import update_ad
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_ad(ad_id="123456789", creative_id="120239290442460377")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_empty_creative_id_rejected(self):
        from meta_ads_mcp.core.ads import update_ad
        result = update_ad(ad_id="123456789", creative_id="")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"


class TestUpdateAdRegistration:
    """Verify update_ad is properly registered."""

    def test_function_exists_and_is_callable(self):
        from meta_ads_mcp.core.ads import update_ad
        assert callable(update_ad)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import ads
        source = inspect.getsource(ads)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def update_ad(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("update_ad is not registered with @mcp.tool()")
