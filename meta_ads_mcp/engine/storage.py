"""
Persistent Vault Storage for Meta Ads Engine (v1.7).

Provides durable JSON read/write for:
- review queue items
- outcome snapshots
- execution journal entries
- operator digests

Storage paths:
  01_CLIENTS/{slug}/meta-ads/_system/review-queue.json
  01_CLIENTS/{slug}/meta-ads/_system/outcome-snapshots.json
  01_CLIENTS/{slug}/meta-ads/_system/execution-journal.json
  01_CLIENTS/{slug}/meta-ads/_system/operator-digests.json

Rules:
- JSON for machine read/write, append-safe
- No secrets, no raw giant payloads
- All writes are idempotent by ID
- Historical records are never deleted, only status-updated
- If file is malformed, fail loudly with repair suggestion
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("meta-ads-mcp.engine.storage")

VAULT_BASE = os.environ.get("VAULT_PATH", os.path.join(os.path.expanduser("~"), "marketing-vault"))

# Account ID -> slug mapping (loaded from registry at runtime)
_slug_cache: dict[str, str] = {}


def _load_slug_map():
    """Load account_id -> slug mapping from accounts.yaml."""
    if _slug_cache:
        return
    import yaml
    registry_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config", "accounts.yaml"
    )
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for slug, info in (data.get("clients", {}) or {}).items():
            acc_id = info.get("account_id", "")
            if acc_id:
                _slug_cache[acc_id] = slug
    except Exception as e:
        logger.warning("Could not load accounts.yaml for slug resolution: %s", e)


def resolve_slug(account_id: str) -> Optional[str]:
    """Resolve account_id to client slug."""
    _load_slug_map()
    return _slug_cache.get(account_id)


def resolve_vault_path(account_id: str, filename: str) -> Optional[str]:
    """Resolve full vault path for a system file."""
    slug = resolve_slug(account_id)
    if not slug:
        return None
    return os.path.join(VAULT_BASE, "01_CLIENTS", slug, "meta-ads", "_system", filename)


def ensure_vault_dir(account_id: str) -> bool:
    """Ensure the _system directory exists for this account."""
    slug = resolve_slug(account_id)
    if not slug:
        return False
    dir_path = os.path.join(VAULT_BASE, "01_CLIENTS", slug, "meta-ads", "_system")
    os.makedirs(dir_path, exist_ok=True)
    return True


def read_json_store(account_id: str, filename: str) -> tuple[Optional[list], Optional[str]]:
    """
    Read a JSON array store file.

    Returns (items, error). If error, items is None.
    """
    path = resolve_vault_path(account_id, filename)
    if not path:
        return None, f"Cannot resolve vault path for {account_id} (slug not found in registry)"

    if not os.path.exists(path):
        return [], None  # Empty store is valid

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return [], None
            data = json.loads(content)
            if not isinstance(data, list):
                return None, f"Store file {filename} is not a JSON array. Content type: {type(data).__name__}. Repair: replace with [] or fix manually."
            return data, None
    except json.JSONDecodeError as e:
        return None, f"Malformed JSON in {filename}: {e}. Repair: fix JSON syntax or replace with []."
    except OSError as e:
        return None, f"Cannot read {filename}: {e}"


def write_json_store(account_id: str, filename: str, items: list) -> Optional[str]:
    """
    Write full JSON array store. Returns error string or None on success.
    """
    if not ensure_vault_dir(account_id):
        return f"Cannot ensure vault directory for {account_id}"

    path = resolve_vault_path(account_id, filename)
    if not path:
        return f"Cannot resolve vault path for {account_id}"

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return None
    except OSError as e:
        return f"Cannot write {filename}: {e}"


def append_to_store(account_id: str, filename: str, new_item: dict) -> Optional[str]:
    """
    Append a single item to a JSON array store. Returns error or None.
    """
    items, err = read_json_store(account_id, filename)
    if err:
        return err
    items.append(new_item)
    return write_json_store(account_id, filename, items)


def update_item_in_store(account_id: str, filename: str, item_id_field: str, item_id: str, updates: dict) -> Optional[str]:
    """
    Update a single item in a store by ID field. Returns error or None.
    """
    items, err = read_json_store(account_id, filename)
    if err:
        return err

    found = False
    for item in items:
        if item.get(item_id_field) == item_id:
            item.update(updates)
            found = True
            break

    if not found:
        return f"Item {item_id_field}={item_id} not found in {filename}"

    return write_json_store(account_id, filename, items)


# --- Store filenames ---
REVIEW_QUEUE_FILE = "review-queue.json"
SNAPSHOTS_FILE = "outcome-snapshots.json"
JOURNAL_FILE = "execution-journal.json"
DIGESTS_FILE = "operator-digests.json"
