"""
Tests for campaign update tool (Phase C.1).

Tests input validation logic without Meta API calls.
API-dependent behavior (actual updates, verification) requires live token
and is covered by manual integration testing.
"""
import pytest


class TestUpdateCampaignInputValidation:
    """Verify update_campaign input validation gates."""

    def test_no_fields_provided_returns_error(self):
        """Calling update_campaign with no fields must return an error."""
        from meta_ads_mcp.core.campaigns import update_campaign
        result = update_campaign(campaign_id="123456789")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "No update fields" in result["error"]

    def test_no_fields_lists_supported_fields(self):
        """Error response must list supported fields."""
        from meta_ads_mcp.core.campaigns import update_campaign
        result = update_campaign(campaign_id="123456789")
        assert "supported_fields" in result
        assert "name" in result["supported_fields"]
        assert "daily_budget" in result["supported_fields"]
        assert "status" in result["supported_fields"]

    def test_both_budgets_rejected(self):
        """Cannot set both daily_budget and lifetime_budget."""
        from meta_ads_mcp.core.campaigns import update_campaign
        result = update_campaign(
            campaign_id="123456789",
            daily_budget=50.0,
            lifetime_budget=500.0,
        )
        assert "error" in result
        assert "both" in result["error"].lower()
        assert result["blocked_at"] == "input_validation"

    def test_invalid_status_rejected(self):
        """Invalid status values must be rejected."""
        from meta_ads_mcp.core.campaigns import update_campaign
        result = update_campaign(
            campaign_id="123456789",
            status="DELETED",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "DELETED" in result["error"]

    def test_valid_statuses_pass_input_validation(self):
        """PAUSED, ACTIVE, ARCHIVED should pass input validation.
        They will raise MetaAPIError at pre_snapshot (no token) - not input_validation error."""
        from meta_ads_mcp.core.campaigns import update_campaign
        from meta_ads_mcp.core.api import MetaAPIError
        for valid_status in ["PAUSED", "ACTIVE", "ARCHIVED"]:
            try:
                result = update_campaign(
                    campaign_id="123456789",
                    status=valid_status,
                )
                # If it returns a dict, check it wasn't blocked at input_validation
                assert result.get("blocked_at") != "input_validation", \
                    f"Status '{valid_status}' should pass input validation"
            except MetaAPIError:
                # Expected - no META_ACCESS_TOKEN set. Input validation passed.
                pass

    def test_status_case_insensitive(self):
        """Status should be normalized to uppercase (lowercase 'paused' accepted)."""
        from meta_ads_mcp.core.campaigns import update_campaign
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_campaign(
                campaign_id="123456789",
                status="paused",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - no token. Input validation passed.

    def test_invalid_special_ad_category_rejected(self):
        """Invalid special_ad_categories must be rejected."""
        from meta_ads_mcp.core.campaigns import update_campaign
        result = update_campaign(
            campaign_id="123456789",
            special_ad_categories="INVALID_CATEGORY",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"
        assert "INVALID_CATEGORY" in result["error"]

    def test_valid_special_ad_categories_pass_input(self):
        """Valid special_ad_categories pass input validation."""
        from meta_ads_mcp.core.campaigns import update_campaign
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_campaign(
                campaign_id="123456789",
                special_ad_categories="CREDIT,HOUSING",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - no token

    def test_empty_special_ad_categories_clears(self):
        """Empty string for special_ad_categories should pass (clears the field)."""
        from meta_ads_mcp.core.campaigns import update_campaign
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = update_campaign(
                campaign_id="123456789",
                special_ad_categories="",
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - no token


class TestUpdateCampaignFieldSignature:
    """Verify the tool signature matches expected interface."""

    def test_function_exists_and_is_callable(self):
        from meta_ads_mcp.core.campaigns import update_campaign
        assert callable(update_campaign)

    def test_tool_is_registered(self):
        """update_campaign must be registered as an MCP tool (not commented out)."""
        import inspect
        from meta_ads_mcp.core import campaigns
        source = inspect.getsource(campaigns)
        # Find the @mcp.tool() decorator line before def update_campaign
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def update_campaign(" in line:
                # Look backwards for the decorator
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return  # Found uncommented decorator
                pytest.fail("update_campaign is not registered with @mcp.tool()")
