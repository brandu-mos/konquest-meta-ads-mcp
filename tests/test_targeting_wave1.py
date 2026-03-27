"""
Tests for Wave 1.1 targeting parity tools.

Tests registration, input validation, and parameter handling
without Meta API calls.
"""
import pytest


class TestGetInterestSuggestions:

    def test_function_exists(self):
        from meta_ads_mcp.core.targeting import get_interest_suggestions
        assert callable(get_interest_suggestions)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import targeting
        source = inspect.getsource(targeting)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def get_interest_suggestions(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("get_interest_suggestions is not registered")

    def test_empty_interest_list_returns_error(self):
        from meta_ads_mcp.core.targeting import get_interest_suggestions
        result = get_interest_suggestions(interest_list="")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_whitespace_only_returns_error(self):
        from meta_ads_mcp.core.targeting import get_interest_suggestions
        result = get_interest_suggestions(interest_list="  ,  , ")
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_input_passes_validation(self):
        from meta_ads_mcp.core.targeting import get_interest_suggestions
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = get_interest_suggestions(interest_list="yoga,fitness")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass  # Expected - no token


class TestSearchDemographics:

    def test_function_exists(self):
        from meta_ads_mcp.core.targeting import search_demographics
        assert callable(search_demographics)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import targeting
        source = inspect.getsource(targeting)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def search_demographics(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("search_demographics is not registered")

    def test_no_query_passes_validation(self):
        """search_demographics with no query should list all demographics."""
        from meta_ads_mcp.core.targeting import search_demographics
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = search_demographics()
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_with_query_passes_validation(self):
        from meta_ads_mcp.core.targeting import search_demographics
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = search_demographics(query="homeowner")
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass


class TestEstimateAudienceSize:

    def test_function_exists(self):
        from meta_ads_mcp.core.targeting import estimate_audience_size
        assert callable(estimate_audience_size)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import targeting
        source = inspect.getsource(targeting)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def estimate_audience_size(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("estimate_audience_size is not registered")

    def test_malformed_json_returns_error(self):
        from meta_ads_mcp.core.targeting import estimate_audience_size
        result = estimate_audience_size(
            account_id="act_123456789",
            targeting_json="not valid json{{{",
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_targeting_must_be_object(self):
        from meta_ads_mcp.core.targeting import estimate_audience_size
        result = estimate_audience_size(
            account_id="act_123456789",
            targeting_json='["array"]',
        )
        assert "error" in result
        assert result["blocked_at"] == "input_validation"

    def test_valid_targeting_passes_validation(self):
        from meta_ads_mcp.core.targeting import estimate_audience_size
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = estimate_audience_size(
                account_id="act_123456789",
                targeting_json='{"geo_locations":{"countries":["GR"]},"age_min":25}',
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass

    def test_account_id_normalized(self):
        """Account ID without act_ prefix should be normalized."""
        from meta_ads_mcp.core.targeting import estimate_audience_size
        from meta_ads_mcp.core.api import MetaAPIError
        try:
            result = estimate_audience_size(
                account_id="123456789",
                targeting_json='{"geo_locations":{"countries":["GR"]}}',
            )
            assert result.get("blocked_at") != "input_validation"
        except MetaAPIError:
            pass
