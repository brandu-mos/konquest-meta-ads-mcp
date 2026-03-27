"""
Tracking Enforcement Gate.

Hard production gate that blocks writes when tracking setup is
incompatible with the intended conversion flow.

No warnings. No fallbacks. No silent downgrades.
Either tracking is correct for the intended flow, or the write is blocked.

## Tracking Modes
- website_pixel: pixel_id + custom_event_type (website conversions)
- instant_form: page_id only, explicit intent (Lead Ads / Instant Forms)
- messaging: WhatsApp/Messenger flow
- page_engagement: Page likes, post engagement
- offline_only: Offline event sets
- unknown: Unresolved - always blocked for conversion objectives

## Intended Flow Detection
Inferred from: objective + optimization_goal + promoted_object + destination_url + CTA

## Hard Block Cases
1. Website conversion without pixel_id
2. Website conversion without custom_event_type
3. OUTCOME_SALES with no pixel path
4. OUTCOME_LEADS with website intent but no pixel
5. Objective / optimization_goal / promoted_object incompatibility
6. Website URL present but tracking resolved to page-only (without explicit instant_form)
7. Pixel exists on account but not used where website tracking is intended
"""
import logging
import re
from typing import Optional

logger = logging.getLogger("meta-ads-mcp.tracking_gate")

# ── Objective -> required tracking ──
OBJECTIVE_TRACKING_REQUIREMENTS = {
    "OUTCOME_SALES": {
        "required_mode": "website_pixel",
        "required_promoted_object": ["pixel_id", "custom_event_type"],
        "valid_events": ["PURCHASE", "ADD_TO_CART", "INITIATED_CHECKOUT", "ADD_PAYMENT_INFO"],
        "description": "Website sales require pixel + purchase/cart event",
    },
    "OUTCOME_LEADS": {
        "required_mode": "website_pixel",  # default, can override to instant_form
        "required_promoted_object": ["pixel_id", "custom_event_type"],
        "valid_events": ["LEAD", "COMPLETE_REGISTRATION", "CONTACT", "SUBMIT_APPLICATION"],
        "allowed_overrides": ["instant_form", "messaging"],
        "description": "Website leads require pixel + lead event. Instant forms require explicit page_id intent.",
    },
    "OUTCOME_TRAFFIC": {
        "required_mode": None,  # Traffic doesn't require conversion tracking
        "description": "Traffic campaigns don't require conversion tracking",
    },
    "OUTCOME_AWARENESS": {
        "required_mode": None,
        "description": "Awareness campaigns don't require conversion tracking",
    },
    "OUTCOME_ENGAGEMENT": {
        "required_mode": None,
        "description": "Engagement campaigns don't require conversion tracking",
    },
}

# ── Optimization goal -> tracking mode mapping ──
OPTGOAL_REQUIRES_PIXEL = {
    "OFFSITE_CONVERSIONS", "VALUE",
}

OPTGOAL_WEBSITE_COMPATIBLE = {
    "OFFSITE_CONVERSIONS", "VALUE", "LANDING_PAGE_VIEWS", "LINK_CLICKS",
}

OPTGOAL_FORM_COMPATIBLE = {
    "LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS",
}


def detect_intended_flow(
    objective: str,
    optimization_goal: str = "",
    promoted_object: Optional[dict] = None,
    destination_url: str = "",
    cta_type: str = "",
    explicit_tracking_mode: Optional[str] = None,
) -> dict:
    """
    Detect the intended conversion flow from campaign/adset parameters.

    Returns:
        {intended_flow, confidence, signals, description}
    """
    signals = []
    flow = "unknown"

    # Explicit override wins
    if explicit_tracking_mode:
        return {
            "intended_flow": explicit_tracking_mode,
            "confidence": "explicit",
            "signals": [f"Operator declared tracking_mode='{explicit_tracking_mode}'"],
            "description": f"Explicitly set to {explicit_tracking_mode}",
        }

    # Signal 1: Objective
    obj_upper = objective.upper() if objective else ""
    if obj_upper in ("OUTCOME_SALES",):
        signals.append("OUTCOME_SALES -> website_pixel")
        flow = "website_pixel"
    elif obj_upper == "OUTCOME_LEADS":
        signals.append("OUTCOME_LEADS -> website_pixel (default, overridable)")
        flow = "website_pixel"

    # Signal 2: Optimization goal
    opt_upper = optimization_goal.upper() if optimization_goal else ""
    if opt_upper in OPTGOAL_REQUIRES_PIXEL:
        signals.append(f"{opt_upper} requires pixel")
        flow = "website_pixel"
    elif opt_upper in OPTGOAL_FORM_COMPATIBLE:
        if flow != "website_pixel":
            signals.append(f"{opt_upper} compatible with instant_form")
            flow = "instant_form"

    # Signal 3: Promoted object
    if promoted_object:
        has_pixel = "pixel_id" in promoted_object
        has_page = "page_id" in promoted_object
        has_event = "custom_event_type" in promoted_object

        if has_pixel:
            signals.append("promoted_object has pixel_id -> website_pixel")
            flow = "website_pixel"
        elif has_page and not has_pixel:
            signals.append("promoted_object has page_id only -> instant_form")
            if flow == "website_pixel":
                signals.append("CONFLICT: objective suggests website but promoted_object is page-only")
            else:
                flow = "instant_form"

    # Signal 4: Destination URL
    if destination_url and destination_url.startswith("http"):
        signals.append(f"destination_url present -> website flow likely")
        if flow == "unknown":
            flow = "website_pixel"

    # Signal 5: CTA type
    cta_upper = cta_type.upper() if cta_type else ""
    if cta_upper in ("SEND_WHATSAPP_MESSAGE", "MESSAGE_PAGE"):
        signals.append(f"CTA {cta_upper} -> messaging")
        flow = "messaging"

    confidence = "high" if len(signals) >= 2 else ("medium" if signals else "low")

    return {
        "intended_flow": flow,
        "confidence": confidence,
        "signals": signals,
        "description": f"Detected flow: {flow} based on {len(signals)} signals",
    }


def enforce_tracking(
    objective: str,
    optimization_goal: str = "",
    promoted_object: Optional[dict] = None,
    destination_url: str = "",
    cta_type: str = "",
    account_pixel_id: Optional[str] = None,
    explicit_tracking_mode: Optional[str] = None,
) -> dict:
    """
    Hard enforcement gate for tracking configuration.

    Args:
        objective: Campaign objective (OUTCOME_SALES, etc.)
        optimization_goal: Ad set optimization goal.
        promoted_object: Parsed promoted_object dict.
        destination_url: Ad destination URL.
        cta_type: CTA type.
        account_pixel_id: Known pixel ID for the account (from registry).
        explicit_tracking_mode: Operator-declared mode override.

    Returns:
        {tracking_mode, intended_flow, tracking_valid, block_write,
         issues, required_fix, enforcement_level}
    """
    obj_upper = objective.upper() if objective else ""
    opt_upper = optimization_goal.upper() if optimization_goal else ""

    # Detect intended flow
    flow_result = detect_intended_flow(
        objective=objective,
        optimization_goal=optimization_goal,
        promoted_object=promoted_object,
        destination_url=destination_url,
        cta_type=cta_type,
        explicit_tracking_mode=explicit_tracking_mode,
    )
    intended_flow = flow_result["intended_flow"]

    # Resolve actual tracking mode from promoted_object
    actual_mode = "unknown"
    pixel_id = None
    event_type = None

    if promoted_object:
        if "pixel_id" in promoted_object:
            actual_mode = "website_pixel"
            pixel_id = promoted_object["pixel_id"]
            event_type = promoted_object.get("custom_event_type")
        elif "page_id" in promoted_object:
            actual_mode = "instant_form"

    issues = []
    required_fix = []
    block_write = False

    # ── Objective requirements check ──
    obj_req = OBJECTIVE_TRACKING_REQUIREMENTS.get(obj_upper, {})

    if obj_req.get("required_mode"):
        required_mode = obj_req["required_mode"]

        # Check if explicit override is allowed
        if explicit_tracking_mode and explicit_tracking_mode in obj_req.get("allowed_overrides", []):
            # Explicit override to instant_form/messaging is allowed for OUTCOME_LEADS
            pass
        elif intended_flow == "website_pixel" and actual_mode != "website_pixel":
            # Website flow intended but not configured
            block_write = True

            if actual_mode == "instant_form":
                issues.append(
                    f"Intended flow is website_pixel but promoted_object has only page_id (instant_form). "
                    f"For website conversion tracking, use pixel_id + custom_event_type."
                )
                required_fix.append(
                    f'Set promoted_object to: {{"pixel_id": "{account_pixel_id or "YOUR_PIXEL_ID"}", '
                    f'"custom_event_type": "{obj_req["valid_events"][0] if obj_req.get("valid_events") else "LEAD"}"}}'
                )
                if account_pixel_id:
                    required_fix.append(
                        f"Account pixel available: {account_pixel_id}. "
                        f"Or set explicit_tracking_mode='instant_form' if using Lead Ads."
                    )
            elif actual_mode == "unknown":
                issues.append(
                    f"Objective {obj_upper} requires promoted_object but none provided."
                )
                if account_pixel_id:
                    required_fix.append(
                        f'Add promoted_object: {{"pixel_id": "{account_pixel_id}", '
                        f'"custom_event_type": "{obj_req["valid_events"][0] if obj_req.get("valid_events") else "LEAD"}"}}'
                    )
                else:
                    required_fix.append(
                        "Install a Meta Pixel on the website, then add pixel_id to promoted_object."
                    )

    # ── Pixel-specific validation for website_pixel mode ──
    if intended_flow == "website_pixel" and actual_mode == "website_pixel":
        # Check pixel_id present
        if not pixel_id:
            block_write = True
            issues.append("website_pixel mode but pixel_id is missing from promoted_object.")
            required_fix.append("Add pixel_id to promoted_object.")

        # Check custom_event_type present
        if not event_type:
            block_write = True
            issues.append("website_pixel mode but custom_event_type is missing. Cannot optimize without event.")
            valid = obj_req.get("valid_events", ["LEAD"])
            required_fix.append(f"Add custom_event_type to promoted_object. Valid for {obj_upper}: {valid}")

        # Check event type is valid for objective
        if event_type and obj_req.get("valid_events"):
            if event_type.upper() not in [e.upper() for e in obj_req["valid_events"]]:
                issues.append(
                    f"custom_event_type '{event_type}' is not standard for {obj_upper}. "
                    f"Valid events: {obj_req['valid_events']}. Proceeding but flagged."
                )
                # This is a warning, not a block - Meta may accept non-standard events

    # ── Optimization goal compatibility ──
    if opt_upper in OPTGOAL_REQUIRES_PIXEL and actual_mode != "website_pixel":
        block_write = True
        issues.append(
            f"optimization_goal '{opt_upper}' requires website pixel tracking "
            f"but tracking_mode is '{actual_mode}'."
        )
        required_fix.append(
            f"Either change optimization_goal to a non-pixel goal, "
            f"or add pixel_id + custom_event_type to promoted_object."
        )

    # ── Website URL + page-only conflict ──
    if (destination_url and destination_url.startswith("http")
            and actual_mode == "instant_form"
            and intended_flow == "website_pixel"
            and not explicit_tracking_mode):
        block_write = True
        issues.append(
            f"destination_url points to website ({destination_url[:40]}...) "
            f"but promoted_object is page-only (instant_form). "
            f"Website conversions will NOT be tracked."
        )
        required_fix.append(
            "Add pixel_id + custom_event_type for website tracking, "
            "or set explicit_tracking_mode='instant_form' if using Lead Ads."
        )

    # ── Pixel exists on account but not used ──
    if (account_pixel_id and not pixel_id
            and intended_flow == "website_pixel"
            and not explicit_tracking_mode):
        if not block_write:  # Don't double-block
            block_write = True
        issues.append(
            f"Account has pixel {account_pixel_id} but it's not in promoted_object. "
            f"Website conversions cannot be tracked."
        )
        required_fix.append(
            f'Use promoted_object: {{"pixel_id": "{account_pixel_id}", "custom_event_type": "LEAD"}}'
        )

    # ── Build result ──
    tracking_valid = len(issues) == 0

    return {
        "tracking_mode": actual_mode,
        "intended_flow": intended_flow,
        "intended_flow_detection": flow_result,
        "tracking_valid": tracking_valid,
        "block_write": block_write,
        "issues": issues,
        "required_fix": required_fix,
        "enforcement_level": "block" if block_write else "pass",
        "pixel_id": pixel_id,
        "custom_event_type": event_type,
        "account_pixel_available": account_pixel_id,
    }
