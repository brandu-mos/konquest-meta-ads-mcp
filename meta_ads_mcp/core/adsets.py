"""
Ad Set management tools.

Provides CRUD operations for Meta Ads ad sets.
Read operations in Phase v1.1, write operations in Phase v1.3.

Handles targeting, budgets, scheduling, frequency caps, promoted objects,
and DSA compliance fields for EU campaigns.

## ABO vs CBO Budget Model Rules

### ABO (Ad Set Budget Optimization)
Use when: testing angles/audiences/hooks, controlling per-ad-set spend,
learning/exploration phase, or when granular budget control matters.
Detection: parent campaign has NO daily_budget and NO lifetime_budget.
Rule: ad set MUST provide its own daily_budget or lifetime_budget.

### CBO (Campaign Budget Optimization)
Use when: scaling proven winners, letting Meta optimize distribution,
or when campaign has a fixed total budget.
Detection: parent campaign HAS daily_budget or lifetime_budget.
Rule: ad set MUST NOT provide budget. Meta distributes from campaign.

### Enforcement
- ABO without ad set budget -> BLOCK
- CBO with ad set budget -> BLOCK
- Both daily and lifetime on same ad set -> BLOCK
"""
import json as _json
import logging
from datetime import datetime
from typing import Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format, format_budget_cents_to_currency, currency_to_cents

logger = logging.getLogger("meta-ads-mcp.adsets")

# Optimization goals by campaign objective
OPTIMIZATION_GOALS = {
    "OUTCOME_LEADS": ["LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS", "LINK_CLICKS", "OFFSITE_CONVERSIONS"],
    "OUTCOME_SALES": ["OFFSITE_CONVERSIONS", "VALUE", "LINK_CLICKS"],
    "OUTCOME_TRAFFIC": ["LINK_CLICKS", "LANDING_PAGE_VIEWS", "IMPRESSIONS"],
    "OUTCOME_AWARENESS": ["REACH", "IMPRESSIONS", "AD_RECALL_LIFT", "THRUPLAY"],
    "OUTCOME_ENGAGEMENT": ["POST_ENGAGEMENT", "THRUPLAY", "LINK_CLICKS"],
    "OUTCOME_APP_PROMOTION": ["APP_INSTALLS", "LINK_CLICKS"],
}

# Fields for list view
ADSET_LIST_FIELDS = [
    "id", "name", "status", "effective_status",
    "campaign_id", "daily_budget", "lifetime_budget",
    "optimization_goal", "billing_event", "bid_strategy",
    "start_time", "end_time",
    "created_time", "updated_time",
]

# Fields for detail view
ADSET_DETAIL_FIELDS = ADSET_LIST_FIELDS + [
    "targeting", "promoted_object",
    "budget_remaining", "bid_amount",
    "frequency_control_specs", "pacing_type",
    "destination_type", "attribution_spec",
    "learning_stage_info",
    "issues_info",
]


@mcp.tool()
def get_adsets(
    account_id: str,
    campaign_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    List ad sets for an account or filtered by campaign.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        campaign_id: Optional campaign ID to filter ad sets for that campaign only.
        status_filter: Filter by effective_status: 'ACTIVE', 'PAUSED', 'ARCHIVED', or 'ALL'.
        limit: Maximum results per page (default 50).
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    params = {"limit": str(min(limit, 100))}

    if status_filter and status_filter.upper() != "ALL":
        status_val = status_filter.upper()
        valid_statuses = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED"]
        if status_val in valid_statuses:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{status_val}"]}}]'

    # Choose endpoint: campaign-scoped or account-scoped
    if campaign_id:
        endpoint = f"/{campaign_id}/adsets"
    else:
        endpoint = f"/{account_id}/adsets"

    try:
        result = api_client.graph_get(
            endpoint,
            fields=ADSET_LIST_FIELDS,
            params=params,
        )

        adsets = result.get("data", [])

        # Enrich with human-readable budget
        for a in adsets:
            if a.get("daily_budget"):
                a["daily_budget_display"] = format_budget_cents_to_currency(a["daily_budget"])
            if a.get("lifetime_budget"):
                a["lifetime_budget_display"] = format_budget_cents_to_currency(a["lifetime_budget"])

        # Paginate up to 200
        all_adsets = list(adsets)
        paging = result.get("paging", {})
        while paging.get("next") and len(all_adsets) < 200:
            after_cursor = paging.get("cursors", {}).get("after")
            if not after_cursor:
                break
            params["after"] = after_cursor
            result = api_client.graph_get(endpoint, fields=ADSET_LIST_FIELDS, params=params)
            next_adsets = result.get("data", [])
            if not next_adsets:
                break
            for a in next_adsets:
                if a.get("daily_budget"):
                    a["daily_budget_display"] = format_budget_cents_to_currency(a["daily_budget"])
                if a.get("lifetime_budget"):
                    a["lifetime_budget_display"] = format_budget_cents_to_currency(a["lifetime_budget"])
            all_adsets.extend(next_adsets)
            paging = result.get("paging", {})

        # Count by status
        status_counts = {}
        for a in all_adsets:
            es = a.get("effective_status", "UNKNOWN")
            status_counts[es] = status_counts.get(es, 0) + 1

        return {
            "total": len(all_adsets),
            "status_counts": status_counts,
            "adsets": all_adsets,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def get_adset_details(adset_id: str) -> dict:
    """
    Get detailed ad set information including targeting, optimization,
    learning stage, frequency caps, and attribution settings.

    Args:
        adset_id: Ad set ID (numeric string).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{adset_id}",
            fields=ADSET_DETAIL_FIELDS,
        )

        # Enrich budget display
        if result.get("daily_budget"):
            result["daily_budget_display"] = format_budget_cents_to_currency(result["daily_budget"])
        if result.get("lifetime_budget"):
            result["lifetime_budget_display"] = format_budget_cents_to_currency(result["lifetime_budget"])

        # Get child ad count
        try:
            ads_result = api_client.graph_get(
                f"/{adset_id}/ads",
                fields=["id"],
                params={"limit": "0"},
            )
            result["ad_count"] = len(ads_result.get("data", []))
        except MetaAPIError:
            result["ad_count"] = None

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except MetaAPIError:
        raise


# --- Phase v1.3: Write Operations ---

# Objectives that require promoted_object
PROMOTED_OBJECT_REQUIRED = {
    "OUTCOME_SALES": "pixel_id + custom_event_type",
    "OUTCOME_LEADS": "page_id or pixel_id + lead event",
}

VALID_BILLING_EVENTS = ["IMPRESSIONS", "LINK_CLICKS", "POST_ENGAGEMENT", "THRUPLAY"]

VALID_AUDIENCE_MODES = ["manual", "broad", "existing_audience", "advantage_plus", "restricted"]


def _detect_budget_model(campaign: dict) -> tuple[str, str]:
    """
    Detect whether a campaign uses ABO or CBO based on its budget fields.

    Returns (model, reason) where model is 'ABO' or 'CBO'.
    """
    has_daily = bool(campaign.get("daily_budget"))
    has_lifetime = bool(campaign.get("lifetime_budget"))

    if has_daily or has_lifetime:
        budget_str = campaign.get("daily_budget") or campaign.get("lifetime_budget")
        return "CBO", f"Campaign has {'daily' if has_daily else 'lifetime'} budget ({budget_str} cents). Ad sets must NOT set their own budget."
    else:
        return "ABO", "Campaign has no budget. Ad sets must provide their own daily_budget or lifetime_budget."


@mcp.tool()
def create_adset(
    account_id: str,
    campaign_id: str,
    name: str,
    optimization_goal: str,
    billing_event: str = "IMPRESSIONS",
    daily_budget: Optional[float] = None,
    lifetime_budget: Optional[float] = None,
    targeting_json: Optional[str] = None,
    promoted_object_json: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    audience_mode: str = "advantage_plus",
    icp_name: Optional[str] = None,
    icp_signals_json: Optional[str] = None,
    experiment_type: Optional[str] = None,
    explicit_tracking_mode: Optional[str] = None,
    naming_audience_type: Optional[str] = None,
    naming_age_range: Optional[str] = None,
    naming_geo: str = "GR",
    naming_exclusion_flag: str = "None",
) -> dict:
    """
    Create a new ad set (always PAUSED, no exceptions).

    Runs Advantage+ audience enforcement, parent campaign inspection, ABO/CBO
    enforcement, ICP signal mapping, narrowing detection, pre-write validation,
    creates the ad set, and verifies post-write.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        campaign_id: Parent campaign ID. Must be PAUSED or ACTIVE.
        name: Ad set name. Greek text validated.
        optimization_goal: e.g. 'OFFSITE_CONVERSIONS', 'LINK_CLICKS', 'LEAD_GENERATION', 'REACH'.
            Must be compatible with parent campaign objective.
        billing_event: Usually 'IMPRESSIONS'. Also: 'LINK_CLICKS', 'THRUPLAY'.
        daily_budget: Daily budget in EUR (e.g., 15.00). Required for ABO campaigns. Omit for CBO.
        lifetime_budget: Lifetime budget in EUR. Alternative to daily_budget. Requires end_time.
        targeting_json: JSON string of targeting spec. Advantage+ mode uses signals as suggestions.
            Example: '{"geo_locations":{"countries":["GR"]},"age_min":25,"age_max":55}'
        promoted_object_json: JSON string of promoted object. Required for OUTCOME_SALES/LEADS.
            Example: '{"pixel_id":"123456789012345","custom_event_type":"PURCHASE"}'
        start_time: ISO 8601 start time. Optional (defaults to immediately when activated).
        end_time: ISO 8601 end time. Required if using lifetime_budget.
        audience_mode: 'advantage_plus' (default, recommended), 'manual', 'broad',
            'existing_audience', 'restricted' (disables Advantage+).
        icp_name: ICP name from concept selection for signal derivation.
        icp_signals_json: Pre-built ICP signals JSON with interests/behaviors/demographics.
        experiment_type: If 'strict_audience_test', allows Advantage+ OFF.
        explicit_tracking_mode: Operator-declared tracking mode override.
            'instant_form', 'messaging', 'page_engagement' allow writes without pixel.
            If not set, system infers intended flow and enforces pixel for website paths.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Vault gate ---
    from meta_ads_mcp.core.vault_reader import enforce_vault_gate
    vault_error, vault_ctx = enforce_vault_gate(account_id, "create_adset")
    if vault_error:
        return vault_error

    # ============================================================
    # Step 0: Input validation (hard gates)
    # ============================================================

    # Billing event
    billing_upper = billing_event.upper().strip()
    if billing_upper not in VALID_BILLING_EVENTS:
        return {
            "error": f"Invalid billing_event: '{billing_event}'.",
            "valid_values": VALID_BILLING_EVENTS,
            "blocked_at": "input_validation",
        }

    # Audience mode
    if audience_mode not in VALID_AUDIENCE_MODES:
        return {
            "error": f"Invalid audience_mode: '{audience_mode}'.",
            "valid_values": VALID_AUDIENCE_MODES,
            "blocked_at": "input_validation",
        }

    # Both budgets
    if daily_budget is not None and lifetime_budget is not None:
        return {
            "error": "Cannot set both daily_budget and lifetime_budget. Choose one.",
            "blocked_at": "input_validation",
        }

    # Lifetime budget requires end_time
    if lifetime_budget is not None and not end_time:
        return {
            "error": "lifetime_budget requires end_time.",
            "blocked_at": "input_validation",
        }

    # end_time before start_time
    if start_time and end_time and end_time <= start_time:
        return {
            "error": f"end_time ({end_time}) must be after start_time ({start_time}).",
            "blocked_at": "input_validation",
        }

    # Parse targeting
    targeting_dict = None
    if targeting_json:
        try:
            targeting_dict = _json.loads(targeting_json)
            if not isinstance(targeting_dict, dict):
                return {"error": "targeting_json must parse to a JSON object.", "blocked_at": "input_validation"}
        except _json.JSONDecodeError as e:
            return {"error": f"Malformed targeting_json: {e}", "blocked_at": "input_validation"}

    # Parse promoted_object
    promoted_object_dict = None
    if promoted_object_json:
        try:
            promoted_object_dict = _json.loads(promoted_object_json)
            if not isinstance(promoted_object_dict, dict):
                return {"error": "promoted_object_json must parse to a JSON object.", "blocked_at": "input_validation"}
        except _json.JSONDecodeError as e:
            return {"error": f"Malformed promoted_object_json: {e}", "blocked_at": "input_validation"}

    # Parse ICP signals
    icp_signals_dict = None
    if icp_signals_json:
        try:
            icp_signals_dict = _json.loads(icp_signals_json)
        except _json.JSONDecodeError as e:
            return {"error": f"Malformed icp_signals_json: {e}", "blocked_at": "input_validation"}

    # Targeting required for manual and existing_audience modes
    if audience_mode in ("manual", "existing_audience") and not targeting_dict:
        return {
            "error": f"audience_mode='{audience_mode}' requires targeting_json.",
            "blocked_at": "input_validation",
        }

    # ============================================================
    # Step 1: Parent campaign inspection
    # ============================================================

    try:
        parent = api_client.graph_get(
            f"/{campaign_id}",
            fields=[
                "id", "name", "objective", "status", "effective_status",
                "daily_budget", "lifetime_budget", "bid_strategy",
                "special_ad_categories",
            ],
        )
    except MetaAPIError as e:
        return {
            "error": f"Cannot read parent campaign {campaign_id}: {e}",
            "blocked_at": "parent_inspection",
        }

    parent_objective = parent.get("objective", "")
    parent_status = parent.get("effective_status", "")

    # Parent must exist and not be deleted
    if parent_status in ("DELETED", "ARCHIVED"):
        return {
            "error": f"Parent campaign {campaign_id} is {parent_status}. Cannot create ad sets under it.",
            "blocked_at": "parent_inspection",
        }

    # Optimization goal vs objective compatibility
    opt_upper = optimization_goal.upper().strip()
    valid_goals = OPTIMIZATION_GOALS.get(parent_objective, [])
    if valid_goals and opt_upper not in valid_goals:
        return {
            "error": f"optimization_goal '{opt_upper}' is not compatible with campaign objective '{parent_objective}'.",
            "valid_goals_for_objective": valid_goals,
            "blocked_at": "input_validation",
        }

    # Promoted object requirement check
    if parent_objective in PROMOTED_OBJECT_REQUIRED and not promoted_object_dict:
        return {
            "error": f"Campaign objective '{parent_objective}' requires promoted_object_json ({PROMOTED_OBJECT_REQUIRED[parent_objective]}).",
            "blocked_at": "input_validation",
        }

    # ============================================================
    # Step 1.5: Tracking enforcement - HARD GATE
    # ============================================================
    from meta_ads_mcp.engine.tracking_gate import enforce_tracking

    # Resolve account pixel for enforcement context
    account_pixel_id = None
    try:
        pixels_result = api_client.graph_get(
            f"/{account_id}/adspixels",
            fields=["id", "name"],
        )
        account_pixels = pixels_result.get("data", [])
        if account_pixels:
            account_pixel_id = account_pixels[0].get("id")
    except MetaAPIError:
        pass

    tracking_result = enforce_tracking(
        objective=parent_objective,
        optimization_goal=opt_upper,
        promoted_object=promoted_object_dict,
        destination_url="",  # Not available at adset level
        cta_type="",
        account_pixel_id=account_pixel_id,
        explicit_tracking_mode=explicit_tracking_mode,
    )

    tracking_status = tracking_result

    if tracking_result["block_write"]:
        return {
            "error": "Tracking enforcement BLOCKED write. " + "; ".join(tracking_result["issues"]),
            "tracking_status": tracking_result,
            "required_fix": tracking_result["required_fix"],
            "blocked_at": "tracking_enforcement",
        }

    # ============================================================
    # Step 2: ABO vs CBO enforcement
    # ============================================================

    budget_model, budget_reason = _detect_budget_model(parent)

    if budget_model == "CBO":
        # CBO: ad set MUST NOT have budget
        if daily_budget is not None or lifetime_budget is not None:
            return {
                "error": "Parent campaign uses CBO (has campaign-level budget). Ad set MUST NOT set its own budget.",
                "budget_model": "CBO",
                "budget_logic_reason": budget_reason,
                "parent_campaign_budget_model_detected": "CBO",
                "blocked_at": "budget_model_enforcement",
            }
    else:
        # ABO: ad set MUST have budget
        if daily_budget is None and lifetime_budget is None:
            return {
                "error": "Parent campaign uses ABO (no campaign-level budget). Ad set MUST provide daily_budget or lifetime_budget.",
                "budget_model": "ABO",
                "budget_logic_reason": budget_reason,
                "parent_campaign_budget_model_detected": "ABO",
                "blocked_at": "budget_model_enforcement",
            }

    # ============================================================
    # Step 2.5: Advantage+ audience enforcement
    # ============================================================

    from meta_ads_mcp.engine.audience import build_audience_spec, validate_audience_for_api

    # Determine geo from targeting or default
    geo_countries = None
    if targeting_dict and targeting_dict.get("geo_locations", {}).get("countries"):
        geo_countries = targeting_dict["geo_locations"]["countries"]

    audience_result = build_audience_spec(
        targeting_input=targeting_dict,
        audience_mode=audience_mode if audience_mode in ("advantage_plus", "restricted") else "advantage_plus",
        icp_name=icp_name,
        icp_signals=icp_signals_dict,
        geo_countries=geo_countries,
        age_min=targeting_dict.get("age_min") if targeting_dict else None,
        age_max=targeting_dict.get("age_max") if targeting_dict else None,
        experiment_type=experiment_type,
    )

    audience_warnings = audience_result.get("warnings", [])
    audience_strategy = audience_result.get("audience_strategy", {})
    effective_targeting_from_audience = audience_result["targeting"]

    # Validate audience before proceeding
    audience_validation = validate_audience_for_api(
        effective_targeting_from_audience,
        audience_mode=audience_mode if audience_mode in ("advantage_plus", "restricted") else "advantage_plus",
    )

    if not audience_validation["validation_passed"]:
        blockers = [i for i in audience_validation["issues"] if i["severity"] == "block"]
        return {
            "error": "Audience validation failed. " + "; ".join(b["message"] for b in blockers),
            "audience_validation": audience_validation,
            "audience_strategy": audience_strategy,
            "blocked_at": "audience_enforcement",
            "fix": "Enable Advantage+ (default) or set audience_mode='restricted' with valid reason.",
        }

    # ============================================================
    # Step 3: Build payload
    # ============================================================

    # --- Naming enforcement ---
    from meta_ads_mcp.engine.naming_gate import enforce_naming

    adset_naming_inputs = None
    if naming_audience_type or naming_age_range:
        adset_naming_inputs = {
            "audience_type": naming_audience_type or "",
            "age_range": naming_age_range or "",
            "geo": naming_geo,
            "exclusion_flag": naming_exclusion_flag,
        }

    naming_result = enforce_naming(
        proposed_name=name,
        object_type="adset",
        naming_inputs=adset_naming_inputs,
    )

    if naming_result["critical_block"]:
        return {
            "error": f"Naming enforcement BLOCKED: {naming_result.get('fix_suggestion', 'Invalid name')}",
            "naming_result": naming_result,
            "blocked_at": "naming_enforcement",
        }

    effective_name = naming_result["final_name"] or name

    payload = {
        "name": effective_name,
        "campaign_id": campaign_id,
        "optimization_goal": opt_upper,
        "billing_event": billing_upper,
        "status": "PAUSED",
    }

    if budget_model == "ABO":
        if daily_budget is not None:
            payload["daily_budget"] = currency_to_cents(daily_budget)
        elif lifetime_budget is not None:
            payload["lifetime_budget"] = currency_to_cents(lifetime_budget)

    # Use audience-enforced targeting
    if effective_targeting_from_audience:
        payload["targeting"] = effective_targeting_from_audience
    elif audience_mode == "broad":
        payload["targeting"] = {
            "geo_locations": {"countries": ["GR"]},
            "targeting_automation": {"advantage_audience": 1},
        }

    if promoted_object_dict:
        payload["promoted_object"] = promoted_object_dict

    if start_time:
        payload["start_time"] = start_time
    if end_time:
        payload["end_time"] = end_time

    # ============================================================
    # Step 4: Pre-write validation
    # ============================================================

    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    validation_result = run_validation(
        action_class=ActionClass.CREATE,
        target_account_id=account_id,
        target_object_type="adset",
        target_object_id=None,
        payload=payload,
        safety_tier=3,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Ad set NOT created.",
            "validation": validation_dict,
            "budget_model": budget_model,
            "blocked_at": "pre_write_validation",
        }

    # ============================================================
    # Step 5: Pre-write snapshot
    # ============================================================

    try:
        existing = api_client.graph_get(
            f"/{campaign_id}/adsets",
            fields=["id"],
            params={"limit": "0"},
        )
        pre_adset_count = len(existing.get("data", []))
    except MetaAPIError:
        pre_adset_count = "unknown"

    rollback_ref = f"create_adset_{campaign_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # ============================================================
    # Step 6: API call
    # ============================================================

    # Meta expects form-encoded with JSON-serialized nested fields
    api_payload: dict = {
        "name": effective_name,
        "campaign_id": campaign_id,
        "optimization_goal": opt_upper,
        "billing_event": billing_upper,
        "status": "PAUSED",
    }

    if budget_model == "ABO":
        if daily_budget is not None:
            api_payload["daily_budget"] = currency_to_cents(daily_budget)
        elif lifetime_budget is not None:
            api_payload["lifetime_budget"] = currency_to_cents(lifetime_budget)

    # Use audience-enforced targeting (Advantage+ already applied in Step 2.5)
    effective_targeting = None
    if effective_targeting_from_audience:
        effective_targeting = effective_targeting_from_audience
    elif audience_mode == "broad":
        effective_targeting = {
            "geo_locations": {"countries": ["GR"]},
            "targeting_automation": {"advantage_audience": 1},
        }

    if effective_targeting:
        api_payload["targeting"] = _json.dumps(effective_targeting)

    # ABO ad sets require explicit bid_strategy
    if budget_model == "ABO":
        parent_bid = parent.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
        api_payload["bid_strategy"] = parent_bid or "LOWEST_COST_WITHOUT_CAP"

    if promoted_object_dict:
        api_payload["promoted_object"] = _json.dumps(promoted_object_dict)

    if start_time:
        api_payload["start_time"] = start_time
    if end_time:
        api_payload["end_time"] = end_time

    try:
        result = api_client.graph_post(
            f"/{account_id}/adsets",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during ad set creation: {e}",
            "validation": validation_dict,
            "budget_model": budget_model,
            "blocked_at": "api_call",
            "rollback_reference": rollback_ref,
        }

    adset_id = result.get("id")
    if not adset_id:
        return {
            "error": "Ad set creation returned no ID.",
            "api_response": result,
            "blocked_at": "api_response",
        }

    # ============================================================
    # Step 7: Post-write verification
    # ============================================================

    verification = {
        "adset_id": adset_id,
        "status_verified": False,
        "campaign_id_verified": False,
        "optimization_goal_verified": False,
        "billing_event_verified": False,
        "name_verified": False,
        "budget_verified": False,
        "targeting_verified": False,
        "critical_mismatch": False,
    }

    try:
        created = api_client.graph_get(
            f"/{adset_id}",
            fields=[
                "id", "name", "status", "effective_status", "campaign_id",
                "optimization_goal", "billing_event", "daily_budget", "lifetime_budget",
                "targeting",
            ],
        )

        # Verify status
        actual_status = created.get("status", "")
        if actual_status == "PAUSED":
            verification["status_verified"] = True
        else:
            verification["critical_mismatch"] = True
            verification["status_expected"] = "PAUSED"
            verification["status_actual"] = actual_status
            logger.critical("CRITICAL: Ad set %s created with status %s!", adset_id, actual_status)

        # Verify campaign_id
        actual_campaign = created.get("campaign_id", "")
        if actual_campaign == campaign_id:
            verification["campaign_id_verified"] = True
        else:
            verification["critical_mismatch"] = True
            verification["campaign_id_expected"] = campaign_id
            verification["campaign_id_actual"] = actual_campaign

        # Verify optimization_goal
        actual_opt = created.get("optimization_goal", "")
        if actual_opt == opt_upper:
            verification["optimization_goal_verified"] = True
        else:
            verification["optimization_goal_expected"] = opt_upper
            verification["optimization_goal_actual"] = actual_opt

        # Verify name
        actual_name = created.get("name", "")
        if actual_name == effective_name:
            verification["name_verified"] = True
        else:
            verification["name_expected"] = name
            verification["name_actual"] = actual_name
            verification["name_note"] = "Name mismatch - possible encoding issue"

        verification["effective_status"] = created.get("effective_status")

        # Verify billing_event
        actual_billing = created.get("billing_event", "")
        if actual_billing == billing_upper:
            verification["billing_event_verified"] = True
        else:
            verification["billing_event_expected"] = billing_upper
            verification["billing_event_actual"] = actual_billing

        # Verify targeting presence
        actual_targeting = created.get("targeting")
        if actual_targeting and isinstance(actual_targeting, dict):
            verification["targeting_verified"] = True
            # Check geo_locations present
            if not actual_targeting.get("geo_locations"):
                verification["targeting_note"] = "Targeting returned but no geo_locations found"
        else:
            verification["targeting_note"] = "No targeting returned in read-back"

        # Budget verification
        if budget_model == "ABO":
            actual_daily = created.get("daily_budget")
            actual_lifetime = created.get("lifetime_budget")
            if daily_budget is not None:
                verification["budget_verified"] = actual_daily == currency_to_cents(daily_budget)
                verification["budget_actual"] = actual_daily
            elif lifetime_budget is not None:
                verification["budget_verified"] = actual_lifetime == currency_to_cents(lifetime_budget)
                verification["budget_actual"] = actual_lifetime
        else:
            # CBO: verify no ad set budget was set
            actual_daily = created.get("daily_budget")
            actual_lifetime = created.get("lifetime_budget")
            verification["budget_verified"] = not actual_daily and not actual_lifetime

    except MetaAPIError as e:
        verification["verification_error"] = str(e)

    # ============================================================
    # Step 8: Mutation log entry
    # ============================================================

    budget_display = "none (CBO)"
    if daily_budget is not None:
        budget_display = f"EUR {daily_budget:.2f}/day (ABO)"
    elif lifetime_budget is not None:
        budget_display = f"EUR {lifetime_budget:.2f} lifetime (ABO)"

    aa_status = audience_strategy.get("advantage_plus_status", "unknown")
    log_entry = (
        f"### [{timestamp}] CREATE adset\n"
        f"- **Account:** {account_id}\n"
        f"- **Campaign:** {campaign_id} ({parent.get('name', '?')})\n"
        f"- **Ad Set ID:** {adset_id}\n"
        f"- **Name:** {name}\n"
        f"- **Optimization:** {opt_upper}\n"
        f"- **Billing:** {billing_upper}\n"
        f"- **Budget model:** {budget_model} - {budget_display}\n"
        f"- **Status:** PAUSED (enforced)\n"
        f"- **Audience mode:** {audience_mode} | Advantage+: {aa_status}\n"
        f"- **Targeting strategy:** {audience_strategy.get('targeting_strategy', 'unknown')}\n"
        f"- **ICP signals:** {audience_strategy.get('icp_name', 'none')}\n"
        f"- **Validation:** {validation_result.verdict.value}\n"
        f"- **Verification:** status={'OK' if verification['status_verified'] else 'MISMATCH'}, "
        f"campaign={'OK' if verification['campaign_id_verified'] else 'MISMATCH'}, "
        f"opt={'OK' if verification['optimization_goal_verified'] else 'MISMATCH'}, "
        f"billing={'OK' if verification['billing_event_verified'] else 'MISMATCH'}, "
        f"budget={'OK' if verification['budget_verified'] else 'MISMATCH'}, "
        f"targeting={'OK' if verification['targeting_verified'] else 'MISSING'}, "
        f"name={'OK' if verification['name_verified'] else 'MISMATCH'}\n"
        f"- **Rollback ref:** {rollback_ref}\n"
    )

    return {
        "adset_id": adset_id,
        "status": "PAUSED",
        "campaign_id": campaign_id,
        "optimization_goal": opt_upper,
        "billing_event": billing_upper,
        "budget_model": budget_model,
        "budget_logic_reason": budget_reason,
        "parent_campaign_budget_model_detected": budget_model,
        "budget_validation_result": "passed",
        "tracking_status": tracking_status,
        "audience_strategy": audience_strategy,
        "audience_warnings": audience_warnings,
        "naming_enforcement": naming_result,
        "name": effective_name,
        "validation": validation_dict,
        "verification": verification,
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


# --- Phase C.2: Ad set update ---

@mcp.tool()
def update_adset(
    adset_id: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    daily_budget: Optional[float] = None,
    lifetime_budget: Optional[float] = None,
    targeting_json: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> dict:
    """
    Update an existing ad set. Supervised write - validates before applying.

    Takes a pre-write snapshot for rollback, validates the update payload,
    applies via Meta API, and verifies post-write state.

    Note on budgets: ABO/CBO rules are enforced. If the parent campaign uses CBO
    (has campaign-level budget), ad set budget updates are blocked. Budget updates
    are only allowed for ABO ad sets (parent campaign has no budget).

    Note on targeting: targeting_json must be a valid Meta targeting spec JSON object.
    Partial updates are supported - Meta merges provided fields with existing targeting.
    To clear a field, set it explicitly to null in the JSON.

    Args:
        adset_id: Ad set ID to update.
        name: New ad set name. Subject to naming enforcement.
        status: New status. Allowed: 'PAUSED', 'ACTIVE', 'ARCHIVED'.
            Activating requires confirmation-level validation.
        daily_budget: New daily budget in currency units (e.g., 15.0 for EUR 15).
            Only allowed for ABO ad sets. Mutually exclusive with lifetime_budget.
        lifetime_budget: New lifetime budget in currency units.
            Only allowed for ABO ad sets. Mutually exclusive with daily_budget.
        targeting_json: JSON string of targeting spec to apply.
            Example: '{"geo_locations":{"countries":["GR"]},"age_min":25,"age_max":55}'
        start_time: New start time (ISO 8601 format).
        end_time: New end time (ISO 8601 format).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- At least one field must be provided ---
    if all(v is None for v in [name, status, daily_budget, lifetime_budget, targeting_json, start_time, end_time]):
        return {
            "error": "No update fields provided. Specify at least one field to update.",
            "supported_fields": ["name", "status", "daily_budget", "lifetime_budget", "targeting_json", "start_time", "end_time"],
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

    # --- Targeting validation ---
    targeting_dict = None
    if targeting_json is not None:
        try:
            targeting_dict = _json.loads(targeting_json)
            if not isinstance(targeting_dict, dict):
                return {
                    "error": "targeting_json must parse to a JSON object.",
                    "blocked_at": "input_validation",
                }
        except _json.JSONDecodeError as e:
            return {
                "error": f"Malformed targeting_json: {e}",
                "blocked_at": "input_validation",
            }

    # --- Step 0: Pre-write snapshot ---
    api_client._ensure_initialized()
    try:
        current = api_client.graph_get(
            f"/{adset_id}",
            fields=["id", "name", "status", "effective_status", "campaign_id",
                     "daily_budget", "lifetime_budget", "targeting",
                     "optimization_goal", "start_time", "end_time", "account_id"],
        )
    except MetaAPIError as e:
        return {
            "error": f"Cannot read ad set {adset_id} for pre-update snapshot: {e}",
            "blocked_at": "pre_snapshot",
        }

    account_id = current.get("account_id", "")
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    campaign_id = current.get("campaign_id", "")

    rollback_ref = f"update_adset_{adset_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    # --- Step 1: ABO/CBO enforcement for budget updates ---
    if daily_budget is not None or lifetime_budget is not None:
        try:
            parent_campaign = api_client.graph_get(
                f"/{campaign_id}",
                fields=["id", "daily_budget", "lifetime_budget"],
            )
        except MetaAPIError as e:
            return {
                "error": f"Cannot read parent campaign {campaign_id} for budget model check: {e}",
                "blocked_at": "budget_model_enforcement",
            }
        budget_model, budget_reason = _detect_budget_model(parent_campaign)

        if budget_model == "CBO":
            return {
                "error": f"Cannot update ad set budget: parent campaign uses CBO. {budget_reason}",
                "blocked_at": "budget_model_enforcement",
                "budget_model": "CBO",
                "campaign_id": campaign_id,
            }

    # --- Step 2: Naming enforcement (if name is being updated) ---
    effective_name = None
    naming_result = None
    if name is not None:
        from meta_ads_mcp.engine.naming_gate import enforce_naming

        naming_result = enforce_naming(
            proposed_name=name,
            object_type="adset",
            naming_inputs=None,
        )

        if naming_result["critical_block"]:
            return {
                "error": f"Naming enforcement BLOCKED: {naming_result.get('fix_suggestion', 'Invalid name')}",
                "naming_result": naming_result,
                "blocked_at": "naming_enforcement",
            }

        effective_name = naming_result["final_name"] or name

    # --- Step 3: Build update payload ---
    api_payload = {}

    if effective_name is not None:
        api_payload["name"] = effective_name
    if status is not None:
        api_payload["status"] = status
    if daily_budget is not None:
        api_payload["daily_budget"] = currency_to_cents(daily_budget)
    if lifetime_budget is not None:
        api_payload["lifetime_budget"] = currency_to_cents(lifetime_budget)
    if targeting_dict is not None:
        api_payload["targeting"] = _json.dumps(targeting_dict, ensure_ascii=False)
    if start_time is not None:
        api_payload["start_time"] = start_time
    if end_time is not None:
        api_payload["end_time"] = end_time

    # --- Step 4: Pre-write validation ---
    from meta_ads_mcp.validators.runner import run_validation, ActionClass

    action_class = ActionClass.ACTIVATE if status == "ACTIVE" else ActionClass.MODIFY_ACTIVE

    validation_result = run_validation(
        action_class=action_class,
        target_account_id=account_id,
        target_object_type="adset",
        target_object_id=adset_id,
        payload=api_payload,
        safety_tier=3,
    )

    validation_dict = validation_result.to_dict()

    if validation_result.verdict.value == "fail":
        return {
            "error": "Pre-write validation failed. Ad set NOT updated.",
            "validation": validation_dict,
            "blocked_at": "pre_write_validation",
        }

    if validation_result.verdict.value == "requires_confirmation" and status == "ACTIVE":
        return {
            "status": "requires_confirmation",
            "message": "Activating an ad set requires explicit confirmation. Review validation and re-submit.",
            "validation": validation_dict,
            "adset_id": adset_id,
            "current_status": current.get("status"),
            "requested_status": "ACTIVE",
        }

    # --- Step 5: API call - update ad set ---
    try:
        result = api_client.graph_post(
            f"/{adset_id}",
            data=api_payload,
        )
    except MetaAPIError as e:
        return {
            "error": f"Meta API error during ad set update: {e}",
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

    # --- Step 6: Post-write verification ---
    verification = {
        "adset_id": adset_id,
        "fields_updated": list(api_payload.keys()),
        "mismatches": [],
    }

    try:
        updated = api_client.graph_get(
            f"/{adset_id}",
            fields=["id", "name", "status", "effective_status",
                     "daily_budget", "lifetime_budget", "targeting",
                     "start_time", "end_time"],
        )

        if effective_name is not None:
            actual_name = updated.get("name", "")
            if actual_name != effective_name:
                verification["mismatches"].append({
                    "field": "name", "expected": effective_name, "actual": actual_name,
                })

        if status is not None:
            actual_status = updated.get("status", "")
            if actual_status != status:
                verification["mismatches"].append({
                    "field": "status", "expected": status, "actual": actual_status,
                })

        if daily_budget is not None:
            actual_budget = updated.get("daily_budget", "")
            expected_cents = currency_to_cents(daily_budget)
            if str(actual_budget) != expected_cents:
                verification["mismatches"].append({
                    "field": "daily_budget", "expected_cents": expected_cents, "actual_cents": actual_budget,
                })

        if lifetime_budget is not None:
            actual_budget = updated.get("lifetime_budget", "")
            expected_cents = currency_to_cents(lifetime_budget)
            if str(actual_budget) != expected_cents:
                verification["mismatches"].append({
                    "field": "lifetime_budget", "expected_cents": expected_cents, "actual_cents": actual_budget,
                })

        verification["post_update_status"] = updated.get("status")
        verification["post_update_effective_status"] = updated.get("effective_status")
        verification["verified"] = len(verification["mismatches"]) == 0

    except MetaAPIError as e:
        verification["verification_error"] = str(e)
        verification["verified"] = False
        verification["note"] = "Ad set was updated but post-verification read failed."

    # --- Step 7: Mutation log entry ---
    fields_summary = ", ".join(f"{k}={v}" for k, v in api_payload.items())
    log_entry = (
        f"### [{timestamp}] UPDATE adset\n"
        f"- **Ad Set ID:** {adset_id}\n"
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
        "adset_id": adset_id,
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
            "targeting": current.get("targeting"),
            "start_time": current.get("start_time"),
            "end_time": current.get("end_time"),
        },
        "rollback_reference": rollback_ref,
        "mutation_log_entry": log_entry,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
