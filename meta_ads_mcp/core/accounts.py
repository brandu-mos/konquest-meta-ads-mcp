"""
Ad Account management tools.

Provides read-only tools for listing and inspecting ad accounts,
pages, and Instagram identities associated with your business.

Phase: v1.0 (Foundation)
"""
import logging
from typing import Optional

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.exceptions import FacebookRequestError

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.auth import verify_token_and_permissions, get_business_id

logger = logging.getLogger("meta-ads-mcp.accounts")


@mcp.tool()
def check_token_status() -> dict:
    """
    Check Meta API token health, permissions, and rate limit status.

    Returns token validity, granted permissions, missing permissions,
    and current rate limit usage percentage.
    """
    return verify_token_and_permissions()


@mcp.tool()
def get_ad_accounts(limit: int = 50) -> dict:
    """
    List all ad accounts accessible to the authenticated user.

    Returns account IDs, names, statuses, currencies, and timezones
    for all accounts in your business portfolio.

    Args:
        limit: Maximum number of accounts to return (default 50).
    """
    api_client._ensure_initialized()

    try:
        business_id = get_business_id()
        if business_id:
            # Get accounts via business manager (preferred for agency setup)
            result = api_client.graph_get(
                f"/{business_id}/owned_ad_accounts",
                fields=[
                    "id", "name", "account_status", "currency",
                    "timezone_name", "amount_spent", "balance",
                    "business", "funding_source_details",
                ],
                params={"limit": str(limit)},
            )
        else:
            # Fallback: get accounts via user
            result = api_client.graph_get(
                "/me/adaccounts",
                fields=[
                    "id", "name", "account_status", "currency",
                    "timezone_name", "amount_spent", "balance",
                ],
                params={"limit": str(limit)},
            )

        accounts = result.get("data", [])

        # Map account_status codes to human-readable values
        status_map = {
            1: "ACTIVE",
            2: "DISABLED",
            3: "UNSETTLED",
            7: "PENDING_RISK_REVIEW",
            8: "PENDING_SETTLEMENT",
            9: "IN_GRACE_PERIOD",
            100: "PENDING_CLOSURE",
            101: "CLOSED",
            201: "ANY_ACTIVE",
            202: "ANY_CLOSED",
        }

        for account in accounts:
            status_code = account.get("account_status")
            account["account_status_name"] = status_map.get(status_code, f"UNKNOWN ({status_code})")

        return {
            "total": len(accounts),
            "accounts": accounts,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except FacebookRequestError as e:
        raise api_client.handle_sdk_error(e)


@mcp.tool()
def get_account_info(account_id: str) -> dict:
    """
    Get detailed information about a specific ad account.

    Returns account configuration, status, spend data, pixel info,
    and connected assets.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
    """
    api_client._ensure_initialized()

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    try:
        result = api_client.graph_get(
            f"/{account_id}",
            fields=[
                "id", "name", "account_status", "currency", "timezone_name",
                "amount_spent", "balance", "spend_cap", "min_daily_budget",
                "business", "funding_source_details", "owner",
                "disable_reason", "created_time",
                "is_prepay_account", "business_country_code",
            ],
        )

        # Also get connected pixels
        try:
            pixels = api_client.graph_get(
                f"/{account_id}/adspixels",
                fields=["id", "name", "is_unavailable", "last_fired_time"],
            )
            result["pixels"] = pixels.get("data", [])
        except MetaAPIError:
            result["pixels"] = []

        # Get connected Instagram accounts
        try:
            ig_accounts = api_client.graph_get(
                f"/{account_id}/instagram_accounts",
                fields=["id", "username", "profile_pic", "followers_count"],
            )
            result["instagram_accounts"] = ig_accounts.get("data", [])
        except MetaAPIError:
            result["instagram_accounts"] = []

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except FacebookRequestError as e:
        raise api_client.handle_sdk_error(e)


@mcp.tool()
def get_account_pages(account_id: str) -> dict:
    """
    List Facebook Pages available for ads on a specific ad account.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
    """
    api_client._ensure_initialized()

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    try:
        result = api_client.graph_get(
            f"/{account_id}/promote_pages",
            fields=["id", "name", "link", "fan_count", "verification_status",
                     "instagram_business_account"],
        )

        pages = result.get("data", [])
        return {
            "total": len(pages),
            "pages": pages,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except FacebookRequestError as e:
        raise api_client.handle_sdk_error(e)


@mcp.tool()
def get_instagram_identities(account_id: str) -> dict:
    """
    List Instagram accounts available for ads on a specific ad account.

    Returns instagram_user_id (the canonical identifier) for each account.
    This is the first step in the Instagram identity resolution ladder.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
    """
    api_client._ensure_initialized()

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    try:
        # Primary: ad account Instagram accounts
        result = api_client.graph_get(
            f"/{account_id}/instagram_accounts",
            fields=["id", "username", "profile_pic", "followers_count",
                     "ig_id", "biography"],
        )

        accounts = result.get("data", [])

        # Normalize: ensure instagram_user_id is the canonical field
        for acct in accounts:
            acct["instagram_user_id"] = acct.get("id")

        return {
            "total": len(accounts),
            "instagram_accounts": accounts,
            "resolution_method": "api_direct",
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except FacebookRequestError as e:
        raise api_client.handle_sdk_error(e)


@mcp.tool()
def discover_all_accounts() -> dict:
    """
    Discover all ad accounts, their pages, pixels, and Instagram accounts.

    Used to generate or update the account registry (config/accounts.yaml).
    Returns a comprehensive mapping of all accessible assets.
    """
    api_client._ensure_initialized()

    # Get all accounts
    accounts_result = get_ad_accounts(limit=100)
    accounts = accounts_result.get("accounts", [])

    registry = []
    for account in accounts:
        account_id = account.get("id")
        if not account_id:
            continue

        entry = {
            "account_id": account_id,
            "name": account.get("name", ""),
            "status": account.get("account_status_name", ""),
            "currency": account.get("currency", ""),
            "timezone": account.get("timezone_name", ""),
        }

        # Get pages for this account
        try:
            pages = get_account_pages(account_id)
            entry["pages"] = [
                {"page_id": p.get("id"), "name": p.get("name")}
                for p in pages.get("pages", [])
            ]
        except Exception:
            entry["pages"] = []

        # Get Instagram identities
        try:
            ig = get_instagram_identities(account_id)
            entry["instagram_accounts"] = [
                {"instagram_user_id": a.get("instagram_user_id"), "username": a.get("username")}
                for a in ig.get("instagram_accounts", [])
            ]
        except Exception:
            entry["instagram_accounts"] = []

        # Get pixels
        try:
            info = api_client.graph_get(
                f"/{account_id}/adspixels",
                fields=["id", "name", "last_fired_time"],
            )
            entry["pixels"] = [
                {"pixel_id": p.get("id"), "name": p.get("name")}
                for p in info.get("data", [])
            ]
        except Exception:
            entry["pixels"] = []

        registry.append(entry)

    return {
        "total_accounts": len(registry),
        "registry": registry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
