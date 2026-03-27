"""
Naming Convention Engine.

Enforces naming standard across all Meta Ads objects.
Learned from client accounts - the structure is universal,
only the values change per client.

## Structure

Campaign: Objective | Product | Funnel | BudgetModel
Ad Set:   AudienceType | AgeRange | Geo | ExclusionFlag
Ad:       Hook | Format | Version

## Separator: ' | ' (space pipe space)

## Rules
- No client name in object names (already in the account)
- Hook names are concept-driven, kebab-case
- Format: REEL, VID, IMG, REEL+FEED (multi-asset)
- Version: V1, V2, V3 (increments on same hook)
- [OLD] suffix for deprecated, never delete
"""
import logging
from typing import Optional

from meta_ads_mcp.server import mcp

logger = logging.getLogger("meta-ads-mcp.naming")

SEP = " | "

# Valid tokens
VALID_OBJECTIVES = ["Sales", "Traffic", "Leads", "Awareness", "Engagement"]
VALID_FUNNELS = ["TOFU", "MOFU", "BOFU", "RT"]
VALID_BUDGET_MODELS = ["ABO", "CBO"]
VALID_FORMATS = ["REEL", "VID", "IMG", "REEL+FEED"]
VALID_GEOS = ["GR", "CY", "US", "UK", "DE", "FR", "NL", "NO", "SE", "DK", "FI"]


def generate_campaign_name(
    objective: str,
    product: str,
    funnel: str,
    budget_model: str,
) -> dict:
    """Generate campaign name following convention."""
    errors = []
    if objective not in VALID_OBJECTIVES:
        errors.append(f"objective '{objective}' not in {VALID_OBJECTIVES}")
    if funnel not in VALID_FUNNELS:
        errors.append(f"funnel '{funnel}' not in {VALID_FUNNELS}")
    if budget_model not in VALID_BUDGET_MODELS:
        errors.append(f"budget_model '{budget_model}' not in {VALID_BUDGET_MODELS}")
    if not product:
        errors.append("product is required")

    if errors:
        return {"name": None, "valid": False, "errors": errors}

    name = SEP.join([objective, product, funnel, budget_model])
    return {"name": name, "valid": True, "pattern": "Objective | Product | Funnel | BudgetModel"}


def generate_adset_name(
    audience_type: str,
    age_range: str,
    geo: str,
    exclusion_flag: str = "None",
) -> dict:
    """Generate ad set name following convention."""
    errors = []
    if not audience_type:
        errors.append("audience_type required (e.g., Broad, Broad-Interest, RT-WV-30d)")
    if not age_range:
        errors.append("age_range required (e.g., 24-55, 18-45, All)")
    if geo not in VALID_GEOS:
        errors.append(f"geo '{geo}' not in {VALID_GEOS}")

    if errors:
        return {"name": None, "valid": False, "errors": errors}

    name = SEP.join([audience_type, age_range, geo, exclusion_flag])
    return {"name": name, "valid": True, "pattern": "AudienceType | AgeRange | Geo | ExclusionFlag"}


def generate_ad_name(
    hook: str,
    format_code: str,
    version: str = "V1",
) -> dict:
    """Generate ad name following convention."""
    errors = []
    if not hook:
        errors.append("hook required (concept name in kebab-case, e.g., Employee-Blame)")
    if format_code not in VALID_FORMATS:
        errors.append(f"format_code '{format_code}' not in {VALID_FORMATS}")
    if not version.startswith("V"):
        errors.append(f"version must start with V (e.g., V1, V2)")

    if errors:
        return {"name": None, "valid": False, "errors": errors}

    name = SEP.join([hook, format_code, version])
    return {"name": name, "valid": True, "pattern": "Hook | Format | Version"}


def validate_name(name: str, object_type: str) -> dict:
    """Validate an existing name against the convention."""
    parts = [p.strip() for p in name.split("|")]

    if object_type == "campaign":
        expected = 4
        labels = ["Objective", "Product", "Funnel", "BudgetModel"]
    elif object_type == "adset":
        expected = 4
        labels = ["AudienceType", "AgeRange", "Geo", "ExclusionFlag"]
    elif object_type == "ad":
        expected = 3
        labels = ["Hook", "Format", "Version"]
    else:
        return {"valid": False, "error": f"Unknown object_type: {object_type}"}

    if len(parts) < expected:
        return {
            "valid": False,
            "error": f"Expected {expected} tokens separated by ' | ', got {len(parts)}",
            "parsed_tokens": parts,
        }

    parsed = dict(zip(labels, parts))
    warnings = []

    if object_type == "ad":
        if parsed.get("Format") not in VALID_FORMATS:
            warnings.append(f"Format '{parsed.get('Format')}' not standard")
        if not parsed.get("Version", "").startswith("V"):
            warnings.append(f"Version '{parsed.get('Version')}' should start with V")

    return {
        "valid": len(warnings) == 0,
        "parsed": parsed,
        "warnings": warnings,
    }


@mcp.tool()
def generate_names(
    object_type: str,
    objective: Optional[str] = None,
    product: Optional[str] = None,
    funnel: Optional[str] = None,
    budget_model: Optional[str] = None,
    audience_type: Optional[str] = None,
    age_range: Optional[str] = None,
    geo: str = "GR",
    exclusion_flag: str = "None",
    hook: Optional[str] = None,
    format_code: Optional[str] = None,
    version: str = "V1",
) -> dict:
    """
    Generate correctly named Meta Ads object following naming convention.

    Convention (learned from ExampleBrand):
    - Campaign: Objective | Product | Funnel | BudgetModel
    - Ad Set: AudienceType | AgeRange | Geo | ExclusionFlag
    - Ad: Hook | Format | Version

    Args:
        object_type: 'campaign', 'adset', or 'ad'.
        objective: For campaigns: Sales, Traffic, Leads, Awareness, Engagement.
        product: For campaigns: product/offer name (client-specific).
        funnel: For campaigns: TOFU, MOFU, BOFU, RT.
        budget_model: For campaigns: ABO, CBO.
        audience_type: For ad sets: Broad, Broad-Interest, RT-WV-30d, etc.
        age_range: For ad sets: 24-55, 18-45, All.
        geo: Country code (default GR).
        exclusion_flag: For ad sets: Adv, ExPurch, None.
        hook: For ads: concept name in kebab-case (e.g., Employee-Blame).
        format_code: For ads: REEL, VID, IMG, REEL+FEED.
        version: For ads: V1, V2, V3.
    """
    if object_type == "campaign":
        return generate_campaign_name(objective or "", product or "", funnel or "", budget_model or "")
    elif object_type == "adset":
        return generate_adset_name(audience_type or "", age_range or "", geo, exclusion_flag)
    elif object_type == "ad":
        return generate_ad_name(hook or "", format_code or "", version)
    else:
        return {"name": None, "valid": False, "errors": [f"Unknown object_type: '{object_type}'"]}
