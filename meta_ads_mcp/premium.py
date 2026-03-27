"""
Premium feature detection.

Checks whether premium modules are available.
Public open-core users get core tools only.
Premium bundle users get the full 98-tool suite.
"""
import os

# Premium is available if the engine's premium modules exist
_PREMIUM_MARKER = os.path.join(
    os.path.dirname(__file__), "engine", "loop.py"
)

PREMIUM_AVAILABLE = os.path.exists(_PREMIUM_MARKER)


def require_premium(feature_name: str) -> dict:
    """Return an error dict if premium is not available."""
    if PREMIUM_AVAILABLE:
        return None  # Premium is available, proceed
    return {
        "error": f"'{feature_name}' is a premium feature. Available in the KonQuest Meta Ads MCP Premium bundle.",
        "blocked_at": "premium_required",
        "info": "Visit the product page for the premium bundle with 98 tools including advisory engine, vault intelligence, and optimization.",
    }
