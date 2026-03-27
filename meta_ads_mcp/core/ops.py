"""
Operational tools that were missing from the MCP.

1. Resumable video upload (>100MB)
2. Bulk rename objects
3. Bulk delete campaign structure
4. Browser pixel diagnostic
5. Page identity resolution
"""
import json as _json
import logging
import os
from datetime import datetime
from typing import Any, Optional

import httpx

from meta_ads_mcp.core.api import api_client, MetaAPIError, GRAPH_API_BASE
from meta_ads_mcp.core.utils import ensure_account_id_format
from meta_ads_mcp.server import mcp

logger = logging.getLogger("meta-ads-mcp.ops")


# ===================================================================
# 1. RESUMABLE VIDEO UPLOAD
# ===================================================================

@mcp.tool()
def upload_video_resumable(
    account_id: str,
    video_path: str,
    title: Optional[str] = None,
    chunk_size_mb: int = 20,
) -> dict:
    """
    Upload a video file using resumable upload (supports files >100MB up to 4GB).

    Use this for large files that fail with upload_video_asset.
    Automatically chunks the file and uploads sequentially.

    Args:
        account_id: Ad account ID.
        video_path: Local path to .mp4 or .mov file.
        title: Optional title (defaults to filename).
        chunk_size_mb: Chunk size in MB (default 20).
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)
    token = api_client._access_token

    normalized = os.path.normpath(video_path)
    if not os.path.exists(normalized):
        return {"error": f"File not found: {normalized}"}

    file_size = os.path.getsize(normalized)
    if file_size == 0:
        return {"error": "File is empty"}

    filename = os.path.basename(normalized)
    video_title = title or os.path.splitext(filename)[0]
    chunk_bytes = chunk_size_mb * 1024 * 1024

    # Step 1: Start session
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{GRAPH_API_BASE}/{account_id}/advideos",
            data={"access_token": token, "upload_phase": "start", "file_size": str(file_size)},
        )
    if r.status_code != 200:
        return {"error": f"Start failed: {r.text[:200]}"}

    start = r.json()
    session_id = start.get("upload_session_id")
    video_id = start.get("video_id")

    if not session_id:
        return {"error": f"No session_id returned: {start}"}

    # Step 2: Upload chunks
    total_chunks = (file_size // chunk_bytes) + (1 if file_size % chunk_bytes else 0)
    with open(normalized, "rb") as f:
        offset = 0
        chunk_num = 0
        while offset < file_size:
            chunk = f.read(chunk_bytes)
            chunk_num += 1

            with httpx.Client(timeout=300.0) as client:
                r = client.post(
                    f"{GRAPH_API_BASE}/{account_id}/advideos",
                    data={
                        "access_token": token,
                        "upload_phase": "transfer",
                        "upload_session_id": session_id,
                        "start_offset": str(offset),
                    },
                    files={"video_file_chunk": ("chunk.mp4", chunk, "video/mp4")},
                )

            if r.status_code != 200:
                return {"error": f"Chunk {chunk_num} failed: {r.text[:200]}", "video_id": video_id, "chunks_done": chunk_num - 1}

            offset = int(r.json().get("start_offset", offset + len(chunk)))

    # Step 3: Finish
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{GRAPH_API_BASE}/{account_id}/advideos",
            data={"access_token": token, "upload_phase": "finish", "upload_session_id": session_id, "title": video_title},
        )

    if r.status_code != 200:
        return {"error": f"Finish failed: {r.text[:200]}", "video_id": video_id}

    return {
        "video_id": video_id,
        "title": video_title,
        "file_size_mb": round(file_size / (1024 * 1024), 1),
        "chunks_uploaded": total_chunks,
        "upload_status": "success",
    }


# ===================================================================
# 2. BULK RENAME
# ===================================================================

@mcp.tool()
def bulk_rename_objects(
    renames_json: str,
) -> dict:
    """
    Rename multiple Meta Ads objects in one call.

    Args:
        renames_json: JSON array of rename specs:
            [{object_id: '...', new_name: '...', object_type: 'campaign|adset|ad'}, ...]
    """
    api_client._ensure_initialized()

    try:
        renames = _json.loads(renames_json)
    except _json.JSONDecodeError as e:
        return {"error": f"Malformed JSON: {e}"}

    results = []
    for item in renames:
        oid = item.get("object_id")
        name = item.get("new_name")
        if not oid or not name:
            results.append({"object_id": oid, "status": "skipped", "error": "Missing object_id or new_name"})
            continue

        try:
            api_client.graph_post(f"/{oid}", data={"name": name})
            results.append({"object_id": oid, "new_name": name, "status": "success"})
        except MetaAPIError as e:
            results.append({"object_id": oid, "new_name": name, "status": "failed", "error": str(e)})

    succeeded = sum(1 for r in results if r["status"] == "success")
    return {"total": len(results), "succeeded": succeeded, "results": results}


# ===================================================================
# 3. BULK DELETE CAMPAIGN STRUCTURE
# ===================================================================

@mcp.tool()
def delete_campaign_structure(
    account_id: str,
    campaign_ids_json: Optional[str] = None,
    delete_all_active: bool = False,
    confirm: bool = False,
) -> dict:
    """
    Delete entire campaign structure (ads -> adsets -> campaigns) in correct order.

    Args:
        account_id: Ad account ID.
        campaign_ids_json: JSON array of campaign IDs to delete. If not provided with
            delete_all_active=True, deletes all non-deleted campaigns.
        delete_all_active: If True and no campaign_ids, targets all campaigns.
        confirm: Must be True to actually delete. False = dry run showing what would be deleted.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)

    # Resolve campaign IDs
    if campaign_ids_json:
        campaign_ids = _json.loads(campaign_ids_json)
    elif delete_all_active:
        from meta_ads_mcp.core.campaigns import get_campaigns
        camps = get_campaigns(account_id)
        campaign_ids = [c["id"] for c in camps["campaigns"] if c.get("status") != "DELETED"]
    else:
        return {"error": "Provide campaign_ids_json or set delete_all_active=True"}

    # Collect all objects in deletion order
    from meta_ads_mcp.core.ads import get_ads
    from meta_ads_mcp.core.adsets import get_adsets

    ads_to_delete = []
    adsets_to_delete = []

    for cid in campaign_ids:
        # Get ads for this campaign
        try:
            camp_ads = get_ads(account_id, campaign_id=cid)
            for ad in camp_ads.get("ads", []):
                if ad.get("status") != "DELETED":
                    ads_to_delete.append({"id": ad["id"], "name": ad.get("name", "?"), "campaign_id": cid})
        except:
            pass

        # Get adsets
        try:
            camp_adsets = get_adsets(account_id, campaign_id=cid)
            for adset in camp_adsets.get("adsets", []):
                if adset.get("status") != "DELETED":
                    adsets_to_delete.append({"id": adset["id"], "name": adset.get("name", "?"), "campaign_id": cid})
        except:
            pass

    if not confirm:
        return {
            "dry_run": True,
            "would_delete": {
                "ads": len(ads_to_delete),
                "adsets": len(adsets_to_delete),
                "campaigns": len(campaign_ids),
                "total": len(ads_to_delete) + len(adsets_to_delete) + len(campaign_ids),
            },
            "ads": [{"id": a["id"], "name": a["name"]} for a in ads_to_delete],
            "adsets": [{"id": a["id"], "name": a["name"]} for a in adsets_to_delete],
            "campaigns": campaign_ids,
        }

    # Delete in order: ads -> adsets -> campaigns
    deleted = {"ads": 0, "adsets": 0, "campaigns": 0, "errors": []}

    for ad in ads_to_delete:
        try:
            api_client.graph_post(f"/{ad['id']}", data={"status": "DELETED"})
            deleted["ads"] += 1
        except MetaAPIError as e:
            deleted["errors"].append(f"Ad {ad['id']}: {e}")

    for adset in adsets_to_delete:
        try:
            api_client.graph_post(f"/{adset['id']}", data={"status": "DELETED"})
            deleted["adsets"] += 1
        except MetaAPIError as e:
            deleted["errors"].append(f"Adset {adset['id']}: {e}")

    for cid in campaign_ids:
        try:
            api_client.graph_post(f"/{cid}", data={"status": "DELETED"})
            deleted["campaigns"] += 1
        except MetaAPIError as e:
            deleted["errors"].append(f"Campaign {cid}: {e}")

    return {"deleted": deleted, "total_deleted": deleted["ads"] + deleted["adsets"] + deleted["campaigns"]}


# ===================================================================
# 4. BROWSER PIXEL DIAGNOSTIC
# ===================================================================

@mcp.tool()
def diagnose_pixel_on_site(
    url: str,
    pixel_id: Optional[str] = None,
) -> dict:
    """
    Diagnose pixel installation on a website via headless browser check.

    Checks: pixel script presence, consent/cookie blocking, Lead event setup,
    Complianz/cookie banner status.

    Requires browser MCP (Puppeteer) to be available.

    Args:
        url: Website URL to check.
        pixel_id: Optional specific pixel ID to look for.
    """
    # This tool provides the diagnostic script for the browser MCP
    # The actual browser execution happens via mcp__browser__puppeteer_*
    script = """
(function() {
    var result = {};

    // Check fbq loaded
    result.fbq_loaded = typeof fbq !== 'undefined';

    // Check for blocked pixel scripts
    var scripts = Array.from(document.querySelectorAll('script'));
    var pixelScripts = scripts.filter(function(s) {
        return (s.textContent || '').includes('fbq') || (s.src || '').includes('facebook');
    });

    result.pixel_scripts = pixelScripts.map(function(s) {
        return {
            type: s.type || 'text/javascript',
            blocked: s.type === 'text/plain',
            data_category: s.dataset.category || s.dataset.cookiecategory || 'none',
            has_pixel_id: PIXEL_ID ? (s.textContent || '').includes(PIXEL_ID) : false,
        };
    });

    result.any_blocked = result.pixel_scripts.some(function(s) { return s.blocked; });

    // Cookie banner
    var cmplz = document.querySelectorAll('[class*="cmplz"]');
    result.complianz_present = cmplz.length > 0;
    result.cookie_banner_visible = false;
    cmplz.forEach(function(el) {
        if (el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none') {
            if (el.textContent.length > 20) result.cookie_banner_visible = true;
        }
    });

    // Forms and Lead events
    var forms = document.querySelectorAll('form');
    result.forms_count = forms.length;

    var allText = scripts.map(function(s) { return s.textContent; }).join('');
    result.lead_event_in_code = allText.includes("'Lead'") || allText.includes('"Lead"');
    result.submit_listener = allText.includes('submit') && allText.includes('fbq');

    // Cookies
    result.has_cookies = document.cookie.length > 0;
    result.has_fbp = document.cookie.includes('_fbp');

    return result;
})()
""".replace("PIXEL_ID", f"'{pixel_id}'" if pixel_id else "null")

    return {
        "url": url,
        "pixel_id": pixel_id,
        "diagnostic_script": script,
        "instructions": [
            "1. Navigate to URL with mcp__browser__puppeteer_navigate",
            "2. Wait 3 seconds for page load",
            "3. Execute this script with mcp__browser__puppeteer_evaluate",
            "4. The result contains all diagnostic data",
        ],
        "checks_performed": [
            "fbq_loaded: Is Meta Pixel function defined?",
            "any_blocked: Are pixel scripts blocked by consent manager?",
            "complianz_present: Is Complianz cookie manager installed?",
            "cookie_banner_visible: Can users accept cookies?",
            "lead_event_in_code: Is Lead event trigger present?",
            "submit_listener: Is form submit listener connected to fbq?",
            "has_fbp: Is _fbp cookie present (pixel has fired before)?",
        ],
    }


# ===================================================================
# 5. PAGE IDENTITY RESOLUTION
# ===================================================================

@mcp.tool()
def resolve_page_identity(
    page_id: str,
    account_id: str = None,
) -> dict:
    """
    Resolve full identity for a Facebook Page: page details + Instagram business account.

    Uses the 3-step IG resolution ladder (registry -> promote_pages -> ad account).
    Falls back to direct page query if account_id not provided.

    Args:
        page_id: Facebook Page ID.
        account_id: Optional ad account ID for improved IG resolution.
    """
    api_client._ensure_initialized()

    # Try direct page query for page details
    page_name = None
    page_link = None
    page_fans = None
    page_verified = None
    try:
        page = api_client.graph_get(f"/{page_id}", fields=[
            "id", "name", "link", "fan_count", "verification_status",
        ])
        page_name = page.get("name")
        page_link = page.get("link")
        page_fans = page.get("fan_count")
        page_verified = page.get("verification_status")
    except MetaAPIError:
        pass  # Page details are nice-to-have

    # Resolve IG identity using the full ladder
    from meta_ads_mcp.core.identity import resolve_instagram_identity as _resolve_ig
    ig_result = _resolve_ig(account_id=account_id, page_id=page_id) if account_id else _resolve_ig(account_id="", page_id=page_id)
    ig_id = ig_result.get("instagram_user_id")

    # Get IG details if available
    ig_details = None
    if ig_id:
        try:
            ig_details = api_client.graph_get(f"/{ig_id}", fields=[
                "id", "username", "name", "profile_picture_url",
                "followers_count", "media_count",
            ])
        except MetaAPIError:
            ig_details = {"id": ig_id, "note": "Could not fetch IG details"}

    return {
        "page_id": page_id,
        "page_name": page_name,
        "page_link": page_link,
        "page_fans": page_fans,
        "page_verified": page_verified,
        "instagram_user_id": ig_id,
        "instagram_linked": ig_id is not None,
        "instagram_details": ig_details,
        "identity_complete": ig_id is not None,
        "resolution_method": ig_result.get("resolution_method"),
        "resolution_confidence": ig_result.get("resolution_confidence"),
        "warning": ig_result.get("block_reason") if not ig_id else None,
    }
