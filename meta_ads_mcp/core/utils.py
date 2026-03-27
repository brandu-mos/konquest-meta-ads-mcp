"""
Shared utilities for the Meta Ads MCP server.

Provides common helpers for pagination, field selection,
data formatting, and date handling.
"""
import json
import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("meta-ads-mcp.utils")


def ensure_account_id_format(account_id: str) -> str:
    """Ensure account ID has the 'act_' prefix."""
    if not account_id.startswith("act_"):
        return f"act_{account_id}"
    return account_id


def format_budget_cents_to_currency(cents: int | str, currency: str = "EUR") -> str:
    """Convert Meta API budget (in cents) to human-readable currency string."""
    value = int(cents) / 100
    return f"{currency} {value:.2f}"


def currency_to_cents(amount: float) -> str:
    """Convert a currency amount to Meta API cents format (as string)."""
    return str(int(amount * 100))


def safe_json_serialize(data: Any) -> str:
    """
    Serialize data to JSON with safe Greek text handling.

    Uses ensure_ascii=False to preserve Greek characters as-is
    instead of escaping to \\uXXXX sequences.
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def normalize_greek_text(text: str) -> str:
    """
    Normalize text using NFC (canonical composition).

    Ensures consistent representation of Greek characters with accents.
    E.g., alpha + combining accent -> precomposed alpha with accent.
    """
    return unicodedata.normalize("NFC", text)


def parse_date_range(preset: str) -> tuple[str, str]:
    """
    Parse a date range preset into start/end date strings.

    Supported presets:
    - today, yesterday, this_week, last_week
    - last_7d, last_14d, last_30d, last_90d
    - this_month, last_month, this_quarter, this_year

    Returns (start_date, end_date) as 'YYYY-MM-DD' strings.
    """
    today = datetime.now().date()

    presets = {
        "today": (today, today),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "last_7d": (today - timedelta(days=7), today),
        "last_14d": (today - timedelta(days=14), today),
        "last_30d": (today - timedelta(days=30), today),
        "last_90d": (today - timedelta(days=90), today),
    }

    if preset in presets:
        start, end = presets[preset]
        return start.isoformat(), end.isoformat()

    if preset == "this_week":
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()

    if preset == "last_week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start.isoformat(), end.isoformat()

    if preset == "this_month":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat()

    if preset == "last_month":
        first_of_month = today.replace(day=1)
        end = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
        return start.isoformat(), end.isoformat()

    if preset == "this_quarter":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=quarter_start_month, day=1)
        return start.isoformat(), today.isoformat()

    if preset == "this_year":
        start = today.replace(month=1, day=1)
        return start.isoformat(), today.isoformat()

    # If not a preset, assume it's already a date range "YYYY-MM-DD,YYYY-MM-DD"
    if "," in preset:
        parts = preset.split(",")
        return parts[0].strip(), parts[1].strip()

    raise ValueError(f"Unknown date range preset: {preset}")


def truncate_for_log(text: str, max_length: int = 200) -> str:
    """Truncate text for log entries, preserving Greek characters."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_timestamp() -> str:
    """Return current timestamp in ISO-8601 format for vault logging."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")
