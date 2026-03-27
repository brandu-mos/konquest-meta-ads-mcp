"""
Targeting search tools.

Interest, behavior, geographic, and demographic targeting search,
audience size estimation, and interest suggestions via Meta's
ad targeting search API.

Phase: v1.1 (Read Operations) + Wave 1.1 (Targeting Parity)
"""
import json as _json
import logging
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.targeting")


def _format_audience_size(lower: int, upper: int) -> str:
    """Format audience size range for display."""
    if lower == 0 and upper == 0:
        return "unknown"

    def _fmt(n: int) -> str:
        if n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

    return f"{_fmt(lower)}-{_fmt(upper)}"


@mcp.tool()
def search_interests(
    query: str,
    limit: int = 20,
) -> dict:
    """
    Search for interest-based targeting options.

    Returns matching interests with audience size estimates, topic category, and path.

    Args:
        query: Search term (e.g., 'yoga', 'hospitality', 'skincare').
        limit: Max results (default 20).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            "/search",
            params={
                "type": "adinterest",
                "q": query,
                "limit": str(min(limit, 50)),
            },
        )

        interests = result.get("data", [])

        # Enrich with formatted size and classification
        for interest in interests:
            lower = interest.get("audience_size_lower_bound", 0) or 0
            upper = interest.get("audience_size_upper_bound", 0) or 0
            interest["audience_size_display"] = _format_audience_size(lower, upper)
            interest["audience_size_lower_bound"] = lower
            interest["audience_size_upper_bound"] = upper

            # Size classification
            if upper > 100_000_000:
                interest["size_class"] = "very_broad"
            elif upper > 10_000_000:
                interest["size_class"] = "broad"
            elif upper > 1_000_000:
                interest["size_class"] = "medium"
            elif upper > 100_000:
                interest["size_class"] = "narrow"
            elif upper > 0:
                interest["size_class"] = "very_narrow"
            else:
                interest["size_class"] = "unknown"

        return {
            "query": query,
            "total": len(interests),
            "interests": interests,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def search_behaviors(
    query: Optional[str] = None,
    limit: int = 30,
) -> dict:
    """
    Search or list behavior-based targeting options.

    If query is provided, filters by keyword. Otherwise returns all behaviors.

    Args:
        query: Optional search term (e.g., 'travel', 'small business').
        limit: Max results (default 30).
    """
    api_client._ensure_initialized()

    params: dict[str, str] = {
        "type": "adTargetingCategory",
        "class": "behaviors",
        "limit": str(min(limit, 100)),
    }

    try:
        result = api_client.graph_get("/search", params=params)
        behaviors = result.get("data", [])

        # Filter by query if provided
        if query:
            query_lower = query.lower()
            behaviors = [
                b for b in behaviors
                if query_lower in b.get("name", "").lower()
                or query_lower in str(b.get("path", [])).lower()
                or query_lower in (b.get("description", "") or "").lower()
            ]

        # Enrich
        for b in behaviors:
            lower = b.get("audience_size_lower_bound", 0) or 0
            upper = b.get("audience_size_upper_bound", 0) or 0
            b["audience_size_display"] = _format_audience_size(lower, upper)
            category = b.get("path", [])
            b["category"] = category[0] if category else "Uncategorized"

        return {
            "query": query,
            "total": len(behaviors),
            "behaviors": behaviors,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def search_geo_locations(
    query: str,
    location_type: str = "country",
    limit: int = 10,
) -> dict:
    """
    Search geographic locations for ad targeting.

    Args:
        query: Location search term (e.g., 'Greece', 'Athens', 'Crete').
        location_type: Type of location: 'country', 'region', 'city', 'zip',
            'geo_market', 'electoral_district'. Default 'country'.
        limit: Max results (default 10).
    """
    api_client._ensure_initialized()

    valid_types = ["country", "region", "city", "zip", "geo_market", "electoral_district"]
    if location_type not in valid_types:
        return {"error": f"Invalid location_type: '{location_type}'. Valid: {', '.join(valid_types)}"}

    try:
        result = api_client.graph_get(
            "/search",
            params={
                "type": "adgeolocation",
                "q": query,
                "location_types": f'["{location_type}"]',
                "limit": str(min(limit, 25)),
            },
        )

        locations = result.get("data", [])

        # Enrich with geo hierarchy
        for loc in locations:
            parts = []
            if loc.get("name"):
                parts.append(loc["name"])
            if loc.get("region"):
                parts.append(loc["region"])
            if loc.get("country_name"):
                parts.append(loc["country_name"])
            elif loc.get("country_code"):
                parts.append(loc["country_code"])
            loc["full_path"] = " > ".join(parts)

            # For countries, add the targeting key format
            if location_type == "country" and loc.get("country_code"):
                loc["targeting_key"] = loc["country_code"]
            elif loc.get("key"):
                loc["targeting_key"] = loc["key"]

        return {
            "query": query,
            "location_type": location_type,
            "total": len(locations),
            "locations": locations,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


# --- Wave 1.1: Targeting Parity ---


@mcp.tool()
def get_interest_suggestions(
    interest_list: str,
    limit: int = 20,
) -> dict:
    """
    Get related interest suggestions from seed interests.

    Accepts a comma-separated list of interest IDs or names and returns
    Meta's suggested related interests for targeting expansion.

    Args:
        interest_list: Comma-separated interest IDs (numeric) or interest names.
            Example IDs: '6003139266461,6003017845981'
            Example names: 'yoga,meditation'
        limit: Max suggestions to return (default 20).
    """
    items = [item.strip() for item in interest_list.split(",") if item.strip()]
    if not items:
        return {
            "error": "interest_list is empty. Provide comma-separated interest IDs or names.",
            "blocked_at": "input_validation",
        }

    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            "/search",
            params={
                "type": "adinterestsuggestion",
                "interest_list": _json.dumps(items),
                "limit": str(min(limit, 50)),
            },
        )

        suggestions = result.get("data", [])

        for s in suggestions:
            lower = s.get("audience_size_lower_bound", 0) or 0
            upper = s.get("audience_size_upper_bound", 0) or 0
            s["audience_size_display"] = _format_audience_size(lower, upper)
            s["audience_size_lower_bound"] = lower
            s["audience_size_upper_bound"] = upper

        return {
            "seed_interests": items,
            "total": len(suggestions),
            "suggestions": suggestions,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def search_demographics(
    query: Optional[str] = None,
    limit: int = 30,
) -> dict:
    """
    Search or list demographic targeting options.

    Returns demographic categories: life events, education, work,
    financial, relationship, home ownership, parental status, etc.

    If query is provided, filters by keyword. Otherwise returns all demographics.

    Args:
        query: Optional search term (e.g., 'homeowner', 'new job', 'university').
        limit: Max results (default 30).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            "/search",
            params={
                "type": "adTargetingCategory",
                "class": "demographics",
                "limit": str(min(limit, 100)),
            },
        )

        demographics = result.get("data", [])

        if query:
            query_lower = query.lower()
            demographics = [
                d for d in demographics
                if query_lower in d.get("name", "").lower()
                or query_lower in str(d.get("path", [])).lower()
                or query_lower in (d.get("description", "") or "").lower()
            ]

        for d in demographics:
            lower = d.get("audience_size_lower_bound", 0) or 0
            upper = d.get("audience_size_upper_bound", 0) or 0
            d["audience_size_display"] = _format_audience_size(lower, upper)
            category = d.get("path", [])
            d["category"] = category[0] if category else "Uncategorized"

        return {
            "query": query,
            "total": len(demographics),
            "demographics": demographics,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def estimate_audience_size(
    account_id: str,
    targeting_json: str,
) -> dict:
    """
    Estimate audience reach for a targeting specification.

    Returns estimated daily reach (lower/upper bounds) for the given
    targeting spec on the specified account.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        targeting_json: JSON string of targeting spec.
            Example: '{"geo_locations":{"countries":["GR"]},"age_min":25,"age_max":55}'
    """
    account_id = ensure_account_id_format(account_id)

    try:
        targeting = _json.loads(targeting_json)
        if not isinstance(targeting, dict):
            return {
                "error": "targeting_json must parse to a JSON object.",
                "blocked_at": "input_validation",
            }
    except _json.JSONDecodeError as e:
        return {
            "error": f"Malformed targeting_json: {e}",
            "blocked_at": "input_validation",
        }

    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{account_id}/reachestimate",
            params={
                "targeting_spec": _json.dumps(targeting),
            },
        )

        data = result.get("data", {})
        users_lower = data.get("users_lower_bound", 0) or 0
        users_upper = data.get("users_upper_bound", 0) or 0

        return {
            "account_id": account_id,
            "targeting_spec": targeting,
            "estimate": {
                "users_lower_bound": users_lower,
                "users_upper_bound": users_upper,
                "users_display": _format_audience_size(users_lower, users_upper),
            },
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise
