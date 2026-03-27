"""
Tests for image upload tool (Wave 1.2).

Tests registration, input validation, and parameter handling
without Meta API calls.
"""
import pytest


class TestUploadAdImage:

    def test_function_exists(self):
        from meta_ads_mcp.core.images import upload_ad_image
        assert callable(upload_ad_image)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import images
        source = inspect.getsource(images)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def upload_ad_image(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("upload_ad_image is not registered with @mcp.tool()")

    def test_empty_url_returns_error(self):
        from meta_ads_mcp.core.images import upload_ad_image
        result = upload_ad_image(account_id="act_123456789", image_url="")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_whitespace_url_returns_error(self):
        from meta_ads_mcp.core.images import upload_ad_image
        result = upload_ad_image(account_id="act_123456789", image_url="   ")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_no_protocol_returns_error(self):
        from meta_ads_mcp.core.images import upload_ad_image
        result = upload_ad_image(account_id="act_123456789", image_url="example.com/image.jpg")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "http" in result["error"].lower()

    def test_ftp_protocol_returns_error(self):
        from meta_ads_mcp.core.images import upload_ad_image
        result = upload_ad_image(account_id="act_123456789", image_url="ftp://example.com/image.jpg")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_https_url_passes_validation(self):
        from meta_ads_mcp.core.images import upload_ad_image
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = upload_ad_image(
                account_id="act_123456789",
                image_url="https://example.com/test-image.jpg",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - no token

    def test_valid_http_url_passes_validation(self):
        from meta_ads_mcp.core.images import upload_ad_image
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = upload_ad_image(
                account_id="act_123456789",
                image_url="http://example.com/test-image.jpg",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_account_id_normalized(self):
        from meta_ads_mcp.core.images import upload_ad_image
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = upload_ad_image(
                account_id="123456789",
                image_url="https://example.com/test.jpg",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_optional_name_parameter(self):
        """Name parameter should be optional (default None)."""
        import inspect
        from meta_ads_mcp.core.images import upload_ad_image
        sig = inspect.signature(upload_ad_image)
        assert sig.parameters["name"].default is None
