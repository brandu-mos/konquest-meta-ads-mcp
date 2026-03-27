"""
Tests for standalone creative creation (Wave 1.3).

Tests registration, input validation, and parameter handling
without Meta API calls.
"""
import pytest


class TestCreateAdCreative:

    def test_function_exists(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        assert callable(create_ad_creative)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import creatives
        source = inspect.getsource(creatives)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def create_ad_creative(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("create_ad_creative is not registered with @mcp.tool()")

    def test_empty_image_hash_returns_error(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        result = create_ad_creative(
            account_id="act_123", page_id="123", image_hash="",
            link_url="https://example.com", primary_text="Test",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_empty_link_url_returns_error(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        result = create_ad_creative(
            account_id="act_123", page_id="123", image_hash="abc123",
            link_url="", primary_text="Test",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_empty_primary_text_returns_error(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        result = create_ad_creative(
            account_id="act_123", page_id="123", image_hash="abc123",
            link_url="https://example.com", primary_text="",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_empty_page_id_returns_error(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        result = create_ad_creative(
            account_id="act_123", page_id="", image_hash="abc123",
            link_url="https://example.com", primary_text="Test",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_invalid_cta_type_returns_error(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        result = create_ad_creative(
            account_id="act_123", page_id="123", image_hash="abc123",
            link_url="https://example.com", primary_text="Test",
            cta_type="INVALID_CTA",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "INVALID_CTA" in result["error"]

    def test_valid_cta_passes_input_validation(self):
        from meta_ads_mcp.core.creatives import create_ad_creative
        from meta_ads_mcp.core.api import MetaAPIError
        for cta in ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "NO_BUTTON"]:
            try:
                result = create_ad_creative(
                    account_id="act_123", page_id="123", image_hash="abc123",
                    link_url="https://example.com", primary_text="Test",
                    cta_type=cta,
                )
                assert result.get("blocked_at") != "input_validation", f"CTA '{cta}' should pass"
            except MetaAPIError:
                pass

    def test_default_cta_is_learn_more(self):
        import inspect
        from meta_ads_mcp.core.creatives import create_ad_creative
        sig = inspect.signature(create_ad_creative)
        assert sig.parameters["cta_type"].default == "LEARN_MORE"

    def test_name_is_optional(self):
        import inspect
        from meta_ads_mcp.core.creatives import create_ad_creative
        sig = inspect.signature(create_ad_creative)
        assert sig.parameters["name"].default is None

    def test_headline_is_optional(self):
        import inspect
        from meta_ads_mcp.core.creatives import create_ad_creative
        sig = inspect.signature(create_ad_creative)
        assert sig.parameters["headline"].default is None

    def test_description_is_optional(self):
        import inspect
        from meta_ads_mcp.core.creatives import create_ad_creative
        sig = inspect.signature(create_ad_creative)
        assert sig.parameters["description"].default is None
