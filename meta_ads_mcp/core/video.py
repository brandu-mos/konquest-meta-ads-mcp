"""
Video upload and processing tools.

Video-first workflow: upload local files, poll processing status,
and provide ready video_ids for manifest-driven ad creation.

Processing state machine: uploaded -> processing -> ready | failed

Supported formats: .mp4, .mov
Max file size: 4GB (Meta limit), practical limit ~1GB for simple upload.
Simple upload used for files < 1GB. Resumable upload for larger.
"""
import logging
import os
import time
from datetime import datetime
from typing import Optional

import httpx

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError, GRAPH_API_BASE
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.video")

SUPPORTED_EXTENSIONS = {".mp4", ".mov"}
MAX_SIMPLE_UPLOAD_BYTES = 1_000_000_000  # 1GB - use simple upload below this
MAX_FILE_SIZE_BYTES = 4_000_000_000  # 4GB Meta limit

VIDEO_PROCESSING_STATES = {
    "processing": "Video is being processed by Meta",
    "ready": "Video processing complete, ready for use in ads",
    "error": "Video processing failed",
}


def _validate_video_file(video_path: str) -> tuple[bool, str, dict]:
    """
    Validate a local video file for upload.

    Returns (valid, error_message, file_info).
    """
    info = {"path": video_path, "exists": False, "size_bytes": 0, "extension": "", "filename": ""}

    # Normalize path
    normalized = os.path.normpath(video_path)
    info["path"] = normalized

    # Check exists
    if not os.path.exists(normalized):
        return False, f"File not found: {normalized}", info
    info["exists"] = True

    # Check is file
    if not os.path.isfile(normalized):
        return False, f"Path is not a file: {normalized}", info

    # Check extension
    _, ext = os.path.splitext(normalized)
    ext_lower = ext.lower()
    info["extension"] = ext_lower
    info["filename"] = os.path.basename(normalized)

    if ext_lower not in SUPPORTED_EXTENSIONS:
        return False, f"Unsupported video format: '{ext_lower}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}", info

    # Check size
    size = os.path.getsize(normalized)
    info["size_bytes"] = size
    info["size_mb"] = round(size / (1024 * 1024), 1)

    if size == 0:
        return False, "File is empty (0 bytes)", info

    if size > MAX_FILE_SIZE_BYTES:
        return False, f"File too large: {info['size_mb']}MB. Meta limit is 4GB.", info

    return True, "", info


@mcp.tool()
def upload_video_asset(
    account_id: str,
    video_path: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """
    Upload a local video file to a Meta ad account.

    Validates the file, uploads via simple upload (for files < 1GB),
    and returns the meta_video_id for use in ad creation.
    The video enters processing after upload - use poll_video_processing
    to check when it's ready.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        video_path: Local filesystem path to the video file (.mp4 or .mov).
        title: Optional title for the video in Meta.
        description: Optional description.
    """
    api_client._ensure_initialized()
    account_id = ensure_account_id_format(account_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Step 1: Validate file
    valid, error_msg, file_info = _validate_video_file(video_path)
    if not valid:
        return {
            "error": error_msg,
            "file_info": file_info,
            "blocked_at": "file_validation",
        }

    normalized_path = file_info["path"]
    filename = file_info["filename"]

    # Step 2: Determine upload method
    if file_info["size_bytes"] > MAX_SIMPLE_UPLOAD_BYTES:
        return {
            "error": f"File is {file_info['size_mb']}MB. Resumable upload not yet implemented. Max for simple upload: ~1GB.",
            "file_info": file_info,
            "blocked_at": "upload_method",
        }

    # Step 3: Upload via simple upload (multipart form)
    rollback_ref = f"upload_video_{account_id}_{timestamp.replace(' ', '_').replace(':', '')}"

    try:
        # Build the upload URL manually since we need multipart file upload
        # which the api_client.graph_post doesn't support directly
        upload_url = f"{GRAPH_API_BASE}/{account_id}/advideos"

        token = api_client._access_token

        with open(normalized_path, "rb") as f:
            files = {"source": (filename, f, "video/mp4")}
            data = {"access_token": token}

            if title:
                data["title"] = title
            elif filename:
                # Use filename without extension as default title
                data["title"] = os.path.splitext(filename)[0]

            if description:
                data["description"] = description

            # Use a longer timeout for video upload (10 minutes)
            with httpx.Client(timeout=600.0) as upload_client:
                response = upload_client.post(upload_url, data=data, files=files)

        # Update rate limits from response
        api_client.rate_limits.update_from_headers(dict(response.headers))

        if response.status_code != 200:
            try:
                error_body = response.json()
                error_detail = error_body.get("error", {}).get("message", response.text[:500])
            except Exception:
                error_detail = response.text[:500]
            return {
                "error": f"Upload failed (HTTP {response.status_code}): {error_detail}",
                "file_info": file_info,
                "blocked_at": "api_upload",
                "rollback_reference": rollback_ref,
            }

        result = response.json()

    except OSError as e:
        return {
            "error": f"File read error: {e}",
            "file_info": file_info,
            "blocked_at": "file_read",
        }
    except httpx.TimeoutException:
        return {
            "error": f"Upload timed out after 600 seconds for {file_info['size_mb']}MB file.",
            "file_info": file_info,
            "blocked_at": "upload_timeout",
            "rollback_reference": rollback_ref,
        }

    video_id = result.get("id")
    if not video_id:
        return {
            "error": "Upload returned no video ID.",
            "api_response": result,
            "blocked_at": "api_response",
        }

    # Step 4: Get initial processing status
    processing_state = "uploaded"
    try:
        status_result = api_client.graph_get(
            f"/{video_id}",
            fields=["id", "title", "status", "length", "thumbnails", "created_time"],
        )
        video_status = status_result.get("status", {})
        if isinstance(video_status, dict):
            proc = video_status.get("processing_phase", {})
            if proc.get("status") == "complete":
                processing_state = "ready"
            elif proc.get("status") == "error":
                processing_state = "failed"
            else:
                processing_state = "processing"
    except MetaAPIError:
        processing_state = "unknown"

    return {
        "video_id": video_id,
        "upload_status": "success",
        "processing_state": processing_state,
        "source_path": normalized_path,
        "filename": filename,
        "file_size_bytes": file_info["size_bytes"],
        "file_size_mb": file_info["size_mb"],
        "title": title or os.path.splitext(filename)[0],
        "rollback_reference": rollback_ref,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


@mcp.tool()
def poll_video_processing(
    video_id: str,
    max_attempts: int = 30,
    poll_interval_seconds: int = 10,
) -> dict:
    """
    Poll video processing status until ready, failed, or max attempts reached.

    Args:
        video_id: Meta video ID from upload_video_asset.
        max_attempts: Maximum poll attempts (default 30 = 5 minutes at 10s interval).
        poll_interval_seconds: Seconds between polls (default 10).
    """
    api_client._ensure_initialized()

    for attempt in range(1, max_attempts + 1):
        try:
            result = api_client.graph_get(
                f"/{video_id}",
                fields=["id", "title", "status", "length", "thumbnails", "source"],
            )

            video_status = result.get("status", {})
            processing_phase = {}
            publishing_phase = {}

            if isinstance(video_status, dict):
                processing_phase = video_status.get("processing_phase", {})
                publishing_phase = video_status.get("publishing_phase", {})

            proc_status = processing_phase.get("status", "unknown")

            if proc_status == "complete":
                # Get thumbnail if available
                thumbnails = result.get("thumbnails", {})
                thumb_data = thumbnails.get("data", []) if isinstance(thumbnails, dict) else []
                thumbnail_uri = thumb_data[0].get("uri") if thumb_data else None

                return {
                    "video_id": video_id,
                    "processing_status": "ready",
                    "ready": True,
                    "attempts_used": attempt,
                    "title": result.get("title"),
                    "duration_seconds": result.get("length"),
                    "thumbnail_uri": thumbnail_uri,
                    "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
                }

            if proc_status == "error":
                return {
                    "video_id": video_id,
                    "processing_status": "failed",
                    "ready": False,
                    "attempts_used": attempt,
                    "error_message": processing_phase.get("error", {}).get("message", "Unknown processing error"),
                    "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
                }

            # Still processing - wait and retry
            if attempt < max_attempts:
                logger.info("Video %s processing (attempt %d/%d), waiting %ds...",
                            video_id, attempt, max_attempts, poll_interval_seconds)
                time.sleep(poll_interval_seconds)

        except MetaAPIError as e:
            return {
                "video_id": video_id,
                "processing_status": "error",
                "ready": False,
                "attempts_used": attempt,
                "error_message": f"API error during poll: {e}",
            }

    # Max attempts reached
    return {
        "video_id": video_id,
        "processing_status": "timeout",
        "ready": False,
        "attempts_used": max_attempts,
        "error_message": f"Processing not complete after {max_attempts} attempts ({max_attempts * poll_interval_seconds}s). Try polling again later.",
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
