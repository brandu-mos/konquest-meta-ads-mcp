"""
Tests for gap closure features: creative update, bulk insights, ad-level duplication.
"""
import pytest


class TestUpdateAdCreative:

    def test_function_exists(self):
        from meta_ads_mcp.core.creatives import update_ad_creative
        assert callable(update_ad_creative)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import creatives
        source = inspect.getsource(creatives)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def update_ad_creative(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("update_ad_creative is not registered")

    def test_no_name_returns_error(self):
        from meta_ads_mcp.core.creatives import update_ad_creative
        result = update_ad_creative(creative_id="123")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "name is required" in result["error"]

    def test_empty_name_returns_error(self):
        from meta_ads_mcp.core.creatives import update_ad_creative
        result = update_ad_creative(creative_id="123", name="   ")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_name_passes_input(self):
        from meta_ads_mcp.core.creatives import update_ad_creative
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_ad_creative(creative_id="123", name="New Name")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_documents_copy_immutability(self):
        """Tool must document that copy is immutable."""
        import inspect
        from meta_ads_mcp.core import creatives
        source = inspect.getsource(creatives.update_ad_creative)
        assert "immutable" in source.lower()
        assert "create_ad_creative" in source


class TestGetBulkInsights:

    def test_function_exists(self):
        from meta_ads_mcp.core.insights import get_bulk_insights
        assert callable(get_bulk_insights)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import insights
        source = inspect.getsource(insights)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def get_bulk_insights(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("get_bulk_insights is not registered")

    def test_invalid_time_range(self):
        from meta_ads_mcp.core.insights import get_bulk_insights
        result = get_bulk_insights(time_range="invalid")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_invalid_level(self):
        from meta_ads_mcp.core.insights import get_bulk_insights
        result = get_bulk_insights(level="campaign")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_params_pass_input(self):
        from meta_ads_mcp.core.insights import get_bulk_insights
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = get_bulk_insights(time_range="last_7d")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass


class TestAdLevelDuplication:

    def test_include_ads_parameter_exists(self):
        import inspect
        from meta_ads_mcp.core.duplication import duplicate_campaign
        sig = inspect.signature(duplicate_campaign)
        assert "include_ads" in sig.parameters
        assert sig.parameters["include_ads"].default is False

    def test_ad_duplication_helper_exists(self):
        from meta_ads_mcp.core.duplication import _duplicate_ads_for_adset
        assert callable(_duplicate_ads_for_adset)


class TestSetupYamlEncoding:

    def test_accounts_yaml_read_uses_utf8(self):
        """Verify setup.py opens accounts.yaml with encoding='utf-8'."""
        import inspect
        from meta_ads_mcp.core import setup
        source = inspect.getsource(setup.run_setup_check)
        assert 'encoding="utf-8"' in source or "encoding='utf-8'" in source
