"""
Tests for final convenience gap closure: adset dup, get_ad_image, product sets.
"""
import pytest


class TestDuplicateAdset:

    def test_function_exists(self):
        from meta_ads_mcp.core.duplication import duplicate_adset
        assert callable(duplicate_adset)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def duplicate_adset(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("duplicate_adset not registered")

    def test_default_name_suffix(self):
        import inspect
        from meta_ads_mcp.core.duplication import duplicate_adset
        sig = inspect.signature(duplicate_adset)
        assert sig.parameters["name_suffix"].default == " - Copy"


class TestGetAdImage:

    def test_function_exists(self):
        from meta_ads_mcp.core.images import get_ad_image
        assert callable(get_ad_image)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import images
        source = inspect.getsource(images)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def get_ad_image(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("get_ad_image not registered")

    def test_empty_hash_returns_error(self):
        from meta_ads_mcp.core.images import get_ad_image
        result = get_ad_image(account_id="act_123", image_hash="")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"


class TestCreateProductSet:

    def test_function_exists(self):
        from meta_ads_mcp.core.catalogs import create_product_set
        assert callable(create_product_set)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import catalogs
        source = inspect.getsource(catalogs)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def create_product_set(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("create_product_set not registered")

    def test_no_longer_raises_not_implemented(self):
        """Scaffold must be replaced - no more NotImplementedError."""
        import inspect
        from meta_ads_mcp.core import catalogs
        source = inspect.getsource(catalogs.create_product_set)
        assert "NotImplementedError" not in source

    def test_empty_name_returns_error(self):
        from meta_ads_mcp.core.catalogs import create_product_set
        result = create_product_set(catalog_id="123", name="", filter_json='{}')
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_malformed_json_returns_error(self):
        from meta_ads_mcp.core.catalogs import create_product_set
        result = create_product_set(catalog_id="123", name="Test", filter_json="not json{{{")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"


class TestUpdateProductSet:

    def test_function_exists(self):
        from meta_ads_mcp.core.catalogs import update_product_set
        assert callable(update_product_set)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import catalogs
        source = inspect.getsource(catalogs)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def update_product_set(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("update_product_set not registered")

    def test_no_longer_raises_not_implemented(self):
        import inspect
        from meta_ads_mcp.core import catalogs
        source = inspect.getsource(catalogs.update_product_set)
        assert "NotImplementedError" not in source

    def test_no_fields_returns_error(self):
        from meta_ads_mcp.core.catalogs import update_product_set
        result = update_product_set(product_set_id="123")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
