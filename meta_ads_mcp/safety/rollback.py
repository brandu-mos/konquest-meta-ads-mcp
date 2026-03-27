"""
Rollback engine for Meta Ads mutations.

Captures pre-mutation snapshots and restores previous state on demand.
Snapshots are stored as JSON files in meta-ads-mcp/rollback/{client-slug}/.

Phase: v1.0 (Foundation) - skeleton with interfaces.
Full implementation in Phase v1.3 when write operations are active.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("meta-ads-mcp.safety.rollback")


class RollbackManager:
    """
    Manages rollback snapshots for Meta Ads mutations.

    Lifecycle:
    1. Before mutation: capture_snapshot() saves current object state
    2. After mutation: log_mutation() records what changed
    3. On rollback: restore_snapshot() applies the saved state
    4. Cleanup: purge_expired() removes old snapshots (30-day retention)
    """

    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            base_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "rollback"
            )
        self.base_path = base_path

    def _client_path(self, client_slug: str) -> str:
        """Get rollback directory for a client."""
        path = os.path.join(self.base_path, client_slug)
        os.makedirs(path, exist_ok=True)
        return path

    def _snapshot_filename(self, object_type: str, object_id: str) -> str:
        """Generate a snapshot filename with timestamp."""
        ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        # Clean object_id (remove act_ prefix for readability)
        clean_id = object_id.replace("act_", "")
        return f"{ts}_{object_type}_{clean_id}.json"

    def capture_snapshot(
        self,
        client_slug: str,
        object_type: str,
        object_id: str,
        current_state: dict,
        action_description: str = "",
    ) -> str:
        """
        Capture a pre-mutation snapshot of an object's current state.

        Args:
            client_slug: Client identifier.
            object_type: 'campaign', 'adset', 'ad', 'creative'.
            object_id: Meta object ID.
            current_state: Current field values from the API.
            action_description: What mutation is about to happen.

        Returns:
            Path to the saved snapshot file.
        """
        snapshot = {
            "snapshot_version": "1.0",
            "captured_at": datetime.now().isoformat(),
            "client_slug": client_slug,
            "object_type": object_type,
            "object_id": object_id,
            "action_description": action_description,
            "state": current_state,
        }

        filename = self._snapshot_filename(object_type, object_id)
        filepath = os.path.join(self._client_path(client_slug), filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        logger.info("Rollback snapshot captured: %s", filepath)
        return filepath

    def list_snapshots(self, client_slug: str) -> list[dict]:
        """
        List available rollback snapshots for a client.

        Returns list of snapshot metadata (without full state data).
        """
        path = self._client_path(client_slug)
        snapshots = []

        for filename in sorted(os.listdir(path), reverse=True):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(path, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                snapshots.append({
                    "filename": filename,
                    "filepath": filepath,
                    "captured_at": data.get("captured_at"),
                    "object_type": data.get("object_type"),
                    "object_id": data.get("object_id"),
                    "action_description": data.get("action_description", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return snapshots

    def get_snapshot(self, filepath: str) -> Optional[dict]:
        """Load a specific snapshot by filepath."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("Could not load snapshot %s: %s", filepath, e)
            return None

    def restore_snapshot(self, filepath: str, mode: str = "safe_pause", confirm: bool = False) -> dict:
        """
        Restore an object to a previous snapshot state.

        Modes:
        - exact_revert: restore all captured fields (status, budget, targeting)
        - safe_pause: restore budget/targeting, always set status=PAUSED (default, safest)

        Process:
        1. Load snapshot
        2. Read current state from API
        3. Build restore payload (filtered to restorable fields)
        4. Apply via Meta API
        5. Always PAUSE after restore (safety default in safe_pause mode)
        6. Verify

        Args:
            filepath: Path to snapshot JSON file.
            mode: "exact_revert" or "safe_pause" (default).
            confirm: Must be True to execute. False = dry run.
        """
        snapshot = self.get_snapshot(filepath)
        if not snapshot:
            return {"status": "error", "message": f"Snapshot not found: {filepath}",
                    "blocked_at": "snapshot_load"}

        object_type = snapshot.get("object_type")
        object_id = snapshot.get("object_id")
        saved_state = snapshot.get("state", {})

        if not object_id:
            return {"status": "error", "message": "Snapshot has no object_id",
                    "blocked_at": "snapshot_data"}

        if mode not in ("exact_revert", "safe_pause"):
            return {"status": "error", "message": f"Invalid mode: {mode}. Use 'exact_revert' or 'safe_pause'.",
                    "blocked_at": "input_validation"}

        # Determine restorable fields per object type
        restorable = self._get_restorable_fields(object_type, saved_state, mode)
        if not restorable["fields"]:
            return {
                "status": "error",
                "message": f"No restorable fields found in snapshot for {object_type} {object_id}",
                "blocked_at": "insufficient_data",
                "snapshot_fields": list(saved_state.keys()),
            }

        # Dry run
        if not confirm:
            return {
                "status": "dry_run",
                "mode": mode,
                "object_type": object_type,
                "object_id": object_id,
                "would_restore": restorable["fields"],
                "would_pause": mode == "safe_pause",
                "captured_at": snapshot.get("captured_at"),
                "note": "Set confirm=True to execute restore.",
            }

        # Execute restore
        from meta_ads_mcp.core.api import api_client, MetaAPIError
        api_client._ensure_initialized()

        try:
            # Read current state before restore
            current = api_client.graph_get(f"/{object_id}", fields=["id", "name", "status", "daily_budget"])
        except MetaAPIError as e:
            return {"status": "error", "message": f"Cannot read current state of {object_id}: {e}",
                    "blocked_at": "pre_restore_read"}

        # Build API payload
        payload = {}
        for field, value in restorable["fields"].items():
            payload[field] = value

        # In safe_pause mode, always set PAUSED regardless of snapshot status
        if mode == "safe_pause":
            payload["status"] = "PAUSED"

        # Apply
        try:
            api_client.graph_post(f"/{object_id}", data=payload)
        except MetaAPIError as e:
            return {
                "status": "error",
                "message": f"Restore failed for {object_id}: {e}",
                "blocked_at": "api_restore",
                "attempted_payload": payload,
            }

        # Verify
        try:
            after = api_client.graph_get(f"/{object_id}", fields=list(payload.keys()) + ["id", "status"])
            verified = after.get("status") == payload.get("status", after.get("status"))
        except MetaAPIError:
            verified = False

        logger.info("Rollback restored %s %s (mode=%s, verified=%s)", object_type, object_id, mode, verified)

        return {
            "status": "restored",
            "mode": mode,
            "object_type": object_type,
            "object_id": object_id,
            "restored_fields": payload,
            "before_state": {
                "status": current.get("status"),
                "daily_budget": current.get("daily_budget"),
            },
            "after_state": {
                "status": after.get("status") if verified else "unknown",
            },
            "verified": verified,
            "captured_at": snapshot.get("captured_at"),
        }

    def _get_restorable_fields(self, object_type: str, saved_state: dict, mode: str) -> dict:
        """Determine which fields can be safely restored."""
        # Fields that are safe to restore per object type
        RESTORABLE = {
            "campaign": ["status", "daily_budget", "lifetime_budget", "name"],
            "adset": ["status", "daily_budget", "lifetime_budget", "name", "bid_amount"],
            "ad": ["status", "name"],
        }

        allowed = RESTORABLE.get(object_type, ["status"])
        fields = {}

        for field in allowed:
            if field in saved_state and saved_state[field] is not None:
                # In safe_pause mode, skip restoring status (we always PAUSE)
                if mode == "safe_pause" and field == "status":
                    continue
                fields[field] = saved_state[field]

        return {"fields": fields, "skipped": [f for f in saved_state if f not in allowed]}

    def purge_expired(self, client_slug: str, retention_days: int = 30) -> dict:
        """
        Remove rollback snapshots older than retention period.

        Args:
            client_slug: Client identifier.
            retention_days: Days to keep snapshots (default 30).

        Returns:
            dict with count of purged and remaining snapshots.
        """
        from datetime import timedelta

        path = self._client_path(client_slug)
        cutoff = datetime.now() - timedelta(days=retention_days)
        purged = 0
        remaining = 0

        for filename in os.listdir(path):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(path, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                captured = datetime.fromisoformat(data.get("captured_at", ""))
                if captured < cutoff:
                    os.remove(filepath)
                    purged += 1
                else:
                    remaining += 1
            except (json.JSONDecodeError, ValueError, OSError):
                remaining += 1

        logger.info("Purged %d expired snapshots for %s (%d remaining)", purged, client_slug, remaining)
        return {"purged": purged, "remaining": remaining}


# Module-level singleton
rollback_manager = RollbackManager()
