"""
Campaign management tools.

Provides CRUD operations for Meta Ads campaigns.
Read operations in Phase v1.1, write operations in Phase v1.3.

Supports outcome-based objectives only (OUTCOME_LEADS, OUTCOME_SALES, etc.).
Legacy objectives (BRAND_AWARENESS, LINK_CLICKS) are rejected.
All campaigns created as PAUSED by default.
"""
import logging
from datetime import datetime
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format, format_budget_cents_to_currency

logger = logging.getLogger("meta-ads-mcp.campaigns")

# Outcome-based objectives (required since Meta API migration)
VALID_OBJECTIVES = [
    "OUTCOME_AWARENESS",
    "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS",
    "OUTCOME_SALES",
    "OUTCOME_TRAFFIC",
    "OUTCOME_APP_PROMOTION",
]

# Legacy objectives that must NOT be used
LEGACY_OBJECTIVES = [
    "BRAND_AWARENESS", "REACH", "LINK_CLICKS", "POST_ENGAGEMENT",
    "VIDEO_VIEWS", "LEAD_GENERATION", "MESSAGES", "CONVERSIONS",
    "CATALOG_SALES", "STORE_TRAFFIC", "APP_INSTALLS",
]

# Campaign fields for list view (compact)
CAMPAIGN_LIST_FIELDS = [
    "id", "name", "status", "effective_status", "objective",
    "daily_budget", "lifetime_budget", "budget_remaining",
    "buying_type", "start_time", "stop_time",
    "created_time", "updated_time",
]

# Campaign fields for detail view (full)
CAMPAIGN_DETAIL_FIELDS = CAMPAIGN_LIST_FIELDS + [
    "bid_strategy", "budget_rebalance_flag",
    "special_ad_categories", "special_ad_category_country",
    "spend_cap", "configured_status",
    "pacing_type", "promoted_object",
    "smart_promotion_type", "source_campaign_id",
    "issues_info",
]


@mcp.tool()
def get_campaigns(
    account_id: str,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    List campaigns for an ad account with status and budget info.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        status_filter: Filter by effective_status: 'ACTIVE', 'PAUSED', 'ARCHIVED', or 'ALL'.
            If not set, returns all campaigns.
        limit: Maximum results per page (default 50, max 100).
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    params = {"limit": str(min(limit, 100))}

    if status_filter and status_filter.upper() != "ALL":
        status_val = status_filter.upper()
        valid_statuses = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"]
        if status_val in valid_statuses:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{status_val}"]}}]'

    try:
        result = api_client.graph_get(
            f"/{account_id}/campaigns",
            fields=CAMPAIGN_LIST_FIELDS,
            params=params,
        )

        campaigns = result.get("data", [])

        # Enrich with human-readable budget
        for c in campaigns:
            if c.get("daily_budget"):
                c["daily_budget_display"] = format_budget_cents_to_currency(c["daily_budget"])
            if c.get("lifetime_budget"):
                c["lifetime_budget_display"] = format_budget_cents_to_currency(c["lifetime_budget"])

        # Handle pagination - collect all pages if more than one
        all_campaigns = list(campaigns)
        paging = result.get("paging", {})
        page_count = 1

        while paging.get("next") and len(all_campaigns) < 200:
            # Extract the 'after' cursor and fetch next page
            after_cursor = paging.get("cursors", {}).get("after")
            if not after_cursor:
                break
            params["after"] = after_cursor
            result = api_client.graph_get(
                f"/{account_id}/campaigns",
                fields=CAMPAIGN_LIST_FIELDS,
                params=params,
            )
            next_campaigns = result.get("data", [])
            if not next_campaigns:
                break
            for c in next_campaigns:
                if c.get("daily_budget"):
                    c["daily_budget_display"] = format_budget_cents_to_currency(c["daily_budget"])
                if c.get("lifetime_budget"):
                    c["lifetime_budget_display"] = format_budget_cents_to_currency(c["lifetime_budget"])
            all_campaigns.extend(next_campaigns)
            paging = result.get("paging", {})
            page_count += 1

        # Count by status
        status_counts = {}
        for c in all_campaigns:
            es = c.get("effective_status", "UNKNOWN")
            status_counts[es] = status_counts.get(es, 0) + 1

        return {
            "total": len(all_campaigns),
            "status_counts": status_counts,
            "pages_fetched": page_count,
            "campaigns": all_campaigns,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def get_campaign_details(campaign_id: str) -> dict:
    """
    Get detailed information about a specific campaign including
    budget, objective, bid strategy, special categories, and issues.

    Args:
        campaign_id: Campaign ID (numeric string).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{campaign_id}",
            fields=CAMPAIGN_DETAIL_FIELDS,
        )

        # Enrich budget display
        if result.get("daily_budget"):
            result["daily_budget_display"] = format_budget_cents_to_currency(result["daily_budget"])
        if result.get("lifetime_budget"):
            result["lifetime_budget_display"] = format_budget_cents_to_currency(result["lifetime_budget"])

        # Get child ad set count
        try:
            adsets_result = api_client.graph_get(
                f"/{campaign_id}/adsets",
                fields=["id"],
                params={"limit": "0", "summary": "true"},
            )
            # summary field gives total count without loading all records
            # Fallback: count data entries
            adset_data = adsets_result.get("data", [])
            result["adset_count"] = len(adset_data)
        except MetaAPIError:
            result["adset_count"] = None

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except MetaAPIError:
        raise


# --- Phase v1.3: Write Operations ---

@mcp.tool()
def create_campaign(
    account_id: str,
    name: str,
    objective: str,
    special_ad_categories: Optional[str] = None,
    product: Optional[str] = None,
    funnel: Optional[str] = None,
    budget_model: Optional[str] = None,
) -> dict:
    """
    Create a new campaign (always PAUSED, no exceptions).

    Runs naming enforcement, pre-write validation, creates the campaign,
    verifies post-write, and logs the mutation.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        name: Campaign name following convention: Objective | Product | Funnel | BudgetModel.
            If not following convention, provide product/funnel/budget_model for auto-correction.
        objective: Must be an outcome-based objective:
            OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_LEADS,
            OUTCOME_SALES, OUTCOME_TRAFFIC, OUTCOME_APP_PROMOTION.
        special_ad_categories: Comma-separated special categories if applicable.
        product: Product/offer name for naming convention (e.g., 'Consulting', 'VitC').
        funnel: Funnel stage for naming: TOFU, MOFU, BOFU, RT.
        budget_model: ABO or CBO for naming convention.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Vault gate ---
    from meta_ads_mcp.core.vault_reader import enforce_vault_gate
    vault_error, vault_ctx = enforce_vault_gate(account_id, "create_campaign")
    if vault_error:
        return vault_error

    # --- Step 0: Input validation (hard gates) ---

    # Objective validation
    objective_upper = objective.upper().strip()
    if objective_upper in LEGACY_OBJECTIVES:
        return {
            "error": f"Legacy objective '{objective}' is not supported. Use outcome-based objectives.",
            "valid_objectives": VALID_OBJECTIVES,
            "blocked_at": "input_validation",
        }
    if objective_upper not in VALID_OBJECTIVES:
        return {
            "error": f"Unknown objective '{objective}'.",
            "valid_objectives": VALID_OBJECTIVES,
            "blocked_at": "input_validation",
        }

    # Parse special_ad_categories
    sac_list: list[str] = []
    if special_ad_categories:
        sac_list = [s.strip().upper() for s in special_ad_categories.split(",") if s.strip()]
        valid_sac = ["FINANCIAL_PRODUCTS_SERVICES", "EMPLOYMENT", "HOUSING", "ISSUES_ELECTIONS_POLITICS"]
        for s in sac_list:
            if s not in valid_sac:
                return {
                    "error": f"Invalid special_ad_category: '{s}'.",
                    "valid_categories": valid_sac,
                    "blocked_at": "input_validation",
                }

    # --- Naming enforcement ---
    from meta_ads_mcp.engine.naming_gate import enforce_naming

    naming_inputs = {}
    if product or funnel or budget_model:
        naming_inputs = {
            "objective": objective_upper,
            "product": product or "",
            "funnel": funnel or "",
            "budget_model": budget_model or "ABO",
        }

    naming_result = enforce_naming(
        proposed_name=name,
        object_type="campaign",
        naming_inputs=naming_inputs if naming_inputs else None,
    )

    if naming_result["critical_block"]:
        return {
            "error": f"Naming enforcement BLOCKED: {naming_result.get('fix_suggestion', 'Invalid name')}",
            "naming_result": naming_result,
            "blocked_at": "naming_enforcement",
        }

    # Use enforced name (may be auto-corrected or auto-generated)
    effective_name = naming_result["final_name"] or name

    # Build the payload (status is ALWAYS PAUSED - hard enforced)
    payload = {
        "name": effective_name,
        "objective": objective_upper,
        "status": "PAUSED",
        "special_ad_categories": sac_list,
        # Meta requires this when no campaign-level budget is set
        "is_adset_budget_sharing_enabled": False,
    }

    # --- Step 1: Pre-write validation ---
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="campaign",
        target_object_id=None,
        payload=payload,
        safety_tier=3,  # Creates are Tier 3 (unrestricted)
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Campaign NOT created.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    # --- Step 2: Pre-write snapshot ---
    try:
        existing = api_client.graph_get(
            f"/{account_id}/campaigns",
            fields=["id"],
            params={"limit": "0"},
        )
        pre_campaign_count = len(existing.get("data", []))
    except MetaAPIError:
        pre_campaign_count = "unknown"

    rollback_ref = f"create_campaign_{account_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # --- Step 3: API call - create campaign ---
    # Meta expects form-encoded data with JSON-serialized list fields
    import json as _json
    api_payload = {
        "name": effective_name,
        "objective": objective_upper,
        "status": "PAUSED",
        "special_ad_categories": _json.dumps(sac_list),
        "is_adset_budget_sharing_enabled": "false",
    }

    from meta_ads_mcp.safety.rate_limiter import enforce_rate_gate
    rate_gate = enforce_rate_gate(account_id, "write")
    if not rate_gate["allowed"]:
        return {
            "error": f"Rate limit gate BLOCKED: {rate_gate['block_reason']}",
            "blocked_at": "rate_limit_gate",
            "rate_state": rate_gate["state"],
            "usage_pct": rate_gate["usage_pct"],
        }

    try:
        result = api_client.graph_post(
            f"/{account_id}/campaigns",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during campaign creation: {e}",
            "validation": validation_dict,
            "blocked_at": "api_call",
            "rollback_reference": rollback_ref,
        }

    campaign_id = result.get("id")
    if not campaign_id:
        return {
            "error": "Campaign creation returned no ID. API response may be malformed.",
            "api_response": result,
            "validation": validation_dict,
            "blocked_at": "api_response",
        }

    # --- Step 4: Post-write verification ---
    verification = {
        "campaign_id": campaign_id,
        "status_verified": False,
        "objective_verified": False,
        "name_verified": False,
        "critical_mismatch": False,
    }

    try:
        created = api_client.graph_get(
            f"/{campaign_id}",
            fields=["id", "name", "status", "effective_status", "objective",
                     "special_ad_categories", "account_id"],
        )

        # Verify status
        actual_status = created.get("status", "")
        actual_effective = created.get("effective_status", "")
        if actual_status == "PAUSED":
            verification["status_verified"] = True
        else:
            verification["critical_mismatch"] = True
            verification["status_expected"] = "PAUSED"
            verification["status_actual"] = actual_status
            logger.critical(
                "CRITICAL: Campaign %s created with status %s instead of PAUSED!",
                campaign_id, actual_status,
            )

        # Verify objective
        actual_objective = created.get("objective", "")
        if actual_objective == objective_upper:
            verification["objective_verified"] = True
        else:
            verification["critical_mismatch"] = True
            verification["objective_expected"] = objective_upper
            verification["objective_actual"] = actual_objective

        # Verify name (Greek integrity check)
        actual_name = created.get("name", "")
        if actual_name == name:
            verification["name_verified"] = True
        else:
            verification["name_expected"] = name
            verification["name_actual"] = actual_name
            verification["name_note"] = "Name mismatch - possible encoding issue"

        verification["effective_status"] = actual_effective
        verification["special_ad_categories"] = created.get("special_ad_categories", [])

    except MetaAPIError as e:
        verification["verification_error"] = str(e)
        verification["note"] = "Campaign was created but post-verification read failed."

    # --- Step 5: Mutation log entry ---
    log_entry = (
        f"### [{timestamp}] CREATE campaign\n"
        f"- **Account:** {account_id}\n"
        f"- **Campaign ID:** {campaign_id}\n"
        f"- **Name:** {name}\n"
        f"- **Objective:** {objective_upper}\n"
        f"- **Status:** PAUSED (enforced)\n"
        f"- **Special categories:** {sac_list or 'none'}\n"
        f"- **Validation:** {validation_result.verdict.value} "
        f"({len(validation_result.checks)} checks, "
        f"{len(validation_result.blocking_issues)} blocking, "
        f"{len(validation_result.warnings)} warnings)\n"
        f"- **Verification:** status={'OK' if verification['status_verified'] else 'MISMATCH'}, "
        f"objective={'OK' if verification['objective_verified'] else 'MISMATCH'}, "
        f"name={'OK' if verification['name_verified'] else 'MISMATCH'}\n"
        f"- **Rollback ref:** {rollback_ref}\n"
        f"- **Pre-existing campaigns:** {pre_campaign_count}\n"
    )

    # Return the full result
    return {
        "campaign_id": campaign_id,
        "status": "PAUSED",
        "objective": objective_upper,
        "name": effective_name,
        "naming_enforcement": naming_result,
        "special_ad_categories": sac_list,
        "validation": validation_dict,
        "verification": verification,
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "vault_status": {
            "client_slug": vault_ctx.get("client_slug"),
            "vault_readiness": vault_ctx.get("vault_readiness"),
            "vault_files_loaded": vault_ctx.get("vault_files_loaded"),
            "resolved_ids": vault_ctx.get("resolved_ids"),
        },
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


# --- Phase C.1: Campaign update ---

@mcp.tool()
def update_campaign(
    campaign_id: str,
    name: Optional[str] = None,
    daily_budget: Optional[float] = None,
    lifetime_budget: Optional[float] = None,
    status: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    special_ad_categories: Optional[str] = None,
) -> dict:
    """
    Update an existing campaign. Supervised write - validates before applying.

    Takes a pre-write snapshot for rollback, validates the update payload,
    applies via Meta API, and verifies post-write state.

    Args:
        campaign_id: Campaign ID to update.
        name: New campaign name. Subject to naming enforcement.
        daily_budget: New daily budget in currency units (e.g., 50.0 for EUR 50).
            Mutually exclusive with lifetime_budget.
        lifetime_budget: New lifetime budget in currency units.
            Mutually exclusive with daily_budget.
        status: New status. Allowed: 'PAUSED', 'ACTIVE', 'ARCHIVED'.
            Activating requires confirmation-level validation.
        start_time: New start time (ISO 8601 format).
        end_time: New end time / stop_time (ISO 8601 format).
        special_ad_categories: Comma-separated categories or empty string to clear.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- At least one field must be provided ---
    if all(v is None for v in [name, daily_budget, lifetime_budget, status, start_time, end_time, special_ad_categories]):
        return {
            "error": "No update fields provided. Specify at least one field to update.",
            "supported_fields": ["name", "daily_budget", "lifetime_budget", "status", "start_time", "end_time", "special_ad_categories"],
            "blocked_at": "input_validation",
        }

    # --- Budget mutual exclusivity ---
    if daily_budget is not None and lifetime_budget is not None:
        return {
            "error": "Cannot set both daily_budget and lifetime_budget. Choose one.",
            "blocked_at": "input_validation",
        }

    # --- Status validation ---
    allowed_statuses = ["PAUSED", "ACTIVE", "ARCHIVED"]
    if status is not None:
        status_upper = status.upper().strip()
        if status_upper not in allowed_statuses:
            return {
                "error": f"Invalid status '{status}'. Allowed: {allowed_statuses}",
                "blocked_at": "input_validation",
            }
        status = status_upper

    # --- Special ad categories validation ---
    sac_list = None
    if special_ad_categories is not None:
        valid_sac = ["FINANCIAL_PRODUCTS_SERVICES", "EMPLOYMENT", "HOUSING", "ISSUES_ELECTIONS_POLITICS"]
        if special_ad_categories.strip() == "":
            sac_list = []
        else:
            sac_list = [s.strip().upper() for s in special_ad_categories.split(",") if s.strip()]
            for s in sac_list:
                if s not in valid_sac:
                    return {
                        "error": f"Invalid special_ad_category: '{s}'.",
                        "valid_categories": valid_sac,
                        "blocked_at": "input_validation",
                    }

    # --- Step 0: Pre-write snapshot (for rollback and verification) ---
    api_client._ensure_initialized()
    try:
        current = api_client.graph_get(
            f"/{campaign_id}",
            fields=["id", "name", "status", "effective_status", "objective",
                     "daily_budget", "lifetime_budget", "start_time", "stop_time",
                     "special_ad_categories", "account_id"],
        )
    except MetaAPIError as e:
        return {
            "error": f"Cannot read campaign {campaign_id} for pre-update snapshot: {e}",
            "blocked_at": "pre_snapshot",
        }

    account_id = current.get("account_id", "")
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    rollback_ref = f"update_campaign_{campaign_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # --- Step 1: Naming enforcement (if name is being updated) ---
    effective_name = None
    naming_result = None
    if name is not None:
        from meta_ads_mcp.engine.naming_gate import enforce_naming

        naming_result = enforce_naming(
            proposed_name=name,
            object_type="campaign",
            naming_inputs=None,
        )

        if naming_result["critical_block"]:
            return {
                "error": f"Naming enforcement BLOCKED: {naming_result.get('fix_suggestion', 'Invalid name')}",
                "naming_result": naming_result,
                "blocked_at": "naming_enforcement",
            }

        effective_name = naming_result["final_name"] or name

    # --- Step 2: Build update payload ---
    import json as _json

    api_payload = {}

    if effective_name is not None:
        api_payload["name"] = effective_name
    if daily_budget is not None:
        api_payload["daily_budget"] = currency_to_cents(daily_budget)
    if lifetime_budget is not None:
        api_payload["lifetime_budget"] = currency_to_cents(lifetime_budget)
    if status is not None:
        api_payload["status"] = status
    if start_time is not None:
        api_payload["start_time"] = start_time
    if end_time is not None:
        api_payload["stop_time"] = end_time  # Meta API uses stop_time, not end_time
    if sac_list is not None:
        api_payload["special_ad_categories"] = _json.dumps(sac_list)

    # --- Step 3: Pre-write validation ---
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    # Use ACTIVATE validation if activating, MODIFY_ACTIVE otherwise
    action_class = ActionClass.ACTIVATE if status == "ACTIVE" else ActionClass.MODIFY_ACTIVE

    validation_result = run_validation(
        action_class=action_class,
        target_account_id=account_id,
        target_object_type="campaign",
        target_object_id=campaign_id,
        payload=api_payload,
        safety_tier=3,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Campaign NOT updated.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    # Activation requires explicit confirmation
    if validation_result.verdict.value == "requires_confirmation" and status == "ACTIVE":
        return {
            "status": "requires_confirmation",
            "message": "Activating a campaign requires explicit confirmation. Review validation and re-submit with confirmation.",
            "validation": validation_dict,
            "campaign_id": campaign_id,
            "current_status": current.get("status"),
            "requested_status": "ACTIVE",
        }

    # --- Step 4: API call - update campaign ---
    from meta_ads_mcp.safety.rate_limiter import enforce_rate_gate
    rate_gate = enforce_rate_gate(campaign_id, "write")
    if not rate_gate["allowed"]:
        return {
            "error": f"Rate limit gate BLOCKED: {rate_gate['block_reason']}",
            "blocked_at": "rate_limit_gate",
            "rate_state": rate_gate["state"],
            "usage_pct": rate_gate["usage_pct"],
        }

    try:
        result = api_client.graph_post(
            f"/{campaign_id}",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during campaign update: {e}",
            "validation": validation_dict,
            "blocked_at": "api_call",
            "rollback_reference": rollback_ref,
            "pre_update_state": {
                "name": current.get("name"),
                "status": current.get("status"),
                "daily_budget": current.get("daily_budget"),
                "lifetime_budget": current.get("lifetime_budget"),
            },
        }

    # --- Step 5: Post-write verification ---
    verification = {
        "campaign_id": campaign_id,
        "fields_updated": list(api_payload.keys()),
        "mismatches": [],
    }

    try:
        updated = api_client.graph_get(
            f"/{campaign_id}",
            fields=["id", "name", "status", "effective_status",
                     "daily_budget", "lifetime_budget", "start_time", "stop_time",
                     "special_ad_categories"],
        )

        # Verify each updated field
        if effective_name is not None:
            actual_name = updated.get("name", "")
            if actual_name != effective_name:
                verification["mismatches"].append({
                    "field": "name",
                    "expected": effective_name,
                    "actual": actual_name,
                })

        if status is not None:
            actual_status = updated.get("status", "")
            if actual_status != status:
                verification["mismatches"].append({
                    "field": "status",
                    "expected": status,
                    "actual": actual_status,
                })

        if daily_budget is not None:
            actual_budget = updated.get("daily_budget", "")
            expected_cents = currency_to_cents(daily_budget)
            if str(actual_budget) != expected_cents:
                verification["mismatches"].append({
                    "field": "daily_budget",
                    "expected_cents": expected_cents,
                    "actual_cents": actual_budget,
                })

        if lifetime_budget is not None:
            actual_budget = updated.get("lifetime_budget", "")
            expected_cents = currency_to_cents(lifetime_budget)
            if str(actual_budget) != expected_cents:
                verification["mismatches"].append({
                    "field": "lifetime_budget",
                    "expected_cents": expected_cents,
                    "actual_cents": actual_budget,
                })

        verification["post_update_status"] = updated.get("status")
        verification["post_update_effective_status"] = updated.get("effective_status")
        verification["verified"] = len(verification["mismatches"]) == 0

    except MetaAPIError as e:
        verification["verification_error"] = str(e)
        verification["verified"] = False
        verification["note"] = "Campaign was updated but post-verification read failed."

    # --- Step 6: Mutation log entry ---
    fields_summary = ", ".join(f"{k}={v}" for k, v in api_payload.items())
    log_entry = (
        f"### [{timestamp}] UPDATE campaign\n"
        f"- **Campaign ID:** {campaign_id}\n"
        f"- **Account:** {account_id}\n"
        f"- **Fields:** {fields_summary}\n"
        f"- **Validation:** {validation_result.verdict.value}\n"
        f"- **Verification:** {'OK' if verification.get('verified') else 'MISMATCH'}\n"
        f"- **Rollback ref:** {rollback_ref}\n"
        f"- **Pre-update state:** name={current.get('name')}, status={current.get('status')}, "
        f"daily_budget={current.get('daily_budget')}, lifetime_budget={current.get('lifetime_budget')}\n"
    )

    return {
        "campaign_id": campaign_id,
        "updated_fields": list(api_payload.keys()),
        "validation": validation_dict,
        "verification": verification,
        "pre_update_state": {
            "name": current.get("name"),
            "status": current.get("status"),
            "effective_status": current.get("effective_status"),
            "daily_budget": current.get("daily_budget"),
            "lifetime_budget": current.get("lifetime_budget"),
            "start_time": current.get("start_time"),
            "stop_time": current.get("stop_time"),
        },
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
