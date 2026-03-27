"""
Setup readiness checker.

Read-only tool that validates MCP setup state and returns
structured pass/warn/fail results with exact fix instructions.

Does not modify any configuration. Does not automate Meta admin actions.
"""
import logging
import os
from pathlib import Path

from meta_ads_mcp.server import mcp
from meta_ads_mcp.core.api import api_client, MetaAPIError, GRAPH_API_VERSION
from meta_ads_mcp.core.utils import ensure_account_id_format

logger = logging.getLogger("meta-ads-mcp.setup")


@mcp.tool()
def run_setup_check() -> dict:
    """
    Check MCP setup readiness and return structured results.

    Validates token, permissions, account access, pages, Instagram identity,
    pixels, and local configuration. Returns pass/warn/fail for each check
    with exact fix instructions for failures.

    Read-only. Does not modify any configuration or Meta settings.
    """
    checks = []
    fix_instructions = []
    ready_accounts = []
    not_ready_accounts = []

    # ============================
    # A. Environment / Local Setup
    # ============================

    # A1: META_ACCESS_TOKEN
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        checks.append(_check("token_exists", "fail", "META_ACCESS_TOKEN is not set.", scope="global"))
        fix_instructions.append("Set META_ACCESS_TOKEN in your .env file. Generate a System User token at: business.facebook.com > Business Settings > System Users > [your user] > Generate New Token. Select permissions: ads_management, ads_read, business_management, pages_read_engagement, pages_manage_ads.")
        return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)
    else:
        checks.append(_check("token_exists", "pass", "META_ACCESS_TOKEN is set.", scope="global"))

    # A2: META_APP_SECRET
    app_secret = os.environ.get("META_APP_SECRET", "")
    if not app_secret:
        checks.append(_check("app_secret", "warn", "META_APP_SECRET not set. Recommended for production (enables appsecret_proof).", scope="global"))
    else:
        checks.append(_check("app_secret", "pass", "META_APP_SECRET is set.", scope="global"))

    # A3: VAULT_PATH (required for write operations - campaign/ad creation/update)
    vault_path = os.environ.get("VAULT_PATH", "")
    vault_available = False
    if not vault_path:
        checks.append(_check("vault_path", "fail", "VAULT_PATH not set. Required for campaign/ad creation and updates. Set VAULT_PATH to a directory path. Then run bootstrap_client_vault for each client.", scope="global"))
        fix_instructions.append("Set VAULT_PATH environment variable to a directory path (e.g., /Users/you/marketing-vault or C:\\Users\\you\\marketing-vault). Then run bootstrap_client_vault for each client account.")
    elif not Path(vault_path).is_dir():
        checks.append(_check("vault_path", "fail", f"VAULT_PATH set to '{vault_path}' but directory does not exist. Create it or fix the path.", scope="global"))
        fix_instructions.append(f"Create directory: mkdir -p {vault_path}")
    else:
        checks.append(_check("vault_path", "pass", f"VAULT_PATH set and exists: {vault_path}", scope="global"))
        vault_available = True

    # A4: accounts.yaml
    config_dir = Path(__file__).parent.parent.parent / "config"
    accounts_yaml = config_dir / "accounts.yaml"
    if not accounts_yaml.exists():
        checks.append(_check("accounts_yaml", "warn", "config/accounts.yaml not found. Run discover_all_accounts to populate it.", scope="global"))
    else:
        import yaml
        try:
            with open(accounts_yaml, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            clients = data.get("clients", data.get("accounts", {}))
            if not clients:
                checks.append(_check("accounts_yaml", "warn", "accounts.yaml exists but has no client entries. Run discover_all_accounts to populate.", scope="global"))
            else:
                checks.append(_check("accounts_yaml", "pass", f"accounts.yaml has {len(clients)} client(s) configured.", scope="global"))
        except Exception as e:
            checks.append(_check("accounts_yaml", "warn", f"accounts.yaml exists but could not be parsed: {e}", scope="global"))

    # A5: Graph API version (advisory only)
    checks.append(_check("api_version", "pass", f"Meta Graph API version: {GRAPH_API_VERSION}", scope="global"))

    # ============================
    # B. Token / Permission Readiness
    # ============================

    try:
        api_client._ensure_initialized()
    except MetaAPIError as e:
        checks.append(_check("token_valid", "fail", f"Token initialization failed: {e}", scope="global"))
        fix_instructions.append("Your META_ACCESS_TOKEN is invalid or expired. Generate a new System User token at business.facebook.com > Business Settings > System Users.")
        return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)

    # Token validity
    try:
        token_result = api_client.graph_get("/me", fields=["id", "name"])
        user_id = token_result.get("id", "unknown")
        user_name = token_result.get("name", "unknown")
        checks.append(_check("token_valid", "pass", f"Token valid. User: {user_name} ({user_id})", scope="global"))
    except MetaAPIError as e:
        checks.append(_check("token_valid", "fail", f"Token rejected by Meta API: {e}", scope="global"))
        fix_instructions.append("Your META_ACCESS_TOKEN is invalid or expired. Generate a new one.")
        return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)

    # Permission check
    try:
        perms_result = api_client.graph_get("/me/permissions")
        granted_perms = {p["permission"] for p in perms_result.get("data", []) if p.get("status") == "granted"}

        critical_perms = ["ads_management", "ads_read", "business_management"]
        warn_perms = ["pages_read_engagement", "pages_manage_ads"]

        for perm in critical_perms:
            if perm in granted_perms:
                checks.append(_check(f"perm_{perm}", "pass", f"Permission '{perm}' granted.", scope="global"))
            else:
                checks.append(_check(f"perm_{perm}", "fail", f"Critical permission '{perm}' NOT granted.", scope="global"))
                fix_instructions.append(f"Grant '{perm}' to your System User at business.facebook.com > Business Settings > System Users > [your user] > Assets.")

        for perm in warn_perms:
            if perm in granted_perms:
                checks.append(_check(f"perm_{perm}", "pass", f"Permission '{perm}' granted.", scope="global"))
            else:
                checks.append(_check(f"perm_{perm}", "warn", f"Permission '{perm}' not granted. Some page/ad operations may be limited.", scope="global"))

    except MetaAPIError as e:
        checks.append(_check("permissions", "warn", f"Could not check permissions: {e}", scope="global"))

    # ============================
    # C. Account / Asset Readiness
    # ============================

    try:
        accounts_result = api_client.graph_get("/me/adaccounts", fields=["id", "name", "account_status"], params={"limit": "50"})
        accounts = accounts_result.get("data", [])
    except MetaAPIError as e:
        checks.append(_check("accounts_accessible", "fail", f"Cannot list ad accounts: {e}", scope="global"))
        fix_instructions.append("Assign ad accounts to your System User at business.facebook.com > Business Settings > System Users > [your user] > Assets > Ad Accounts.")
        return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)

    if not accounts:
        checks.append(_check("accounts_accessible", "fail", "No ad accounts accessible.", scope="global"))
        fix_instructions.append("Assign at least one ad account to your System User.")
        return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)

    checks.append(_check("accounts_accessible", "pass", f"{len(accounts)} ad account(s) accessible.", scope="global"))

    # Per-account checks (limit to first 10 to avoid excessive API calls)
    for account in accounts[:10]:
        acct_id = account.get("id", "")
        acct_name = account.get("name", acct_id)
        acct_scope = f"account:{acct_id}"
        account_ready = True

        # Pages
        try:
            pages_result = api_client.graph_get(f"/{acct_id}/promote_pages", fields=["id", "name"], params={"limit": "10"})
            pages = pages_result.get("data", [])
            if pages:
                page_names = ", ".join(p.get("name", p.get("id", "?")) for p in pages[:3])
                checks.append(_check(f"{acct_id}_pages", "pass", f"Pages: {page_names}", scope=acct_scope))
            else:
                checks.append(_check(f"{acct_id}_pages", "warn", "No pages found. Ad creation requires a Facebook Page.", scope=acct_scope))
        except MetaAPIError:
            checks.append(_check(f"{acct_id}_pages", "warn", "Could not check pages.", scope=acct_scope))

        # Instagram identity
        try:
            ig_result = api_client.graph_get(f"/{acct_id}/instagram_accounts", fields=["id", "username"], params={"limit": "5"})
            ig_accounts = ig_result.get("data", [])
            if ig_accounts:
                ig_names = ", ".join(a.get("username", a.get("id", "?")) for a in ig_accounts[:2])
                checks.append(_check(f"{acct_id}_instagram", "pass", f"Instagram: {ig_names}", scope=acct_scope))
            else:
                checks.append(_check(f"{acct_id}_instagram", "warn", "No Instagram identity. Ads will be Facebook-only.", scope=acct_scope))
        except MetaAPIError:
            checks.append(_check(f"{acct_id}_instagram", "warn", "Could not check Instagram identity.", scope=acct_scope))

        # Pixel
        try:
            pixel_result = api_client.graph_get(f"/{acct_id}/adspixels", fields=["id", "name"], params={"limit": "5"})
            pixels = pixel_result.get("data", [])
            if pixels:
                pixel_names = ", ".join(p.get("name", p.get("id", "?")) for p in pixels[:2])
                checks.append(_check(f"{acct_id}_pixel", "pass", f"Pixel: {pixel_names}", scope=acct_scope))
            else:
                checks.append(_check(f"{acct_id}_pixel", "warn", "No pixel found. Tracking diagnostics and conversion optimization will be limited.", scope=acct_scope))
        except MetaAPIError:
            checks.append(_check(f"{acct_id}_pixel", "warn", "Could not check pixels.", scope=acct_scope))

        # Vault readiness per account
        if vault_available:
            from meta_ads_mcp.engine.storage import resolve_slug
            slug = resolve_slug(acct_id)
            if not slug:
                checks.append(_check(f"{acct_id}_vault", "fail",
                    "No client slug in accounts.yaml. Write operations will be blocked. Run bootstrap_client_vault after registering this account.",
                    scope=acct_scope))
            else:
                client_dir = Path(vault_path) / "01_CLIENTS" / slug
                if not client_dir.exists():
                    checks.append(_check(f"{acct_id}_vault", "fail",
                        f"Vault directory missing: 01_CLIENTS/{slug}/. Run bootstrap_client_vault with account_id='{acct_id}' to create it.",
                        scope=acct_scope))
                else:
                    profile = client_dir / "00-profile.md"
                    voice = client_dir / "04-brand-voice.md"
                    icps = client_dir / "02-icp-personas.md"
                    has_profile = profile.exists() and profile.stat().st_size > 50
                    has_voice = voice.exists() and voice.stat().st_size > 50
                    has_icps = icps.exists() and icps.stat().st_size > 50
                    important_count = sum(1 for f in ["05-messaging-house.md", "08-objections.md", "03-offers.md", "01-positioning.md", "matrix.md"]
                                          if (client_dir / f).exists() and (client_dir / f).stat().st_size > 50)

                    if has_profile and has_voice and has_icps and important_count >= 5:
                        vault_state = "production_ready"
                    elif has_profile and has_voice and has_icps and important_count >= 3:
                        vault_state = "partial"
                    elif has_profile:
                        vault_state = "minimal"
                    else:
                        vault_state = "empty"

                    if vault_state == "production_ready":
                        checks.append(_check(f"{acct_id}_vault", "pass",
                            f"Vault production-ready: 01_CLIENTS/{slug}/ - full copy/advisory capability.",
                            scope=acct_scope))
                    elif vault_state == "partial":
                        checks.append(_check(f"{acct_id}_vault", "pass",
                            f"Vault partial: 01_CLIENTS/{slug}/ - campaign/ad creation works. Fill more files for better copy.",
                            scope=acct_scope))
                    elif vault_state == "minimal":
                        missing = []
                        if not has_voice: missing.append("04-brand-voice.md")
                        if not has_icps: missing.append("02-icp-personas.md")
                        checks.append(_check(f"{acct_id}_vault", "warn",
                            f"Vault minimal: 01_CLIENTS/{slug}/ - campaign creation works but ad set/ad creation may be limited. Missing: {', '.join(missing)}",
                            scope=acct_scope))
                    else:
                        checks.append(_check(f"{acct_id}_vault", "fail",
                            f"Vault empty: 01_CLIENTS/{slug}/ exists but 00-profile.md is missing or empty. Fill it with account IDs.",
                            scope=acct_scope))
        else:
            # No vault at all - report once globally, not per-account
            pass

        # Determine account readiness
        has_fails = any(c["status"] == "fail" and c["scope"] == acct_scope for c in checks)
        if has_fails:
            not_ready_accounts.append({"id": acct_id, "name": acct_name})
        else:
            ready_accounts.append({"id": acct_id, "name": acct_name})

    return _build_result(checks, fix_instructions, ready_accounts, not_ready_accounts)


def _check(name: str, status: str, detail: str, scope: str = "global") -> dict:
    return {"name": name, "status": status, "detail": detail, "scope": scope}


def _build_result(checks: list, fix_instructions: list, ready_accounts: list, not_ready_accounts: list) -> dict:
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    if fail_count > 0:
        overall = "not_ready"
    elif warn_count > 0:
        overall = "ready_with_warnings"
    else:
        overall = "ready"

    return {
        "overall_status": overall,
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "total_checks": len(checks),
            "ready_accounts": len(ready_accounts),
            "not_ready_accounts": len(not_ready_accounts),
        },
        "checks": checks,
        "fix_instructions": fix_instructions if fix_instructions else None,
        "ready_accounts": ready_accounts,
        "not_ready_accounts": not_ready_accounts,
    }
