"""
Tests for static multi-dimension image ad support (Wave 2.0).

Tests input validation, blocking rules, and mode detection
without Meta API calls.
"""
import pytest


class TestMultiImageInputValidation:

    def test_mixed_video_image_blocked(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        result = create_multi_asset_ad(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
            video_9x16_id="vid123",
            image_1x1_hash="hash1",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "Mixed" in result["error"]

    def test_no_asset_blocked(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        result = create_multi_asset_ad(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "No asset" in result["error"]

    def test_single_image_hash_blocked(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        result = create_multi_asset_ad(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
            image_1x1_hash="hash1",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "At least 2" in result["error"]

    def test_single_4x5_hash_blocked(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        result = create_multi_asset_ad(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
            image_4x5_hash="hash1",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_single_9x16_hash_blocked(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        result = create_multi_asset_ad(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
            image_9x16_hash="hash1",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"


class TestMultiImageCombinations:
    """Test that all valid 2-of-3 and 3-of-3 combinations pass input validation."""

    def _call(self, **kwargs):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        from meta_ads_mcp.core.api import MetaAPIError
        base = dict(
            account_id="act_123", adset_id="456", page_id="789",
            ad_name="Test", primary_text="test", destination_url="https://example.com",
        )
        base.update(kwargs)
        try:
            result = create_multi_asset_ad(**base)
            return result
        except MetaAPIError:
            return {"passed_input": True}  # Hit API = passed input validation

    def test_1x1_plus_4x5_passes(self):
        result = self._call(image_1x1_hash="h1", image_4x5_hash="h2")
        assert result.get("blocked_at") != "input_validation"

    def test_1x1_plus_9x16_passes(self):
        result = self._call(image_1x1_hash="h1", image_9x16_hash="h2")
        assert result.get("blocked_at") != "input_validation"

    def test_4x5_plus_9x16_passes(self):
        result = self._call(image_4x5_hash="h1", image_9x16_hash="h2")
        assert result.get("blocked_at") != "input_validation"

    def test_all_three_passes(self):
        result = self._call(image_1x1_hash="h1", image_4x5_hash="h2", image_9x16_hash="h3")
        assert result.get("blocked_at") != "input_validation"


class TestVideoPathIntact:
    """Verify existing video path still works after image additions."""

    def test_video_only_still_passes_input(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = create_multi_asset_ad(
                account_id="act_123", adset_id="456", page_id="789",
                ad_name="Test", primary_text="test", destination_url="https://example.com",
                video_9x16_id="vid1", video_1x1_id="vid2",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - hit API

    def test_single_video_still_passes_input(self):
        from meta_ads_mcp.core.ad_builder import create_multi_asset_ad
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = create_multi_asset_ad(
                account_id="act_123", adset_id="456", page_id="789",
                ad_name="Test", primary_text="test", destination_url="https://example.com",
                video_9x16_id="vid1",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass


class TestPlacementRules:
    """Verify 4:5 placement rules exist."""

    def test_4x5_in_placement_rules(self):
        from meta_ads_mcp.core.ad_builder import PLACEMENT_RULES
        assert "4x5" in PLACEMENT_RULES
        spec = PLACEMENT_RULES["4x5"]["customization_spec"]
        assert "facebook" in spec["publisher_platforms"]
        assert "instagram" in spec["publisher_platforms"]
        assert "feed" in spec["facebook_positions"]
        assert "feed" in spec["instagram_positions"]

    def test_all_three_ratios_in_rules(self):
        from meta_ads_mcp.core.ad_builder import PLACEMENT_RULES
        assert "1x1" in PLACEMENT_RULES
        assert "4x5" in PLACEMENT_RULES
        assert "9x16" in PLACEMENT_RULES
