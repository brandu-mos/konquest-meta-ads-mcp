"""
Campaign duplication tool (Phase F.1).

Duplicates a campaign and optionally its child ad sets into the same account.
All created objects are PAUSED. Does not duplicate ads or creatives.
Same-account only - cross-account duplication is blocked.
"""
import json as _json
import logging
from datetime import datetime
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format, currency_to_cents

logger = logging.getLogger("meta-ads-mcp.duplication")


def _apply_name_suffix(source_name: str, suffix: str) -> str:
    """Apply suffix to a name, respecting pipe-separated naming conventions.

    For pipe-separated names (e.g., "Objective | Product | Funnel | Model"),
    the suffix is inserted into the second segment (product) to preserve
    the naming convention structure.

    For non-pipe names, the suffix is appended to the end.
    """
    parts = [p.strip() for p in source_name.split("|")]
    if len(parts) >= 3:
        # Pipe-separated convention: insert suffix into product segment (index 1)
        parts[1] = f"{parts[1]}{suffix}"
        return " | ".join(parts)
    else:
        # Simple name: append to end
        return f"{source_name}{suffix}"


@mcp.tool()
def duplicate_campaign(
    campaign_id: str,
    account_id: str,
    name_suffix: str = " - Copy",
    include_adsets: bool = True,
    include_ads: bool = False,
    adset_budget_override: Optional[float] = None,
) -> dict:
    """
    Duplicate a campaign (and optionally its child ad sets and ads) within the same account.

    All created objects are PAUSED. When include_ads=True, ads are duplicated
    with their existing creative references (creatives are reused, not copied).

    Same-account only. Cross-account duplication is not supported.

    Args:
        campaign_id: Source campaign ID to duplicate.
        account_id: Ad account ID. Must match the source campaign's account.
        name_suffix: Appended to source names (default " - Copy").
            Must result in valid names per naming convention.
        include_adsets: Whether to duplicate child ad sets (default True).
        adset_budget_override: Override all duplicated ad set budgets (EUR).
            Only applies to ABO campaigns. If None, copies source budgets.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    account_id = ensure_account_id_format(account_id)

    # --- Step 0: Read source campaign ---
    api_client._ensure_initialized()
    try:
        source_campaign = api_client.graph_get(
            f"/{campaign_id}",
            fields=[
                "id", "name", "objective", "status", "effective_status",
                "daily_budget", "lifetime_budget", "bid_strategy",
                "special_ad_categories", "account_id",
            ],
        )
    except MetaAPIError as e:
        return {
            "error": f"Cannot read source campaign {campaign_id}: {e}",
            "blocked_at": "source_read",
        }

    # --- Step 1: Same-account enforcement ---
    source_account = source_campaign.get("account_id", "")
    if source_account and not source_account.startswith("act_"):
        source_account = f"act_{source_account}"

    if source_account and source_account != account_id:
        return {
            "error": f"Cross-account duplication is not supported. Source campaign belongs to {source_account}, but target account is {account_id}.",
            "blocked_at": "same_account_enforcement",
            "source_account": source_account,
            "target_account": account_id,
        }

    # --- Step 2: Determine budget model ---
    source_has_daily = source_campaign.get("daily_budget") and int(source_campaign.get("daily_budget", "0")) > 0
    source_has_lifetime = source_campaign.get("lifetime_budget") and int(source_campaign.get("lifetime_budget", "0")) > 0
    budget_model = "CBO" if (source_has_daily or source_has_lifetime) else "ABO"

    # --- Step 3: Build campaign create payload ---
    source_name = source_campaign.get("name", "")
    new_campaign_name = _apply_name_suffix(source_name, name_suffix)
    source_objective = source_campaign.get("objective", "")
    source_sac = source_campaign.get("special_ad_categories", [])

    # Naming enforcement
    from meta_ads_mcp.engine.naming_gate import enforce_naming

    naming_result = enforce_naming(
        proposed_name=new_campaign_name,
        object_type="campaign",
        naming_inputs=None,
    )

    if naming_result["critical_block"]:
        return {
            "error": f"Naming enforcement blocked duplicated campaign name: {naming_result.get('fix_suggestion', '')}",
            "source_name": source_name,
            "attempted_name": new_campaign_name,
            "naming_result": naming_result,
            "blocked_at": "naming_enforcement",
        }

    effective_campaign_name = naming_result["final_name"] or new_campaign_name

    # Pre-write validation
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    campaign_payload = {
        "name": effective_campaign_name,
        "objective": source_objective,
        "status": "PAUSED",
        "special_ad_categories": _json.dumps(source_sac) if source_sac else "[]",
        "is_adset_budget_sharing_enabled": "false",
    }

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="campaign",
        target_object_id=None,
        payload=campaign_payload,
        safety_tier=3,
    )

    if validation_result.verdict.value == "fail":
        return {
            "error": "Validation failed for duplicated campaign. NOT created.",
            "validation": validation_result.to_dict(),
            "blocked_at": "pre_write_validation",
        }

    # --- Step 4: Create the duplicated campaign ---
    try:
        result = api_client.graph_post(
            f"/{account_id}/campaigns",
            data=campaign_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Failed to create duplicated campaign: {e}",
            "blocked_at": "campaign_creation",
        }

    new_campaign_id = result.get("id")
    if not new_campaign_id:
        return {
            "error": "Campaign creation returned no ID.",
            "api_response": result,
            "blocked_at": "campaign_creation",
        }

    # Post-write verification
    try:
        created_campaign = api_client.graph_get(
            f"/{new_campaign_id}",
            fields=["id", "name", "status", "objective", "special_ad_categories"],
        )
        campaign_verified = created_campaign.get("status") == "PAUSED"
    except MetaAPIError:
        campaign_verified = False

    rollback_ref = f"duplicate_campaign_{campaign_id}_to_{new_campaign_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # --- Step 5: Duplicate ad sets (if requested) ---
    duplicated_adsets = []
    failed_adsets = []

    if include_adsets:
        try:
            source_adsets = api_client.graph_get(
                f"/{campaign_id}/adsets",
                fields=[
                    "id", "name", "optimization_goal", "billing_event",
                    "daily_budget", "lifetime_budget", "targeting",
                    "promoted_object", "start_time", "end_time",
                    "bid_strategy", "bid_amount",
                ],
                params={"limit": "100"},
            )
        except MetaAPIError as e:
            return {
                "status": "partial_success",
                "message": f"Campaign duplicated but failed to read source ad sets: {e}",
                "new_campaign_id": new_campaign_id,
                "new_campaign_name": effective_campaign_name,
                "duplicated_adsets": [],
                "failed_adsets": [],
                "orphaned_objects": {
                    "campaigns": [new_campaign_id],
                    "count": 1,
                    "status": "PAUSED",
                    "recommended_action": "Review or delete with delete_campaign_structure",
                },
                "rollback_reference": rollback_ref,
            }

        for source_adset in source_adsets.get("data", []):
            adset_result = _duplicate_single_adset(
                source_adset=source_adset,
                new_campaign_id=new_campaign_id,
                account_id=account_id,
                name_suffix=name_suffix,
                budget_model=budget_model,
                adset_budget_override=adset_budget_override,
            )

            if "error" in adset_result:
                failed_adsets.append({
                    "source_adset_id": source_adset.get("id"),
                    "source_adset_name": source_adset.get("name"),
                    "error": adset_result["error"],
                    "blocked_at": adset_result.get("blocked_at"),
                })
            else:
                # Duplicate ads if requested
                if include_ads and adset_result.get("new_adset_id"):
                    ads_result = _duplicate_ads_for_adset(
                        source_adset_id=source_adset.get("id"),
                        new_adset_id=adset_result["new_adset_id"],
                        account_id=account_id,
                        name_suffix=name_suffix,
                    )
                    adset_result["duplicated_ads"] = ads_result.get("duplicated", [])
                    adset_result["failed_ads"] = ads_result.get("failed", [])
                duplicated_adsets.append(adset_result)

    # --- Step 6: Build response ---
    total_created = 1 + len(duplicated_adsets)
    has_failures = len(failed_adsets) > 0

    if has_failures and len(duplicated_adsets) == 0 and include_adsets:
        status = "partial_success"
    elif has_failures:
        status = "partial_success"
    else:
        status = "success"

    # Mutation log
    log_entry = (
        f"### [{timestamp}] DUPLICATE campaign\n"
        f"- **Source:** {campaign_id} ({source_name})\n"
        f"- **New Campaign:** {new_campaign_id} ({effective_campaign_name})\n"
        f"- **Account:** {account_id}\n"
        f"- **Budget Model:** {budget_model}\n"
        f"- **Ad Sets Duplicated:** {len(duplicated_adsets)}\n"
        f"- **Ad Sets Failed:** {len(failed_adsets)}\n"
        f"- **All PAUSED:** Yes\n"
        f"- **Rollback ref:** {rollback_ref}\n"
    )

    response = {
        "status": status,
        "source_campaign_id": campaign_id,
        "source_campaign_name": source_name,
        "new_campaign_id": new_campaign_id,
        "new_campaign_name": effective_campaign_name,
        "campaign_verified": campaign_verified,
        "budget_model": budget_model,
        "include_adsets": include_adsets,
        "duplicated_adsets": duplicated_adsets,
        "total_objects_created": total_created,
        "all_paused": True,
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }

    if failed_adsets:
        response["failed_adsets"] = failed_adsets
        all_created_ids = [new_campaign_id] + [a["new_adset_id"] for a in duplicated_adsets]
        response["orphaned_objects"] = {
            "campaigns": [new_campaign_id],
            "adsets": [a["new_adset_id"] for a in duplicated_adsets],
            "count": len(all_created_ids),
            "status": "PAUSED",
            "recommended_action": "Review created objects. Use delete_campaign_structure to clean up if needed.",
        }

    return response


def _duplicate_single_adset(
    source_adset: dict,
    new_campaign_id: str,
    account_id: str,
    name_suffix: str,
    budget_model: str,
    adset_budget_override: Optional[float],
) -> dict:
    """Duplicate a single ad set into the new campaign. Returns result dict or error dict."""

    source_name = source_adset.get("name", "")
    new_name = _apply_name_suffix(source_name, name_suffix)

    # Naming enforcement
    from meta_ads_mcp.engine.naming_gate import enforce_naming

    naming_result = enforce_naming(
        proposed_name=new_name,
        object_type="adset",
        naming_inputs=None,
    )

    if naming_result["critical_block"]:
        return {
            "error": f"Naming blocked: {naming_result.get('fix_suggestion', '')}",
            "blocked_at": "naming_enforcement",
        }

    effective_name = naming_result["final_name"] or new_name

    # Build ad set payload
    payload = {
        "campaign_id": new_campaign_id,
        "name": effective_name,
        "optimization_goal": source_adset.get("optimization_goal", "LINK_CLICKS"),
        "billing_event": source_adset.get("billing_event", "IMPRESSIONS"),
        "status": "PAUSED",
    }

    # Bid strategy (required by Meta API)
    bid_strategy = source_adset.get("bid_strategy")
    if bid_strategy:
        payload["bid_strategy"] = bid_strategy
    bid_amount = source_adset.get("bid_amount")
    if bid_amount:
        payload["bid_amount"] = bid_amount

    # Targeting
    targeting = source_adset.get("targeting")
    if targeting:
        payload["targeting"] = _json.dumps(targeting, ensure_ascii=False)

    # Promoted object
    promoted_object = source_adset.get("promoted_object")
    if promoted_object:
        payload["promoted_object"] = _json.dumps(promoted_object)

    # Budget handling
    if budget_model == "ABO":
        if adset_budget_override is not None:
            payload["daily_budget"] = currency_to_cents(adset_budget_override)
        else:
            source_daily = source_adset.get("daily_budget")
            source_lifetime = source_adset.get("lifetime_budget")
            if source_daily and int(source_daily) > 0:
                payload["daily_budget"] = source_daily
            elif source_lifetime and int(source_lifetime) > 0:
                payload["lifetime_budget"] = source_lifetime
    # CBO: no budget on ad set (campaign controls it)

    # Validation
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="adset",
        target_object_id=None,
        payload=payload,
        safety_tier=3,
    )

    if validation_result.verdict.value == "fail":
        return {
            "error": f"Validation failed for ad set '{source_name}'",
            "validation": validation_result.to_dict(),
            "blocked_at": "pre_write_validation",
        }

    # Create
    try:
        result = api_client.graph_post(
            f"/{account_id}/adsets",
            data=payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"API error creating ad set: {e}",
            "blocked_at": "api_call",
        }

    new_adset_id = result.get("id")
    if not new_adset_id:
        return {
            "error": "Ad set creation returned no ID",
            "blocked_at": "api_response",
        }

    # Verify
    verified = False
    try:
        created = api_client.graph_get(
            f"/{new_adset_id}",
            fields=["id", "name", "status", "daily_budget", "lifetime_budget"],
        )
        verified = created.get("status") == "PAUSED"
    except MetaAPIError:
        pass

    return {
        "source_adset_id": source_adset.get("id"),
        "source_adset_name": source_name,
        "new_adset_id": new_adset_id,
        "new_adset_name": effective_name,
        "daily_budget": payload.get("daily_budget"),
        "lifetime_budget": payload.get("lifetime_budget"),
        "verified": verified,
    }


def _duplicate_ads_for_adset(
    source_adset_id: str,
    new_adset_id: str,
    account_id: str,
    name_suffix: str,
) -> dict:
    """Duplicate all ads from source ad set into new ad set. Reuses creative references."""
    import json as _json

    duplicated = []
    failed = []

    try:
        source_ads = api_client.graph_get(
            f"/{source_adset_id}/ads",
            fields=["id", "name", "creative", "status"],
            params={"limit": "50"},
        )
    except MetaAPIError as e:
        return {"duplicated": [], "failed": [{"error": f"Cannot read source ads: {e}"}]}

    for source_ad in source_ads.get("data", []):
        source_name = source_ad.get("name", "")
        new_name = _apply_name_suffix(source_name, name_suffix)

        # Get creative ID from source
        creative = source_ad.get("creative", {})
        creative_id = creative.get("id") if isinstance(creative, dict) else None

        if not creative_id:
            failed.append({
                "source_ad_id": source_ad.get("id"),
                "error": "No creative ID found on source ad",
            })
            continue

        # Create ad with same creative reference
        payload = {
            "adset_id": new_adset_id,
            "name": new_name,
            "status": "PAUSED",
            "creative": _json.dumps({"creative_id": creative_id}),
        }

        try:
            result = api_client.graph_post(f"/{account_id}/ads", data=payload)
            new_ad_id = result.get("id")
            if new_ad_id:
                duplicated.append({
                    "source_ad_id": source_ad.get("id"),
                    "new_ad_id": new_ad_id,
                    "new_ad_name": new_name,
                    "creative_id": creative_id,
                })
            else:
                failed.append({
                    "source_ad_id": source_ad.get("id"),
                    "error": "No ad ID returned",
                })
        except MetaAPIError as e:
            failed.append({
                "source_ad_id": source_ad.get("id"),
                "error": str(e),
            })

    return {"duplicated": duplicated, "failed": failed}


# --- Convenience Gap: Standalone Ad Set Duplication ---

@mcp.tool()
def duplicate_adset(
    adset_id: str,
    target_campaign_id: str,
    account_id: str,
    name_suffix: str = " - Copy",
    budget_override: Optional[float] = None,
) -> dict:
    """
    Duplicate a single ad set into a target campaign within the same account.

    All created objects are PAUSED. Does not duplicate child ads.
    Same-account only.

    Args:
        adset_id: Source ad set ID to duplicate.
        target_campaign_id: Campaign to place the duplicated ad set in.
        account_id: Ad account ID (must match source).
        name_suffix: Appended to source name (default " - Copy").
        budget_override: Override budget in EUR. If None, copies source budget.
    """
    account_id = ensure_account_id_format(account_id)
    api_client._ensure_initialized()

    # Read source ad set
    try:
        source = api_client.graph_get(
            f"/{adset_id}",
            fields=[
                "id", "name", "optimization_goal", "billing_event",
                "daily_budget", "lifetime_budget", "targeting",
                "promoted_object", "start_time", "end_time",
                "bid_strategy", "bid_amount", "account_id",
            ],
        )
    except MetaAPIError as e:
        return {"error": f"Cannot read source ad set {adset_id}: {e}", "blocked_at": "source_read"}

    # Same-account check
    source_account = source.get("account_id", "")
    if source_account and not source_account.startswith("act_"):
        source_account = f"act_{source_account}"
    if source_account and source_account != account_id:
        return {
            "error": f"Cross-account duplication not supported. Source: {source_account}, target: {account_id}.",
            "blocked_at": "same_account_enforcement",
        }

    # Detect budget model from target campaign
    try:
        target_campaign = api_client.graph_get(
            f"/{target_campaign_id}",
            fields=["id", "daily_budget", "lifetime_budget"],
        )
    except MetaAPIError as e:
        return {"error": f"Cannot read target campaign: {e}", "blocked_at": "target_read"}

    from meta_ads_mcp.core.adsets import _detect_budget_model
    budget_model, _ = _detect_budget_model(target_campaign)

    result = _duplicate_single_adset(
        source_adset=source,
        new_campaign_id=target_campaign_id,
        account_id=account_id,
        name_suffix=name_suffix,
        budget_model=budget_model,
        adset_budget_override=budget_override,
    )

    if "error" in result:
        return result

    return {
        "status": "success",
        "source_adset_id": adset_id,
        "new_adset_id": result["new_adset_id"],
        "new_adset_name": result["new_adset_name"],
        "target_campaign_id": target_campaign_id,
        "budget_model": budget_model,
        "verified": result.get("verified", False),
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
