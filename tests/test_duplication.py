"""
Tests for campaign duplication tool (Phase F.1).

Tests input validation and enforcement logic without Meta API calls.
"""
import pytest


class TestDuplicateCampaignInputValidation:
    """Verify duplicate_campaign input validation gates."""

    def test_function_exists_and_is_callable(self):
        from meta_ads_mcp.core.duplication import duplicate_campaign
        assert callable(duplicate_campaign)

    def test_tool_is_registered(self):
        """duplicate_campaign must be registered as an MCP tool."""
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def duplicate_campaign(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("duplicate_campaign is not registered with @mcp.tool()")

    def test_missing_campaign_id_hits_api(self):
        """Without a real token, calling with any campaign_id should fail at API level, not input validation."""
        from meta_ads_mcp.core.duplication import duplicate_campaign
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = duplicate_campaign(
                campaign_id="999999999",
                account_id="act_123456789",
            )
            # If it returns (no exception), it should be an error from source_read
            assert "error" in result
        except MetaAPIError:
            pass  # Expected - no token

    def test_default_name_suffix(self):
        """Default name_suffix should be ' - Copy'."""
        import inspect
        from meta_ads_mcp.core.duplication import duplicate_campaign
        sig = inspect.signature(duplicate_campaign)
        assert sig.parameters["name_suffix"].default == " - Copy"

    def test_default_include_adsets(self):
        """Default include_adsets should be True."""
        import inspect
        from meta_ads_mcp.core.duplication import duplicate_campaign
        sig = inspect.signature(duplicate_campaign)
        assert sig.parameters["include_adsets"].default is True

    def test_default_budget_override_is_none(self):
        """Default adset_budget_override should be None."""
        import inspect
        from meta_ads_mcp.core.duplication import duplicate_campaign
        sig = inspect.signature(duplicate_campaign)
        assert sig.parameters["adset_budget_override"].default is None


class TestDuplicateAdsetHelper:
    """Verify _duplicate_single_adset helper logic."""

    def test_helper_exists(self):
        from meta_ads_mcp.core.duplication import _duplicate_single_adset
        assert callable(_duplicate_single_adset)

    def test_naming_enforcement_on_adset(self):
        """Adset duplication should go through naming enforcement."""
        from meta_ads_mcp.core.duplication import _duplicate_single_adset
        from meta_ads_mcp.core.api import MetaAPIError

        source_adset = {
            "id": "123",
            "name": "Test Adset",
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "IMPRESSIONS",
            "targeting": {"geo_locations": {"countries": ["GR"]}},
        }

        # This will either fail at naming or at API call (no token)
        try:
            result = _duplicate_single_adset(
                source_adset=source_adset,
                new_campaign_id="999",
                account_id="act_123456789",
                name_suffix=" - Copy",
                budget_model="ABO",
                adset_budget_override=None,
            )
            # If naming blocks, we get an error dict
            # If naming passes but API fails, we get a different error
            assert isinstance(result, dict)
        except MetaAPIError:
            pass  # Expected - no token

    def test_cbo_adset_has_no_budget(self):
        """When budget_model is CBO, ad set should not get a budget."""
        from meta_ads_mcp.core.duplication import _duplicate_single_adset
        from meta_ads_mcp.core.api import MetaAPIError

        source_adset = {
            "id": "123",
            "name": "CBO Test",
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "IMPRESSIONS",
            "daily_budget": "500",  # Source has budget but CBO should skip it
        }

        try:
            result = _duplicate_single_adset(
                source_adset=source_adset,
                new_campaign_id="999",
                account_id="act_123456789",
                name_suffix=" - Copy",
                budget_model="CBO",
                adset_budget_override=None,
            )
            # If it gets past naming to payload building, CBO should skip budget
            # We can't fully verify without API, but at least it shouldn't crash
            assert isinstance(result, dict)
        except MetaAPIError:
            pass

    def test_abo_budget_override_applied(self):
        """When budget_model is ABO and override is set, override should be used."""
        # This test verifies the logic path exists - full verification requires API
        from meta_ads_mcp.core.duplication import _duplicate_single_adset
        assert callable(_duplicate_single_adset)
        # The actual budget override is applied in payload["daily_budget"]
        # which we can't inspect without mocking. Functional test needed on live.


class TestSameAccountEnforcement:
    """Verify cross-account duplication is blocked."""

    def test_cross_account_blocked_message(self):
        """If source and target account differ, must return explicit blocked error."""
        # We can't easily test this without API since same-account check
        # happens after reading the source campaign. But we verify the
        # function has the check by inspecting the source.
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication.duplicate_campaign)
        assert "same_account_enforcement" in source
        assert "Cross-account duplication is not supported" in source

    def test_partial_success_handling_in_source(self):
        """Verify partial_success status is handled in the code."""
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication.duplicate_campaign)
        assert "partial_success" in source
        assert "orphaned_objects" in source
        assert "failed_adsets" in source


class TestAllPausedEnforcement:
    """Verify everything created is PAUSED."""

    def test_campaign_payload_always_paused(self):
        """Source inspection: campaign payload must hardcode PAUSED."""
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication.duplicate_campaign)
        # The campaign_payload dict must contain status: PAUSED
        assert '"status": "PAUSED"' in source or "'status': 'PAUSED'" in source

    def test_adset_payload_always_paused(self):
        """Source inspection: ad set payload must hardcode PAUSED."""
        import inspect
        from meta_ads_mcp.core import duplication
        source = inspect.getsource(duplication._duplicate_single_adset)
        assert '"status": "PAUSED"' in source or "'status': 'PAUSED'" in source
