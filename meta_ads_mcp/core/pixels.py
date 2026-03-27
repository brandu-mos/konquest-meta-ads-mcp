"""
Pixel and event diagnostic tools.

Provides pixel health checks, event inspection, diagnostic reports,
and Test Events API integration.

Diagnostic-first: outputs classify tracking health and suggest fixes,
not just raw API payloads.

Phase: v1.1 (Read Operations)
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.pixels")

# --- Archetype event requirements ---

REQUIRED_EVENTS = {
    "ecommerce": {
        "critical": ["Purchase"],
        "important": ["AddToCart", "InitiateCheckout", "ViewContent"],
        "optional": ["ViewCategory", "Search", "AddPaymentInfo"],
    },
    "lead_gen": {
        "critical": ["Lead"],
        "important": ["SubmitApplication", "Contact"],
        "optional": ["ViewContent", "Schedule"],
    },
    "awareness": {
        "critical": [],
        "important": ["PageView"],
        "optional": ["ViewContent"],
    },
    "traffic": {
        "critical": [],
        "important": ["PageView", "ViewContent"],
        "optional": ["Lead"],
    },
    "hybrid": {
        "critical": ["Purchase", "Lead"],
        "important": ["AddToCart", "ViewContent", "InitiateCheckout"],
        "optional": ["SubmitApplication", "Contact"],
    },
    "messages": {
        "critical": [],
        "important": ["PageView"],
        "optional": ["Lead", "Contact"],
    },
}

# Events that require value/currency parameters
VALUE_REQUIRED_EVENTS = ["Purchase"]

# Severity levels
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"


def _classify_pixel_health(
    pixel_info: dict,
    events_found: list[str],
    archetype: str,
    diagnostics: list[dict],
) -> dict:
    """
    Classify overall pixel health based on info, events, and archetype requirements.

    Returns health classification with severity-ranked issues.
    """
    issues = []
    last_fired = pixel_info.get("last_fired_time")
    is_unavailable = pixel_info.get("is_unavailable", False)

    # Check pixel existence and availability
    if is_unavailable:
        issues.append({
            "severity": SEVERITY_CRITICAL,
            "check": "pixel_available",
            "message": "Pixel is marked as unavailable",
            "fix": "Check pixel configuration in Events Manager. May need re-creation.",
        })

    # Check last fired time
    if not last_fired:
        issues.append({
            "severity": SEVERITY_CRITICAL,
            "check": "pixel_ever_fired",
            "message": "Pixel has never fired",
            "fix": "Install pixel on website. Verify base code is on all pages.",
        })
        health = "never_fired"
    else:
        # Parse last fired and check recency
        try:
            fired_dt = datetime.fromisoformat(last_fired.replace("+0000", "+00:00").replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            hours_since = (now - fired_dt).total_seconds() / 3600

            if hours_since > 48:
                issues.append({
                    "severity": SEVERITY_HIGH,
                    "check": "pixel_recency",
                    "message": f"Pixel last fired {hours_since:.0f}h ago (> 48h)",
                    "fix": "Verify website is up and pixel code is still installed.",
                })
        except (ValueError, TypeError):
            pass

        health = "healthy"  # Will be downgraded below if needed

    # Check required events by archetype
    reqs = REQUIRED_EVENTS.get(archetype, REQUIRED_EVENTS["hybrid"])
    events_lower = [e.lower() for e in events_found]

    missing_critical = []
    for ev in reqs["critical"]:
        if ev.lower() not in events_lower:
            missing_critical.append(ev)

    missing_important = []
    for ev in reqs["important"]:
        if ev.lower() not in events_lower:
            missing_important.append(ev)

    if missing_critical:
        issues.append({
            "severity": SEVERITY_CRITICAL,
            "check": "required_events",
            "message": f"Missing critical events for {archetype}: {', '.join(missing_critical)}",
            "fix": f"Install {', '.join(missing_critical)} event(s) on the website. For ecommerce, ensure purchase event fires on order confirmation page with value and currency params.",
        })
        if health != "never_fired":
            health = "degraded"

    if missing_important:
        issues.append({
            "severity": SEVERITY_MEDIUM,
            "check": "important_events",
            "message": f"Missing important events for {archetype}: {', '.join(missing_important)}",
            "fix": f"Add {', '.join(missing_important)} event(s) for better optimization data.",
        })
        if health == "healthy":
            health = "partial"

    # Check diagnostics from da_checks
    for diag in diagnostics:
        result = diag.get("result", "")
        if result == "failed":
            issues.append({
                "severity": SEVERITY_HIGH,
                "check": f"da_check_{diag.get('key', 'unknown')}",
                "message": diag.get("description", diag.get("title", "Diagnostic check failed")),
                "fix": diag.get("action_uri", "Check Events Manager for details."),
            })
            if health == "healthy":
                health = "degraded"

    # If no events at all but pixel fired, it's degraded
    if not events_found and last_fired:
        if health == "healthy":
            health = "degraded"

    # Sort issues by severity
    severity_order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3, SEVERITY_INFO: 4}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 5))

    return {
        "health": health,
        "issues": issues,
        "issue_count": len(issues),
        "critical_count": sum(1 for i in issues if i["severity"] == SEVERITY_CRITICAL),
        "events_detected": events_found,
        "archetype": archetype,
    }


@mcp.tool()
def get_pixel_info(pixel_id: str) -> dict:
    """
    Get pixel status, connections, last fired time, and availability.

    Args:
        pixel_id: Pixel ID (numeric string).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{pixel_id}",
            fields=[
                "id", "name", "creation_time", "last_fired_time",
                "is_unavailable", "is_created_by_business",
            ],
        )

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except MetaAPIError:
        raise


@mcp.tool()
def get_pixel_events(pixel_id: str) -> dict:
    """
    Get events received by a pixel in the last 24 hours,
    broken down by event type and hourly counts.

    Args:
        pixel_id: Pixel ID (numeric string).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{pixel_id}/stats",
            params={"aggregation": "event"},
        )

        raw_data = result.get("data", [])

        # Aggregate event counts across all time buckets
        event_totals: dict[str, int] = {}
        hourly_buckets = 0
        for bucket in raw_data:
            hourly_buckets += 1
            for event_entry in bucket.get("data", []):
                event_name = event_entry.get("value", "Unknown")
                count = event_entry.get("count", 0)
                event_totals[event_name] = event_totals.get(event_name, 0) + count

        # Sort by count descending
        sorted_events = sorted(event_totals.items(), key=lambda x: x[1], reverse=True)

        return {
            "pixel_id": pixel_id,
            "time_window": "last_24h",
            "hourly_buckets": hourly_buckets,
            "event_count": len(sorted_events),
            "events": [{"event": name, "count": count} for name, count in sorted_events],
            "event_names": [name for name, _ in sorted_events],
            "total_fires": sum(count for _, count in sorted_events),
            "raw_buckets": len(raw_data),
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def get_event_stats(
    pixel_id: str,
    archetype: str = "hybrid",
) -> dict:
    """
    Get event statistics with archetype-aware diagnostic analysis.

    Checks event coverage, parameter completeness, diagnostic flags,
    and classifies overall tracking health.

    Args:
        pixel_id: Pixel ID (numeric string).
        archetype: Account archetype for requirement matching:
            'ecommerce', 'lead_gen', 'awareness', 'traffic', 'hybrid', 'messages'.
    """
    api_client._ensure_initialized()

    # 1. Get pixel info
    try:
        pixel_info = api_client.graph_get(
            f"/{pixel_id}",
            fields=["id", "name", "last_fired_time", "is_unavailable", "creation_time"],
        )
    except MetaAPIError as e:
        return {
            "pixel_id": pixel_id,
            "error": f"Could not read pixel: {e}",
            "health": "missing",
        }

    # 2. Get events (last 24h)
    events_found: list[str] = []
    event_counts: dict[str, int] = {}
    try:
        stats_result = api_client.graph_get(
            f"/{pixel_id}/stats",
            params={"aggregation": "event"},
        )
        for bucket in stats_result.get("data", []):
            for entry in bucket.get("data", []):
                name = entry.get("value", "Unknown")
                count = entry.get("count", 0)
                event_counts[name] = event_counts.get(name, 0) + count
                if name not in events_found:
                    events_found.append(name)
    except MetaAPIError:
        pass

    # 3. Get diagnostics (da_checks)
    diagnostics: list[dict] = []
    try:
        diag_result = api_client.graph_get(f"/{pixel_id}/da_checks")
        diagnostics = diag_result.get("data", [])
    except MetaAPIError:
        pass

    # 4. Classify health
    classification = _classify_pixel_health(pixel_info, events_found, archetype, diagnostics)

    # 5. Check value parameter coverage for purchase events
    value_coverage = None
    if "Purchase" in events_found or "purchase" in [e.lower() for e in events_found]:
        # We can't check individual event params via stats API alone,
        # but we can flag it as needing verification
        value_coverage = {
            "event": "Purchase",
            "has_value_param": "unknown_from_stats_api",
            "note": "Verify via Test Events or Events Manager that Purchase events include value and currency params.",
        }
        # Check if any da_check flags missing params
        for diag in diagnostics:
            if "missing_param" in diag.get("key", ""):
                value_coverage["has_value_param"] = "likely_missing"
                value_coverage["diagnostic"] = diag.get("description")

    # 6. Build summary
    diagnostic_summary = {
        "pixel_id": pixel_id,
        "pixel_name": pixel_info.get("name"),
        "last_fired": pixel_info.get("last_fired_time"),
        "is_unavailable": pixel_info.get("is_unavailable", False),
        "health": classification["health"],
        "archetype": archetype,
        "events_detected": events_found,
        "event_counts": dict(sorted(event_counts.items(), key=lambda x: x[1], reverse=True)),
        "total_events_24h": sum(event_counts.values()),
        "issues": classification["issues"],
        "issue_count": classification["issue_count"],
        "critical_issues": classification["critical_count"],
        "diagnostics_checked": len(diagnostics),
        "diagnostics_failed": sum(1 for d in diagnostics if d.get("result") == "failed"),
        "value_coverage": value_coverage,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }

    return diagnostic_summary


@mcp.tool()
def send_test_event(
    pixel_id: str,
    event_name: str = "PageView",
    test_event_code: Optional[str] = None,
    custom_data: Optional[str] = None,
) -> dict:
    """
    Send a test event via the Conversions API Test Events endpoint.

    Args:
        pixel_id: Pixel ID (numeric string).
        event_name: Event name to send (default 'PageView').
        test_event_code: Test event code from Events Manager.
            If not provided, generates a temporary one.
        custom_data: Optional JSON string of custom_data params
            (e.g., '{"value": 10.00, "currency": "EUR"}').
    """
    api_client._ensure_initialized()
    import json
    import time
    import hashlib

    # Build the event payload per Conversions API spec
    now = int(time.time())
    test_code = test_event_code or f"TEST{now}"

    event_data: dict[str, Any] = {
        "event_name": event_name,
        "event_time": now,
        "action_source": "website",
        "event_source_url": "https://test.example.com/test-event",
        "user_data": {
            "client_ip_address": "0.0.0.0",
            "client_user_agent": "Mozilla/5.0 (Meta Ads MCP Test Event)",
            "em": [hashlib.sha256(f"test_{now}@example.com".encode()).hexdigest()],
        },
    }

    if custom_data:
        try:
            event_data["custom_data"] = json.loads(custom_data)
        except json.JSONDecodeError:
            return {"error": f"Invalid custom_data JSON: {custom_data}"}

    payload = {
        "data": [event_data],
        "test_event_code": test_code,
    }

    try:
        result = api_client.graph_post(
            f"/{pixel_id}/events",
            json_body=payload,
        )

        return {
            "pixel_id": pixel_id,
            "event_name": event_name,
            "test_event_code": test_code,
            "events_received": result.get("events_received"),
            "messages": result.get("messages", []),
            "fbtrace_id": result.get("fbtrace_id"),
            "status": "sent",
            "note": f"Check Events Manager > Test Events tab with code '{test_code}' to verify receipt.",
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError as e:
        return {
            "pixel_id": pixel_id,
            "event_name": event_name,
            "test_event_code": test_code,
            "status": "failed",
            "error": str(e),
        }


@mcp.tool()
def run_tracking_diagnostic(
    account_id: str,
    archetype: str = "hybrid",
) -> dict:
    """
    Run comprehensive tracking diagnostic for an ad account.

    Checks all connected pixels, event coverage, parameter completeness,
    and Meta diagnostic flags. Returns archetype-aware health classification
    with severity-ranked issues and fix suggestions.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        archetype: Account archetype for requirement matching.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    # 1. Get connected pixels
    try:
        pixel_result = api_client.graph_get(
            f"/{account_id}/adspixels",
            fields=["id", "name", "last_fired_time", "is_unavailable", "creation_time"],
        )
        pixels = pixel_result.get("data", [])
    except MetaAPIError as e:
        return {
            "account_id": account_id,
            "error": f"Could not read pixels: {e}",
            "health": "missing",
            "pixels": [],
        }

    if not pixels:
        severity = SEVERITY_CRITICAL if archetype in ("ecommerce", "lead_gen") else SEVERITY_MEDIUM
        return {
            "account_id": account_id,
            "archetype": archetype,
            "health": "missing",
            "pixels": [],
            "pixel_count": 0,
            "issues": [{
                "severity": severity,
                "check": "pixel_exists",
                "message": "No pixel connected to this ad account",
                "fix": "Create a pixel in Events Manager and connect it to this ad account.",
            }],
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    # 2. Diagnose each pixel
    pixel_reports = []
    worst_health = "healthy"
    all_issues = []

    for pixel in pixels:
        pid = pixel.get("id")
        report = get_event_stats(pid, archetype=archetype)
        pixel_reports.append(report)
        all_issues.extend(report.get("issues", []))

        # Track worst health
        health = report.get("health", "unknown")
        health_order = {"healthy": 0, "partial": 1, "degraded": 2, "never_fired": 3, "missing": 4}
        if health_order.get(health, 5) > health_order.get(worst_health, 0):
            worst_health = health

    # 3. Objective-tracking alignment check
    # Get active campaigns to check objective vs tracking
    try:
        camp_result = api_client.graph_get(
            f"/{account_id}/campaigns",
            fields=["id", "name", "objective", "effective_status"],
            params={
                "limit": "20",
                "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
            },
        )
        active_campaigns = camp_result.get("data", [])
    except MetaAPIError:
        active_campaigns = []

    # Check for mismatches
    all_detected_events = set()
    for pr in pixel_reports:
        all_detected_events.update(pr.get("events_detected", []))

    alignment_warnings = []
    for camp in active_campaigns:
        obj = camp.get("objective", "")
        name = camp.get("name", "")
        if obj == "OUTCOME_SALES" and "Purchase" not in all_detected_events:
            alignment_warnings.append({
                "severity": SEVERITY_HIGH,
                "check": "objective_tracking_alignment",
                "message": f"Campaign '{name}' has OUTCOME_SALES objective but no Purchase events detected on pixel",
                "fix": "Install Purchase event on order confirmation page, or change campaign objective.",
            })
        elif obj == "OUTCOME_LEADS" and "Lead" not in all_detected_events:
            alignment_warnings.append({
                "severity": SEVERITY_HIGH,
                "check": "objective_tracking_alignment",
                "message": f"Campaign '{name}' has OUTCOME_LEADS objective but no Lead events detected on pixel",
                "fix": "Install Lead event on form submission, or use instant forms.",
            })

    all_issues.extend(alignment_warnings)

    # Sort all issues by severity
    severity_order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3, SEVERITY_INFO: 4}
    all_issues.sort(key=lambda x: severity_order.get(x["severity"], 5))

    return {
        "account_id": account_id,
        "archetype": archetype,
        "health": worst_health,
        "pixel_count": len(pixels),
        "pixels": pixel_reports,
        "active_campaigns": len(active_campaigns),
        "all_detected_events": sorted(all_detected_events),
        "issues": all_issues,
        "issue_count": len(all_issues),
        "critical_issues": sum(1 for i in all_issues if i["severity"] == SEVERITY_CRITICAL),
        "alignment_warnings": len(alignment_warnings),
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
