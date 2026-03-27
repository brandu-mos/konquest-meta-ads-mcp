"""
Audience management and diagnostic tools.

Lists custom audiences with type classification, size estimation,
delivery status, and diagnostic warnings for unusable, stale,
too-small, or too-broad audiences.

Phase: v1.1 (Read) / v1.3 (Write)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.audiences")

# Audience subtype classification
SUBTYPE_LABELS = {
    "CUSTOM": "Custom (manual upload)",
    "WEBSITE": "Website visitors (pixel-based)",
    "APP": "App activity",
    "OFFLINE": "Offline activity",
    "ENGAGEMENT": "Engagement (video/page/ad)",
    "IG_BUSINESS": "Instagram engagers",
    "LOOKALIKE": "Lookalike",
    "DATA_SET": "Dataset-based",
    "BAG_OF_ACCOUNTS": "Account list",
    "STORE_VISIT": "Store visitors",
    "FOX": "Facebook offline",
    "CLAIM": "Claimed",
    "PARTNER": "Partner data",
    "MANAGED": "Managed",
    "VIDEO": "Video viewers",
    "SHOPPING": "Shopping activity",
}

# Size thresholds for diagnostics
MIN_AUDIENCE_SIZE = 100  # Below this, Meta may not deliver
SMALL_AUDIENCE_THRESHOLD = 1000
LARGE_AUDIENCE_THRESHOLD = 10_000_000

# Delivery status codes
DELIVERY_STATUS_MAP = {
    200: "ready",
    300: "too_small",
    400: "error",
    500: "expired",
}


def _classify_audience_health(audience: dict) -> dict:
    """Classify audience health and generate warnings."""
    warnings = []

    subtype = audience.get("subtype", "CUSTOM")
    lower = audience.get("approximate_count_lower_bound", 0) or 0
    upper = audience.get("approximate_count_upper_bound", 0) or 0
    delivery = audience.get("delivery_status", {})
    delivery_code = delivery.get("code", 0) if isinstance(delivery, dict) else 0
    delivery_desc = delivery.get("description", "") if isinstance(delivery, dict) else ""
    time_updated = audience.get("time_updated")

    # Size classification
    if upper == 0 and lower == 0:
        size_class = "empty"
        warnings.append({
            "severity": "HIGH",
            "message": "Audience is empty (0 members)",
            "fix": "Check source data. For website audiences, verify pixel is firing. For lookalikes, verify source audience.",
        })
    elif upper < MIN_AUDIENCE_SIZE:
        size_class = "too_small"
        warnings.append({
            "severity": "HIGH",
            "message": f"Audience too small ({lower}-{upper} members). Meta may not deliver ads to this audience.",
            "fix": "Expand audience window (e.g., 30d -> 90d) or broaden source criteria.",
        })
    elif upper < SMALL_AUDIENCE_THRESHOLD:
        size_class = "small"
        warnings.append({
            "severity": "MEDIUM",
            "message": f"Audience is small ({lower}-{upper} members). May limit delivery and increase costs.",
            "fix": "Consider expanding the window or combining with other audiences.",
        })
    elif lower > LARGE_AUDIENCE_THRESHOLD:
        size_class = "very_large"
        warnings.append({
            "severity": "LOW",
            "message": f"Audience is very large ({lower:,}-{upper:,} members). May be too broad for targeted campaigns.",
            "fix": "Consider narrowing with additional targeting or using as a lookalike source instead.",
        })
    else:
        size_class = "healthy"

    # Delivery status
    if delivery_code == 300:
        warnings.append({
            "severity": "HIGH",
            "message": f"Delivery status: too small. {delivery_desc}",
            "fix": "Expand audience criteria or wait for more data.",
        })
    elif delivery_code == 400:
        warnings.append({
            "severity": "CRITICAL",
            "message": f"Delivery status: error. {delivery_desc}",
            "fix": "Check audience configuration in Ads Manager.",
        })
    elif delivery_code == 500:
        warnings.append({
            "severity": "HIGH",
            "message": f"Delivery status: expired. {delivery_desc}",
            "fix": "Re-create the audience or update the data source.",
        })

    # Staleness check
    if time_updated:
        try:
            updated_ts = int(time_updated)
            updated_dt = datetime.fromtimestamp(updated_ts, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            days_since = (now - updated_dt).days
            if days_since > 90:
                warnings.append({
                    "severity": "MEDIUM",
                    "message": f"Audience last updated {days_since} days ago. May be stale.",
                    "fix": "Verify the data source is still active. Pixel/engagement audiences refresh automatically if the source is live.",
                })
        except (ValueError, TypeError, OSError):
            pass

    # Website audience with very low count = pixel issue
    if subtype == "WEBSITE" and upper < 100 and upper > 0:
        warnings.append({
            "severity": "HIGH",
            "message": f"Website audience has only {lower}-{upper} members. Pixel may not be firing correctly.",
            "fix": "Run pixel diagnostics. Check that the pixel is installed and firing on all relevant pages.",
        })

    usable = delivery_code == 200 and size_class not in ("empty", "too_small")

    return {
        "size_class": size_class,
        "usable": usable,
        "delivery_status": DELIVERY_STATUS_MAP.get(delivery_code, f"unknown_{delivery_code}"),
        "warnings": warnings,
    }


@mcp.tool()
def list_custom_audiences(
    account_id: str,
    limit: int = 50,
) -> dict:
    """
    List custom audiences for an ad account with type classification,
    size estimates, delivery status, and diagnostic warnings.

    Flags audiences that are unusable, too small, too broad, stale, or errored.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        limit: Max audiences to return (default 50).
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    try:
        result = api_client.graph_get(
            f"/{account_id}/customaudiences",
            fields=[
                "id", "name", "subtype", "description",
                "approximate_count_lower_bound", "approximate_count_upper_bound",
                "delivery_status", "operation_status",
                "time_created", "time_updated",
                "data_source", "lookalike_spec",
            ],
            params={"limit": str(min(limit, 100))},
        )

        audiences = result.get("data", [])

        # Paginate
        all_audiences = list(audiences)
        paging = result.get("paging", {})
        while paging.get("next") and len(all_audiences) < 200:
            after = paging.get("cursors", {}).get("after")
            if not after:
                break
            result = api_client.graph_get(
                f"/{account_id}/customaudiences",
                fields=[
                    "id", "name", "subtype", "description",
                    "approximate_count_lower_bound", "approximate_count_upper_bound",
                    "delivery_status", "operation_status",
                    "time_created", "time_updated",
                    "data_source", "lookalike_spec",
                ],
                params={"limit": str(min(limit, 100)), "after": after},
            )
            next_batch = result.get("data", [])
            if not next_batch:
                break
            all_audiences.extend(next_batch)
            paging = result.get("paging", {})

        # Enrich each audience with diagnostics
        subtype_counts: dict[str, int] = {}
        total_warnings = 0
        unusable_count = 0

        for aud in all_audiences:
            subtype = aud.get("subtype", "CUSTOM")
            aud["subtype_label"] = SUBTYPE_LABELS.get(subtype, subtype)
            subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1

            health = _classify_audience_health(aud)
            aud["size_class"] = health["size_class"]
            aud["usable"] = health["usable"]
            aud["delivery_status_label"] = health["delivery_status"]
            aud["warnings"] = health["warnings"]
            total_warnings += len(health["warnings"])
            if not health["usable"]:
                unusable_count += 1

        return {
            "account_id": account_id,
            "total": len(all_audiences),
            "subtype_breakdown": subtype_counts,
            "unusable_count": unusable_count,
            "total_warnings": total_warnings,
            "audiences": all_audiences,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise
