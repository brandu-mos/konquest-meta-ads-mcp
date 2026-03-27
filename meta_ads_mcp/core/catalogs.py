"""
Catalog management and diagnostic tools.

Provides catalog health checks, product inspection, product set CRUD,
feed status, and connection chain validation.

Diagnostic-first: outputs classify catalog health and surface connection
gaps, stale feeds, rejected products, and ecommerce readiness issues.

Phase: v1.1 (Read) / v1.3 (Write)
"""
import logging
from typing import Any, Optional

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.catalogs")

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"


@mcp.tool()
def get_catalog_info(catalog_id: str) -> dict:
    """
    Get catalog details including product count, vertical, name,
    and connected event sources (pixels).

    Args:
        catalog_id: Product catalog ID (numeric string).
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{catalog_id}",
            fields=[
                "id", "name", "product_count", "vertical",
                "da_display_settings",
            ],
        )

        # Get connected pixels (external_event_sources)
        try:
            event_sources = api_client.graph_get(
                f"/{catalog_id}/external_event_sources",
                fields=["id", "name"],
            )
            result["connected_pixels"] = event_sources.get("data", [])
        except MetaAPIError:
            result["connected_pixels"] = []

        # Get product sets
        try:
            sets_result = api_client.graph_get(
                f"/{catalog_id}/product_sets",
                fields=["id", "name", "product_count"],
            )
            result["product_sets"] = sets_result.get("data", [])
        except MetaAPIError:
            result["product_sets"] = []

        # Get feeds
        try:
            feeds_result = api_client.graph_get(
                f"/{catalog_id}/product_feeds",
                fields=["id", "name", "product_count", "latest_upload", "schedule"],
            )
            result["feeds"] = feeds_result.get("data", [])
        except MetaAPIError:
            result["feeds"] = []

        result["rate_limit_usage_pct"] = api_client.rate_limits.max_usage_pct
        return result

    except MetaAPIError:
        raise


@mcp.tool()
def get_catalog_products(
    catalog_id: str,
    limit: int = 25,
    filter_availability: Optional[str] = None,
) -> dict:
    """
    List products in a catalog with price, availability, review status, and URLs.

    Args:
        catalog_id: Product catalog ID.
        limit: Max products to return (default 25, max 100).
        filter_availability: Optional filter: 'in stock', 'out of stock', 'discontinued'.
    """
    api_client._ensure_initialized()

    params: dict[str, str] = {"limit": str(min(limit, 100))}

    if filter_availability:
        params["filter"] = f'{{"availability":{{"eq":"{filter_availability}"}}}}'

    try:
        result = api_client.graph_get(
            f"/{catalog_id}/products",
            fields=[
                "id", "name", "price", "currency",
                "availability", "review_status",
                "image_url", "url",
                "retailer_id", "brand",
            ],
            params=params,
        )

        products = result.get("data", [])

        # Aggregate stats
        avail_counts: dict[str, int] = {}
        review_counts: dict[str, int] = {}
        price_values: list[float] = []

        for p in products:
            avail = p.get("availability", "unknown")
            review = p.get("review_status", "unknown") or "no_review"
            avail_counts[avail] = avail_counts.get(avail, 0) + 1
            review_counts[review] = review_counts.get(review, 0) + 1

            # Parse price for stats
            price_str = p.get("price", "")
            if price_str:
                try:
                    # Price format: "€33.00" or "33.00 EUR" or just "3300"
                    cleaned = price_str.replace("€", "").replace("EUR", "").replace(",", ".").strip()
                    price_val = float(cleaned)
                    if price_val > 500:  # Likely in cents
                        price_val /= 100
                    price_values.append(price_val)
                except (ValueError, TypeError):
                    pass

        stats = {
            "total_returned": len(products),
            "availability_breakdown": avail_counts,
            "review_status_breakdown": review_counts,
        }

        if price_values:
            stats["price_range"] = {
                "min": round(min(price_values), 2),
                "max": round(max(price_values), 2),
                "avg": round(sum(price_values) / len(price_values), 2),
                "currency": products[0].get("currency", "EUR") if products else "EUR",
            }

        return {
            "catalog_id": catalog_id,
            "products": products,
            "stats": stats,
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def get_product_sets(catalog_id: str) -> dict:
    """
    List product sets in a catalog with product counts and filter rules.

    Args:
        catalog_id: Product catalog ID.
    """
    api_client._ensure_initialized()

    try:
        result = api_client.graph_get(
            f"/{catalog_id}/product_sets",
            fields=["id", "name", "product_count", "filter"],
        )

        sets = result.get("data", [])

        # Flag empty sets
        for s in sets:
            s["is_empty"] = (s.get("product_count", 0) == 0)

        return {
            "catalog_id": catalog_id,
            "total": len(sets),
            "product_sets": sets,
            "empty_sets": sum(1 for s in sets if s.get("is_empty")),
            "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
        }

    except MetaAPIError:
        raise


@mcp.tool()
def validate_catalog_connections(
    catalog_id: str,
    account_id: Optional[str] = None,
    pixel_id: Optional[str] = None,
    page_id: Optional[str] = None,
) -> dict:
    """
    Validate the catalog-pixel-account-page connection chain
    and run diagnostic health assessment.

    For DPA (Dynamic Product Ads) to work, the full chain must be connected:
    Catalog -> Pixel -> Ad Account -> Page

    Args:
        catalog_id: Product catalog ID.
        account_id: Optional ad account ID to verify connection.
        pixel_id: Optional pixel ID to verify catalog-pixel link.
        page_id: Optional page ID to verify catalog-page link.
    """
    api_client._ensure_initialized()

    issues: list[dict] = []
    connections = {
        "catalog_exists": False,
        "catalog_has_products": False,
        "pixel_connected": False,
        "has_product_sets": False,
        "feed_active": False,
        "products_approved": False,
    }

    # 1. Check catalog exists and has products
    try:
        catalog = api_client.graph_get(
            f"/{catalog_id}",
            fields=["id", "name", "product_count", "vertical"],
        )
        connections["catalog_exists"] = True
        product_count = catalog.get("product_count", 0)
        connections["catalog_has_products"] = product_count > 0

        # Check catalog name hygiene
        catalog_name = catalog.get("name", "")
        generic_names = ["service card catalog", "test catalog", "catalog", "untitled", "default"]
        if any(g in catalog_name.lower() for g in generic_names):
            issues.append({
                "severity": SEVERITY_LOW,
                "check": "catalog_name_hygiene",
                "message": f"Catalog name '{catalog_name}' appears generic or auto-generated",
                "fix": "Rename the catalog to something descriptive (e.g., 'Example E-Shop Products') in Commerce Manager.",
            })

        if product_count == 0:
            issues.append({
                "severity": SEVERITY_CRITICAL,
                "check": "catalog_products",
                "message": "Catalog has 0 products",
                "fix": "Add products to the catalog via Commerce Manager or product feed.",
            })
        elif product_count < 4:
            issues.append({
                "severity": SEVERITY_LOW,
                "check": "catalog_product_count",
                "message": f"Catalog has only {product_count} products (< 4 for carousel)",
                "fix": "Consider adding more products for carousel ad format.",
            })

    except MetaAPIError as e:
        issues.append({
            "severity": SEVERITY_CRITICAL,
            "check": "catalog_exists",
            "message": f"Cannot access catalog {catalog_id}: {e}",
            "fix": "Verify catalog ID is correct and accessible by this business.",
        })
        return {
            "catalog_id": catalog_id,
            "health": "missing",
            "connections": connections,
            "issues": issues,
        }

    # 2. Check pixel connection
    try:
        event_sources = api_client.graph_get(
            f"/{catalog_id}/external_event_sources",
            fields=["id", "name"],
        )
        connected_pixels = event_sources.get("data", [])
        connected_pixel_ids = [p.get("id") for p in connected_pixels]

        if not connected_pixels:
            issues.append({
                "severity": SEVERITY_CRITICAL,
                "check": "pixel_connected",
                "message": "No pixel connected to this catalog. Catalog is NOT DPA-ready - Dynamic Product Ads cannot run without pixel-catalog linkage.",
                "fix": "Connect the pixel to this catalog in Commerce Manager > Data Sources. Until connected, DPA campaigns (like retargeting) will not function.",
            })
        else:
            connections["pixel_connected"] = True
            if pixel_id and pixel_id not in connected_pixel_ids:
                issues.append({
                    "severity": SEVERITY_HIGH,
                    "check": "specific_pixel_connected",
                    "message": f"Pixel {pixel_id} is not connected to this catalog. Connected: {connected_pixel_ids}",
                    "fix": f"Connect pixel {pixel_id} to catalog {catalog_id} in Commerce Manager.",
                })

    except MetaAPIError:
        issues.append({
            "severity": SEVERITY_MEDIUM,
            "check": "pixel_connection_check",
            "message": "Could not verify pixel-catalog connection via API",
            "fix": "Check catalog data sources in Commerce Manager manually.",
        })

    # 3. Check product sets
    try:
        sets_result = api_client.graph_get(
            f"/{catalog_id}/product_sets",
            fields=["id", "name", "product_count"],
        )
        product_sets = sets_result.get("data", [])
        connections["has_product_sets"] = len(product_sets) > 0

        empty_sets = [s for s in product_sets if s.get("product_count", 0) == 0]
        if empty_sets:
            names = [s.get("name", s.get("id")) for s in empty_sets]
            issues.append({
                "severity": SEVERITY_MEDIUM,
                "check": "empty_product_sets",
                "message": f"Empty product sets: {', '.join(names)}",
                "fix": "Update filter rules or remove empty product sets.",
            })

        # Check product set coverage vs total catalog
        if product_sets and product_count > 0:
            total_set_products = sum(s.get("product_count", 0) for s in product_sets)
            max_set_products = max(s.get("product_count", 0) for s in product_sets)
            if max_set_products < product_count * 0.5:
                issues.append({
                    "severity": SEVERITY_MEDIUM,
                    "check": "product_set_coverage",
                    "message": f"Largest product set covers {max_set_products}/{product_count} products ({max_set_products*100//product_count}%). {product_count - max_set_products} products are not in the primary set.",
                    "fix": "Review product set filters. Products outside all sets will not appear in DPA ads.",
                })

        if not product_sets:
            issues.append({
                "severity": SEVERITY_MEDIUM,
                "check": "product_sets_exist",
                "message": "No product sets defined. DPA ad sets require a product set.",
                "fix": "Create product sets in Commerce Manager for targeting.",
            })

    except MetaAPIError:
        pass

    # 4. Check product health (sample)
    try:
        products = api_client.graph_get(
            f"/{catalog_id}/products",
            fields=["id", "availability", "review_status"],
            params={"limit": "50"},
        )
        product_list = products.get("data", [])

        out_of_stock = sum(1 for p in product_list if p.get("availability") != "in stock")
        rejected = sum(1 for p in product_list if p.get("review_status") in ("rejected", "disapproved"))

        if product_list:
            connections["products_approved"] = rejected == 0

        if rejected > 0:
            issues.append({
                "severity": SEVERITY_HIGH,
                "check": "rejected_products",
                "message": f"{rejected} product(s) rejected/disapproved out of {len(product_list)} sampled",
                "fix": "Review rejected products in Commerce Manager and fix violations.",
            })

        if out_of_stock > 0:
            issues.append({
                "severity": SEVERITY_LOW,
                "check": "out_of_stock",
                "message": f"{out_of_stock} product(s) out of stock out of {len(product_list)} sampled",
                "fix": "Update product availability or exclude out-of-stock items from DPA.",
            })

    except MetaAPIError:
        pass

    # 5. Check feeds
    try:
        feeds = api_client.graph_get(
            f"/{catalog_id}/product_feeds",
            fields=["id", "name", "product_count", "latest_upload", "schedule"],
        )
        feed_list = feeds.get("data", [])
        connections["feed_active"] = len(feed_list) > 0

        if not feed_list:
            issues.append({
                "severity": SEVERITY_INFO,
                "check": "feed_exists",
                "message": "No product feed detected via API. Catalog may be manually managed or managed via another path (Commerce Manager, Shops, or partner integration).",
                "fix": "If product updates are needed at scale, consider adding an automated product feed.",
            })

    except MetaAPIError:
        pass

    # 6. Classify overall health
    critical_count = sum(1 for i in issues if i["severity"] == SEVERITY_CRITICAL)
    high_count = sum(1 for i in issues if i["severity"] == SEVERITY_HIGH)

    if critical_count > 0:
        health = "degraded"
    elif high_count > 0:
        health = "partial"
    elif issues:
        health = "healthy_with_warnings"
    else:
        health = "healthy"

    # Sort issues by severity
    severity_order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3, SEVERITY_INFO: 4}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 5))

    # DPA readiness summary
    dpa_ready = (
        connections["catalog_exists"]
        and connections["catalog_has_products"]
        and connections["pixel_connected"]
        and connections["has_product_sets"]
        and connections["products_approved"]
    )
    dpa_blockers = []
    if not connections["pixel_connected"]:
        dpa_blockers.append("pixel not connected to catalog")
    if not connections["catalog_has_products"]:
        dpa_blockers.append("catalog has no products")
    if not connections["has_product_sets"]:
        dpa_blockers.append("no product sets defined")
    if not connections["products_approved"]:
        dpa_blockers.append("products have approval issues")

    return {
        "catalog_id": catalog_id,
        "catalog_name": catalog.get("name"),
        "product_count": catalog.get("product_count"),
        "vertical": catalog.get("vertical"),
        "health": health,
        "dpa_ready": dpa_ready,
        "dpa_blockers": dpa_blockers,
        "connections": connections,
        "issues": issues,
        "issue_count": len(issues),
        "critical_issues": critical_count,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


# --- Convenience Gap: Product Set Create/Update ---

@mcp.tool()
def create_product_set(
    catalog_id: str,
    name: str,
    filter_json: str,
) -> dict:
    """
    Create a product set with filter rules for DPA targeting.

    Args:
        catalog_id: Product catalog ID.
        name: Product set name.
        filter_json: JSON string of filter rules.
            Example: '{"product_type":{"i_contains":"shoes"}}'
    """
    import json as _json

    if not name or not name.strip():
        return {"error": "name is required.", "blocked_at": "input_validation"}

    try:
        filters = _json.loads(filter_json)
        if not isinstance(filters, dict):
            return {"error": "filter_json must be a JSON object.", "blocked_at": "input_validation"}
    except _json.JSONDecodeError as e:
        return {"error": f"Malformed filter_json: {e}", "blocked_at": "input_validation"}

    api_client._ensure_initialized()

    try:
        result = api_client.graph_post(
            f"/{catalog_id}/product_sets",
            data={
                "name": name.strip(),
                "filter": _json.dumps(filters),
            },
        )
    except MetaAPIError as e:
        return {"error": f"Meta API error: {e}", "blocked_at": "api_call"}

    ps_id = result.get("id")
    return {
        "product_set_id": ps_id,
        "catalog_id": catalog_id,
        "name": name.strip(),
        "filter": filters,
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }


@mcp.tool()
def update_product_set(
    product_set_id: str,
    name: Optional[str] = None,
    filter_json: Optional[str] = None,
) -> dict:
    """
    Update a product set name or filter rules.

    Args:
        product_set_id: Product set ID to update.
        name: New name.
        filter_json: New filter rules as JSON string.
    """
    import json as _json

    if name is None and filter_json is None:
        return {"error": "Provide name or filter_json.", "blocked_at": "input_validation"}

    if filter_json is not None:
        try:
            filters = _json.loads(filter_json)
            if not isinstance(filters, dict):
                return {"error": "filter_json must be a JSON object.", "blocked_at": "input_validation"}
        except _json.JSONDecodeError as e:
            return {"error": f"Malformed filter_json: {e}", "blocked_at": "input_validation"}

    api_client._ensure_initialized()

    payload = {}
    if name is not None:
        payload["name"] = name.strip()
    if filter_json is not None:
        payload["filter"] = _json.dumps(filters)

    try:
        api_client.graph_post(f"/{product_set_id}", data=payload)
    except MetaAPIError as e:
        return {"error": f"Meta API error: {e}", "blocked_at": "api_call"}

    return {
        "product_set_id": product_set_id,
        "updated_fields": list(payload.keys()),
        "rate_limit_usage_pct": api_client.rate_limits.max_usage_pct,
    }
