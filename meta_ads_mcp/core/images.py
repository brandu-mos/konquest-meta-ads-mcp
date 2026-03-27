"""
Image upload tools (Wave 1.2).

Downloads image from URL, then uploads to Meta ad images library via multipart.
Returns image hash for use in creative creation and ad building.
"""
import logging
from typing import Optional

import httpx

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError, GRAPH_API_BASE
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.images")

MAX_IMAGE_SIZE_BYTES = 30_000_000  # 30MB Meta limit


@mcp.tool()
def upload_ad_image(
    account_id: str,
    image_url: str,
    name: Optional[str] = None,
) -> dict:
    """
    Upload an image from URL into Meta ad images library.

    Downloads the image from the provided URL, then uploads it to Meta
    via multipart form upload. Returns the image hash needed for creative
    creation (create_ad_creative, create_multi_asset_ad) and ad building.

    Supported formats: JPG, PNG. Max size: 30MB.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        image_url: Public URL of the image to upload.
        name: Optional name for the image in the library.
            Defaults to filename from URL.
    """
    # Input validation
    if not image_url or not image_url.strip():
        return {
            "error": "image_url is empty. Provide a valid public image URL.",
            "blocked_at": "input_validation",
        }

    image_url = image_url.strip()

    if not (image_url.startswith("http://") or image_url.startswith("https://")):
        return {
            "error": f"image_url must start with http:// or https://. Got: '{image_url[:50]}'",
            "blocked_at": "input_validation",
        }

    account_id = ensure_account_id_format(account_id)

    # Derive filename from URL if no name provided
    if not name:
        url_path = image_url.split("?")[0].split("#")[0]
        name = url_path.split("/")[-1] or "uploaded_image.jpg"
        # Ensure it has an extension
        if "." not in name:
            name = f"{name}.jpg"

    # Download the image
    try:
        response = httpx.get(image_url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        image_bytes = response.content
    except httpx.HTTPStatusError as e:
        return {
            "error": f"Failed to download image: HTTP {e.response.status_code}",
            "image_url": image_url,
            "blocked_at": "image_download",
        }
    except httpx.RequestError as e:
        return {
            "error": f"Failed to download image: {e}",
            "image_url": image_url,
            "blocked_at": "image_download",
        }

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        return {
            "error": f"Image too large: {len(image_bytes):,} bytes (max {MAX_IMAGE_SIZE_BYTES:,} bytes / 30MB).",
            "image_url": image_url,
            "blocked_at": "input_validation",
        }

    if len(image_bytes) == 0:
        return {
            "error": "Downloaded image is empty (0 bytes).",
            "image_url": image_url,
            "blocked_at": "input_validation",
        }

    # Detect content type
    content_type = response.headers.get("content-type", "image/jpeg")
    if "png" in content_type.lower() or name.lower().endswith(".png"):
        mime = "image/png"
    else:
        mime = "image/jpeg"

    # Upload via multipart to Meta ad images endpoint
    api_client._ensure_initialized()

    upload_url = f"{GRAPH_API_BASE}/{account_id}/adimages"
    try:
        upload_response = httpx.post(
            upload_url,
            data={"access_token": api_client._access_token},
            files={"filename": (name, image_bytes, mime)},
            timeout=60.0,
        )

        if upload_response.status_code != 200:
            error_data = upload_response.json() if upload_response.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_data.get("error", {}).get("message", upload_response.text[:200])
            return {
                "error": f"Meta API error during image upload: {error_msg}",
                "image_url": image_url,
                "blocked_at": "api_call",
            }

        result = upload_response.json()

    except httpx.RequestError as e:
        return {
            "error": f"Network error during upload: {e}",
            "image_url": image_url,
            "blocked_at": "api_call",
        }

    # Parse response
    images = result.get("images", {})

    if not images:
        return {
            "error": "Image upload returned no image data.",
            "api_response": result,
            "image_url": image_url,
            "blocked_at": "api_response",
        }

    image_key = next(iter(images))
    image_data = images[image_key]

    image_hash = image_data.get("hash")
    if not image_hash:
        return {
            "error": "Image upload succeeded but no hash returned.",
            "api_response": result,
            "blocked_at": "api_response",
        }

    return {
        "account_id": account_id,
        "image_hash": image_hash,
        "image_url": image_url,
        "name": name,
        "meta_url": image_data.get("url"),
        "width": image_data.get("width"),
        "height": image_data.get("height"),
        "size_bytes": len(image_bytes),
        "usage": {
            "creative_creation": f"Use image_hash '{image_hash}' in create_ad_creative or create_multi_asset_ad",
            "ad_building": f"Use image_hash '{image_hash}' in ad manifest image_hash field",
        },
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


# --- Convenience Gap: Image Retrieval ---

@mcp.tool()
def get_ad_image(
    account_id: str,
    image_hash: str,
) -> dict:
    """
    Retrieve metadata and URL for an uploaded ad image by hash.

    Returns the image URL, dimensions, name, and other metadata.

    Args:
        account_id: Ad account ID (e.g., 'act_123456789').
        image_hash: Image hash from upload_ad_image.
    """
    if not image_hash or not image_hash.strip():
        return {"error": "image_hash is required.", "blocked_at": "input_validation"}

    account_id = ensure_account_id_format(account_id)
    image_hash = image_hash.strip()

    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{account_id}/adimages",
            fields=["hash", "name", "url", "url_128", "width", "height", "status", "created_time"],
            params={"hashes": f'["{image_hash}"]'},
        )
    except MetaAPIError as e:
        return {"error": f"Meta API error: {e}", "blocked_at": "api_call"}

    images = result.get("data", [])
    if not images:
        return {
            "error": f"No image found for hash '{image_hash}'.",
            "blocked_at": "not_found",
        }

    img = images[0]
    return {
        "account_id": account_id,
        "image_hash": img.get("hash", image_hash),
        "name": img.get("name"),
        "url": img.get("url"),
        "url_128": img.get("url_128"),
        "width": img.get("width"),
        "height": img.get("height"),
        "status": img.get("status"),
        "created_time": img.get("created_time"),
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
