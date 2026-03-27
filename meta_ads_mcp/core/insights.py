"""
Performance insights tools.

Provides comprehensive performance data with breakdown dimensions,
time range presets, attribution windows, compact mode, and
objective-aware metric normalization.

Phase: v1.1 (Read Operations) + Gap Closure (Bulk Insights)
"""
import json
import logging
from typing import Any, Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format, parse_date_range

logger = logging.getLogger("meta-ads-mcp.insights")

# --- Metric definitions ---

# Core delivery metrics (always requested)
CORE_METRICS = [
    "spend", "impressions", "reach", "frequency",
    "clicks", "cpc", "cpm", "ctr",
    "actions", "action_values",
    "cost_per_action_type", "cost_per_unique_action_type",
    "conversions", "conversion_values", "cost_per_conversion",
    "website_purchase_roas",
]

# Extended metrics available on most objects
EXTENDED_METRICS = CORE_METRICS + [
    "unique_clicks", "unique_ctr", "cost_per_unique_click",
    "inline_link_clicks", "inline_link_click_ctr",
    "cost_per_inline_link_click",
    "outbound_clicks", "outbound_clicks_ctr",
    "cost_per_outbound_click",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "video_avg_time_watched_actions",
    "quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking",
]

# Action types we extract from the actions array
# Keyed by archetype for objective-aware extraction
ACTION_TYPES_BY_ARCHETYPE = {
    "ecommerce": [
        "purchase", "omni_purchase",
        "add_to_cart", "omni_add_to_cart",
        "initiate_checkout", "omni_initiated_checkout",
        "view_content", "omni_view_content",
        "landing_page_view", "omni_landing_page_view",
        "link_click",
        "video_view",
    ],
    "lead_gen": [
        "lead", "onsite_conversion.lead_grouped",
        "offsite_conversion.fb_pixel_lead",
        "landing_page_view", "omni_landing_page_view",
        "link_click",
        "video_view",
    ],
    "awareness": [
        "video_view", "post_engagement",
        "link_click", "landing_page_view",
        "page_engagement",
    ],
    "traffic": [
        "link_click", "landing_page_view", "omni_landing_page_view",
        "view_content", "omni_view_content",
        "video_view",
    ],
    "hybrid": [
        "purchase", "omni_purchase",
        "lead", "onsite_conversion.lead_grouped",
        "add_to_cart", "omni_add_to_cart",
        "initiate_checkout",
        "landing_page_view", "omni_landing_page_view",
        "link_click", "video_view",
        "post_engagement",
    ],
    "messages": [
        "onsite_conversion.messaging_first_reply",
        "link_click", "landing_page_view",
        "video_view",
    ],
}

# Breakdown dimensions supported by Meta API
VALID_BREAKDOWNS = [
    "age", "gender", "country", "region", "dma",
    "impression_device", "platform_position", "publisher_platform",
    "device_platform", "product_id",
]

# Breakdown combinations that are NOT supported by Meta API
INVALID_BREAKDOWN_COMBOS = [
    {"age", "impression_device"},
    {"age", "platform_position"},
    {"age", "region"},
    {"country", "region"},
    {"country", "dma"},
    {"region", "dma"},
]

# Time presets that map directly to Meta date_preset parameter
META_DATE_PRESETS = [
    "today", "yesterday", "this_month", "last_month",
    "this_quarter", "last_3d", "last_7d", "last_14d",
    "last_28d", "last_30d", "last_90d", "last_week_mon_sun",
    "last_week_sun_sat", "last_quarter", "last_year", "this_week_mon_today",
    "this_week_sun_today", "this_year", "maximum",
]


def _extract_action_value(actions: list[dict], action_type: str) -> Optional[str]:
    """Extract a specific action type value from the actions array."""
    if not actions:
        return None
    for action in actions:
        if action.get("action_type") == action_type:
            return action.get("value")
    return None


def _extract_action_cost(cost_per_action: list[dict], action_type: str) -> Optional[str]:
    """Extract cost per action for a specific type."""
    if not cost_per_action:
        return None
    for item in cost_per_action:
        if item.get("action_type") == action_type:
            return item.get("value")
    return None


def _extract_roas(action_values: list[dict]) -> Optional[str]:
    """Extract purchase ROAS from action_values."""
    if not action_values:
        return None
    for item in action_values:
        if item.get("action_type") in ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"):
            return item.get("value")
    return None


def _normalize_metrics(row: dict, archetype: str = "hybrid") -> dict:
    """
    Normalize a single insights row into a consistent metric structure.

    Extracts action-type values into top-level keys based on archetype.
    """
    actions = row.get("actions", [])
    cost_per_action = row.get("cost_per_action_type", [])
    action_values = row.get("action_values", [])
    roas_list = row.get("website_purchase_roas", [])

    normalized = {
        # Delivery
        "spend": row.get("spend"),
        "impressions": row.get("impressions"),
        "reach": row.get("reach"),
        "frequency": row.get("frequency"),
        # Clicks
        "clicks": row.get("clicks"),
        "cpc": row.get("cpc"),
        "cpm": row.get("cpm"),
        "ctr": row.get("ctr"),
        # Rankings
        "quality_ranking": row.get("quality_ranking"),
        "engagement_rate_ranking": row.get("engagement_rate_ranking"),
        "conversion_rate_ranking": row.get("conversion_rate_ranking"),
        # Date range
        "date_start": row.get("date_start"),
        "date_stop": row.get("date_stop"),
    }

    # Breakdowns (pass through if present)
    for bd in VALID_BREAKDOWNS:
        if bd in row:
            normalized[bd] = row[bd]

    # Level-specific IDs (pass through for campaign/adset/ad level queries)
    for level_field in ["campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name"]:
        if level_field in row:
            normalized[level_field] = row[level_field]

    # Extract action values based on archetype priority
    priority_types = ACTION_TYPES_BY_ARCHETYPE.get(archetype, ACTION_TYPES_BY_ARCHETYPE["hybrid"])

    for action_type in priority_types:
        key = action_type.replace(".", "_").replace("omni_", "")
        val = _extract_action_value(actions, action_type)
        if val is not None:
            normalized[key] = val

    # Standardized higher-level keys
    # Purchases
    purchases = _extract_action_value(actions, "omni_purchase") or _extract_action_value(actions, "purchase")
    if purchases:
        normalized["purchases"] = purchases
        cpa = _extract_action_cost(cost_per_action, "omni_purchase") or _extract_action_cost(cost_per_action, "purchase")
        if cpa:
            normalized["cpa_purchase"] = cpa

    # Leads
    leads = (_extract_action_value(actions, "lead")
             or _extract_action_value(actions, "onsite_conversion.lead_grouped")
             or _extract_action_value(actions, "offsite_conversion.fb_pixel_lead"))
    if leads:
        normalized["leads"] = leads
        cpl = (_extract_action_cost(cost_per_action, "lead")
               or _extract_action_cost(cost_per_action, "onsite_conversion.lead_grouped")
               or _extract_action_cost(cost_per_action, "offsite_conversion.fb_pixel_lead"))
        if cpl:
            normalized["cpl"] = cpl

    # Add to cart
    atc = _extract_action_value(actions, "omni_add_to_cart") or _extract_action_value(actions, "add_to_cart")
    if atc:
        normalized["add_to_cart"] = atc

    # Initiate checkout
    ic = (_extract_action_value(actions, "omni_initiated_checkout")
          or _extract_action_value(actions, "initiate_checkout"))
    if ic:
        normalized["initiate_checkout"] = ic

    # Landing page views
    lpv = (_extract_action_value(actions, "omni_landing_page_view")
           or _extract_action_value(actions, "landing_page_view"))
    if lpv:
        normalized["landing_page_views"] = lpv

    # Video views
    vv = _extract_action_value(actions, "video_view")
    if vv:
        normalized["video_views"] = vv

    # ROAS
    if roas_list:
        for r in roas_list:
            if r.get("action_type") in ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"):
                normalized["roas"] = r.get("value")
                break
    # Fallback: compute ROAS from action_values
    if "roas" not in normalized and purchases and normalized.get("spend"):
        purchase_value = _extract_roas(action_values)
        spend = float(normalized["spend"]) if normalized["spend"] else 0
        if purchase_value and spend > 0:
            normalized["roas"] = f"{float(purchase_value) / spend:.2f}"

    # Revenue
    purchase_revenue = _extract_roas(action_values)
    if purchase_revenue:
        normalized["revenue"] = purchase_revenue

    return normalized


def _build_compact_summary(normalized: dict, archetype: str = "hybrid") -> dict:
    """
    Build a compact operator-friendly summary for WhatsApp/reporting.

    Returns only the metrics that matter for the archetype, formatted for display.
    """
    summary = {
        "spend": normalized.get("spend"),
        "impressions": normalized.get("impressions"),
        "reach": normalized.get("reach"),
        "clicks": normalized.get("clicks"),
        "ctr": normalized.get("ctr"),
        "cpc": normalized.get("cpc"),
        "cpm": normalized.get("cpm"),
        "date_range": f"{normalized.get('date_start', '?')} to {normalized.get('date_stop', '?')}",
    }

    if archetype == "ecommerce":
        summary["purchases"] = normalized.get("purchases")
        summary["cpa_purchase"] = normalized.get("cpa_purchase")
        summary["roas"] = normalized.get("roas")
        summary["revenue"] = normalized.get("revenue")
        summary["add_to_cart"] = normalized.get("add_to_cart")
        summary["initiate_checkout"] = normalized.get("initiate_checkout")
        summary["landing_page_views"] = normalized.get("landing_page_views")

    elif archetype == "lead_gen":
        summary["leads"] = normalized.get("leads")
        summary["cpl"] = normalized.get("cpl")
        summary["landing_page_views"] = normalized.get("landing_page_views")

    elif archetype == "awareness":
        summary["video_views"] = normalized.get("video_views")
        summary["frequency"] = normalized.get("frequency")

    elif archetype == "traffic":
        summary["landing_page_views"] = normalized.get("landing_page_views")
        summary["video_views"] = normalized.get("video_views")

    else:  # hybrid or messages
        summary["purchases"] = normalized.get("purchases")
        summary["leads"] = normalized.get("leads")
        summary["roas"] = normalized.get("roas")
        summary["revenue"] = normalized.get("revenue")
        summary["cpa_purchase"] = normalized.get("cpa_purchase")
        summary["cpl"] = normalized.get("cpl")
        summary["landing_page_views"] = normalized.get("landing_page_views")
        summary["video_views"] = normalized.get("video_views")

    # Strip None values for cleaner output
    return {k: v for k, v in summary.items() if v is not None}


def _validate_breakdowns(breakdowns: list[str]) -> tuple[bool, str]:
    """Validate breakdown combination is supported."""
    for bd in breakdowns:
        if bd not in VALID_BREAKDOWNS:
            return False, f"Unknown breakdown: '{bd}'. Valid: {', '.join(VALID_BREAKDOWNS)}"
    bd_set = set(breakdowns)
    for invalid_combo in INVALID_BREAKDOWN_COMBOS:
        if invalid_combo.issubset(bd_set):
            return False, f"Unsupported breakdown combination: {invalid_combo}"
    return True, ""


@mcp.tool()
def get_insights(
    object_id: str,
    time_range: str = "last_7d",
    breakdowns: Optional[str] = None,
    level: Optional[str] = None,
    archetype: str = "hybrid",
    compact: bool = True,
    limit: int = 50,
) -> dict:
    """
    Get performance insights for any Meta Ads object (account, campaign, ad set, or ad).

    Returns normalized metrics with objective-aware extraction: purchases/ROAS for ecommerce,
    leads/CPL for lead_gen, reach/frequency for awareness.

    Args:
        object_id: Account ID (act_XXX), campaign ID, ad set ID, or ad ID.
        time_range: Date preset ('last_7d', 'last_30d', 'this_month', etc.)
            or explicit range 'YYYY-MM-DD,YYYY-MM-DD'.
        breakdowns: Comma-separated breakdown dimensions (e.g. 'age,gender').
            Supported: age, gender, country, region, impression_device,
            platform_position, publisher_platform, device_platform, product_id.
        level: Aggregation level when querying account/campaign: 'campaign', 'adset', 'ad'.
            Omit for object-level insights.
        archetype: Account archetype for metric selection: 'ecommerce', 'lead_gen',
            'awareness', 'traffic', 'hybrid', 'messages'. Default 'hybrid' (all metrics).
        compact: If true, return a compact operator-friendly summary alongside raw data.
        limit: Max rows for breakdown or level queries (default 50).
    """
    api_client._ensure_initialized()

    # Normalize account ID format
    if object_id.startswith("act_") or object_id.replace("_", "").isdigit():
        if object_id.startswith("act"):
            object_id = ensure_account_id_format(object_id)

    # Build params
    params: dict[str, str] = {"limit": str(min(limit, 200))}

    # Handle time range
    if "," in time_range:
        # Explicit date range: "YYYY-MM-DD,YYYY-MM-DD"
        start_date, end_date = parse_date_range(time_range)
        params["time_range"] = f'{{"since":"{start_date}","until":"{end_date}"}}'
    elif time_range in META_DATE_PRESETS:
        params["date_preset"] = time_range
    else:
        # Try our custom presets
        try:
            start_date, end_date = parse_date_range(time_range)
            params["time_range"] = f'{{"since":"{start_date}","until":"{end_date}"}}'
        except ValueError:
            return {"error": f"Unknown time_range: '{time_range}'", "valid_presets": META_DATE_PRESETS}

    # Handle breakdowns
    breakdown_list = []
    if breakdowns:
        breakdown_list = [b.strip() for b in breakdowns.split(",")]
        valid, error_msg = _validate_breakdowns(breakdown_list)
        if not valid:
            return {"error": error_msg}
        params["breakdowns"] = ",".join(breakdown_list)

    # Handle level (for account/campaign level queries)
    if level:
        valid_levels = ["account", "campaign", "adset", "ad"]
        if level not in valid_levels:
            return {"error": f"Invalid level: '{level}'. Valid: {', '.join(valid_levels)}"}
        params["level"] = level

    # Select fields - add level-specific ID fields
    fields = list(CORE_METRICS)
    if level == "campaign":
        fields.extend(["campaign_id", "campaign_name"])
    elif level == "adset":
        fields.extend(["adset_id", "adset_name", "campaign_id"])
    elif level == "ad":
        fields.extend(["ad_id", "ad_name", "adset_id", "campaign_id"])

    try:
        result = api_client.graph_get(
            f"/{object_id}/insights",
            fields=fields,
            params=params,
        )

        rows = result.get("data", [])

        if not rows:
            return {
                "total": 0,
                "data": [],
                "summary": None,
                "compact_summary": None,
                "message": "No data for the specified time range and filters.",
                "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
            }

        # Normalize all rows
        normalized_rows = [_normalize_metrics(row, archetype) for row in rows]

        # Build response
        response: dict[str, Any] = {
            "total": len(normalized_rows),
            "object_id": object_id,
            "time_range": time_range,
            "archetype": archetype,
            "data": normalized_rows,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

        if breakdowns:
            response["breakdowns"] = breakdown_list

        if level:
            response["level"] = level

        # Compact summary (for single-row results or aggregated)
        if compact and len(normalized_rows) == 1:
            response["compact_summary"] = _build_compact_summary(normalized_rows[0], archetype)
        elif compact and len(normalized_rows) > 1 and not breakdown_list and not level:
            # Multiple rows = time series, summarize first (most recent)
            response["compact_summary"] = _build_compact_summary(normalized_rows[0], archetype)

        return response

    except MetaAPIError as e:
        error_msg = str(e)
        # Classify common errors
        if "breakdowns" in error_msg.lower() or "not compatible" in error_msg.lower():
            return {
                "error": "Unsupported breakdown combination",
                "details": error_msg,
                "suggestion": "Try removing or changing breakdowns. Some combinations are not supported by Meta API.",
            }
        if "does not exist" in error_msg.lower() or "invalid" in error_msg.lower():
            return {
                "error": "Object not found or invalid ID",
                "details": error_msg,
            }
        raise


# --- Gap Closure: Bulk Cross-Account Insights ---

@mcp.tool()
def get_bulk_insights(
    time_range: str = "last_7d",
    level: str = "account",
    limit_accounts: int = 20,
) -> dict:
    """
    Get performance insights across all accessible ad accounts in one call.

    Aggregates spend, impressions, clicks, conversions, ROAS across accounts.
    Uses accounts from the Meta API (not accounts.yaml).

    Args:
        time_range: 'today', 'yesterday', 'last_3d', 'last_7d', 'last_14d', 'last_30d'.
        level: 'account' (one row per account). Campaign-level bulk is not supported.
        limit_accounts: Max accounts to query (default 20).
    """
    valid_ranges = {
        "today": {"since": "today", "until": "today"},
        "yesterday": {"since": "yesterday", "until": "yesterday"},
        "last_3d": {"since": "{3d_ago}", "until": "today"},
        "last_7d": {"since": "{7d_ago}", "until": "today"},
        "last_14d": {"since": "{14d_ago}", "until": "today"},
        "last_30d": {"since": "{30d_ago}", "until": "today"},
    }

    if time_range not in valid_ranges:
        return {
            "error": f"Invalid time_range: '{time_range}'. Valid: {list(valid_ranges.keys())}",
            "blocked_at": "input_validation",
        }

    if level != "account":
        return {
            "error": "Only level='account' is supported for bulk insights.",
            "blocked_at": "input_validation",
        }

    api_client._ensure_initialized()

    # Build date range
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    range_map = {
        "today": {"since": today, "until": today},
        "yesterday": {"since": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                       "until": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")},
        "last_3d": {"since": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"), "until": today},
        "last_7d": {"since": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"), "until": today},
        "last_14d": {"since": (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"), "until": today},
        "last_30d": {"since": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), "until": today},
    }
    date_range = range_map[time_range]

    # Get all accounts
    try:
        accounts_result = api_client.graph_get(
            "/me/adaccounts",
            fields=["id", "name", "account_status"],
            params={"limit": str(min(limit_accounts, 50))},
        )
        accounts = accounts_result.get("data", [])
    except MetaAPIError as e:
        return {"error": f"Cannot list accounts: {e}", "blocked_at": "account_list"}

    # Get insights per account
    account_insights = []
    totals = {"spend": 0.0, "impressions": 0, "clicks": 0, "reach": 0}
    errors = []

    for acct in accounts[:limit_accounts]:
        acct_id = acct.get("id", "")
        acct_name = acct.get("name", acct_id)
        try:
            ins = api_client.graph_get(
                f"/{acct_id}/insights",
                params={
                    "time_range": json.dumps(date_range),
                    "fields": "spend,impressions,clicks,reach,actions,action_values,cpc,cpm,ctr",
                    "level": "account",
                },
            )
            data = ins.get("data", [])
            if data:
                row = data[0]
                spend = float(row.get("spend", "0"))
                impressions = int(row.get("impressions", "0"))
                clicks = int(row.get("clicks", "0"))
                reach = int(row.get("reach", "0"))
                totals["spend"] += spend
                totals["impressions"] += impressions
                totals["clicks"] += clicks
                totals["reach"] += reach
                account_insights.append({
                    "account_id": acct_id,
                    "account_name": acct_name,
                    "spend": spend,
                    "impressions": impressions,
                    "clicks": clicks,
                    "reach": reach,
                    "cpc": row.get("cpc"),
                    "cpm": row.get("cpm"),
                    "ctr": row.get("ctr"),
                })
            else:
                account_insights.append({
                    "account_id": acct_id,
                    "account_name": acct_name,
                    "spend": 0,
                    "note": "No data for this period",
                })
        except MetaAPIError as e:
            errors.append({"account_id": acct_id, "error": str(e)})

    # Sort by spend descending
    account_insights.sort(key=lambda x: x.get("spend", 0), reverse=True)

    return {
        "time_range": time_range,
        "date_range": date_range,
        "accounts_queried": len(accounts),
        "accounts_with_data": len([a for a in account_insights if a.get("spend", 0) > 0]),
        "totals": totals,
        "accounts": account_insights,
        "errors": errors if errors else None,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
