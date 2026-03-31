"""
Rate limit monitoring and write gating.

Reads live rate limit state from the API client's RateLimitStatus
(which parses x-app-usage, x-business-use-case-usage, x-ad-account-usage
headers on every API call).

Provides a gate function for write corridors to check before execution.

States:
  healthy   (0-59%)   -> allow all
  elevated  (60-79%)  -> allow with warning
  critical  (80-94%)  -> block non-essential writes, allow reads
  blocked   (95%+)    -> block all writes
"""
import logging
from typing import Optional

logger = logging.getLogger("meta-ads-mcp.safety.rate_limiter")

# Thresholds (percentage of rate limit consumed)
HEALTHY_MAX = 60
ELEVATED_MAX = 80
CRITICAL_MAX = 95
# Above CRITICAL_MAX = blocked


def get_rate_state(account_id: Optional[str] = None) -> dict:
    """
    Get current rate limit state from the API client.

    Returns:
        {
            "state": "healthy" | "elevated" | "critical" | "blocked",
            "usage_pct": float,
            "app_usage": dict,
            "ad_account_usage": dict,
            "allow_writes": bool,
            "allow_reads": bool,
            "warning": str or None,
        }
    """
    from meta_ads_mcp.core.api import api_client

    rl = api_client.rate_limits
    pct = rl.max_usage_pct

    if pct < HEALTHY_MAX:
        state = "healthy"
        allow_writes = True
        warning = None
    elif pct < ELEVATED_MAX:
        state = "elevated"
        allow_writes = True
        warning = f"Rate limit usage at {pct:.1f}% - elevated but within safe range"
    elif pct < CRITICAL_MAX:
        state = "critical"
        allow_writes = False
        warning = f"Rate limit usage at {pct:.1f}% - CRITICAL. Write operations blocked until usage drops."
    else:
        state = "blocked"
        allow_writes = False
        warning = f"Rate limit usage at {pct:.1f}% - BLOCKED. All write operations suspended."

    return {
        "state": state,
        "usage_pct": round(pct, 1),
        "app_usage": rl.app_usage,
        "ad_account_usage": rl.ad_account_usage,
        "business_usage": rl.business_usage,
        "estimated_time_to_regain_access_minutes": rl.estimated_time_to_regain_access_minutes,
        "allow_writes": allow_writes,
        "allow_reads": True,  # reads always allowed
        "warning": warning,
    }


def enforce_rate_gate(account_id: str, operation_type: str = "write") -> dict:
    """
    Hard gate for write corridors. Call before any API write.

    Args:
        account_id: Ad account ID.
        operation_type: "write" (campaigns/adsets/ads) or "read" (insights/lists).

    Returns:
        {
            "allowed": bool,
            "state": str,
            "usage_pct": float,
            "block_reason": str or None,
        }
    """
    state = get_rate_state(account_id)

    if operation_type == "read":
        return {
            "allowed": True,
            "state": state["state"],
            "usage_pct": state["usage_pct"],
            "block_reason": None,
        }

    if state["allow_writes"]:
        if state["warning"]:
            logger.warning(state["warning"])
        return {
            "allowed": True,
            "state": state["state"],
            "usage_pct": state["usage_pct"],
            "block_reason": None,
            "warning": state["warning"],
        }

    # Block writes
    logger.error(f"Rate limit gate BLOCKED write for {account_id}: {state['warning']}")
    return {
        "allowed": False,
        "state": state["state"],
        "usage_pct": state["usage_pct"],
        "block_reason": state["warning"],
    }
