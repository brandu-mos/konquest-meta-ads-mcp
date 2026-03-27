"""
Authentication and token management.

Handles token loading from environment, health checks, and
permission verification for the Meta Ads system.
"""
import logging
import os
from typing import Optional

from meta_ads_mcp.core.api import api_client, MetaAPIError

logger = logging.getLogger("meta-ads-mcp.auth")


def get_access_token() -> str:
    """Get the Meta access token from environment."""
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise MetaAPIError("META_ACCESS_TOKEN not set in environment", error_code=-1)
    return token


def verify_token_and_permissions() -> dict:
    """
    Verify token is valid and has required permissions.

    Returns dict with:
    - status: valid | expired | insufficient_permissions | error
    - permissions: list of granted permissions
    - missing_permissions: list of required but missing permissions
    """
    required_permissions = [
        "ads_management",
        "ads_read",
        "business_management",
        "pages_read_engagement",
    ]

    # Optional but useful permissions
    optional_permissions = [
        "catalog_management",
        "pages_manage_ads",
        "instagram_basic",
        "instagram_manage_comments",
    ]

    try:
        # Check token validity
        health = api_client.check_token_health()
        if health["status"] != "valid":
            return health

        # Check permissions
        perm_result = api_client.graph_get("/me/permissions")
        granted = set()
        for perm in perm_result.get("data", []):
            if perm.get("status") == "granted":
                granted.add(perm.get("permission"))

        missing_required = [p for p in required_permissions if p not in granted]
        missing_optional = [p for p in optional_permissions if p not in granted]

        if missing_required:
            return {
                "status": "insufficient_permissions",
                "granted": sorted(granted),
                "missing_required": missing_required,
                "missing_optional": missing_optional,
            }

        return {
            "status": "valid",
            "user_id": health.get("user_id"),
            "user_name": health.get("user_name"),
            "granted_permissions": sorted(granted),
            "missing_optional": missing_optional,
            "rate_limit_usage_pct": health.get("rate_limit_usage_pct", 0),
        }

    except MetaAPIError as e:
        return {"status": "error", "error": str(e), "error_code": e.error_code}


def get_business_id() -> Optional[str]:
    """Get the primary business ID for the authenticated user."""
    try:
        result = api_client.graph_get("/me/businesses", fields=["id", "name"])
        businesses = result.get("data", [])
        if businesses:
            return businesses[0].get("id")
        return None
    except MetaAPIError:
        return None
