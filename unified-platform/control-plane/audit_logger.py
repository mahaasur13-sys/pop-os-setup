"""
Control Plane — Audit Logger
Immutable event chain for compliance and debugging.
Every job transition is logged with cryptographic proof.
"""

import json
import hashlib
import time
from typing import Optional
from pathlib import Path


class AuditLogger:
    """
    Immutable audit log with hash chain.

    Each entry contains:
        - timestamp
        - event_type
        - job_id
        - payload
        - prev_hash (chain integrity)
        - entry_hash (self-verifying)
    """

    def __init__(self, log_path: str = "/var/log/control-plane/audit.jsonl"):
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._load_last_hash()

    def _load_last_hash(self) -> str:
        """Load the hash of the last entry for chain continuity."""
        if not self._log_path.exists():
            return "GENESIS"
        with open(self._log_path, "rb") as f:
            f.seek(-200, 2)  # Read last entry
            last_line = f.readline()
            if last_line:
                entry = json.loads(last_line)
                return entry.get("entry_hash", "GENESIS")
        return "GENESIS"

    def _compute_hash(self, entry: dict) -> str:
        """SHA-256 hash of entry contents."""
        payload = {
            k: v for k, v in entry.items() if k not in ("prev_hash", "entry_hash")
        }
        chain_input = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(chain_input.encode()).hexdigest()

    def log_event(self, event_type: str, **kwargs) -> str:
        """
        Append an immutable event to the audit chain.
        Returns the entry hash.
        """
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "prev_hash": self._last_hash,
            **kwargs,
        }

        entry["entry_hash"] = self._compute_hash(entry)

        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        self._last_hash = entry["entry_hash"]
        return entry["entry_hash"]

    def verify_chain(self) -> dict:
        """
        Verify integrity of the entire audit chain.
        Returns report with:
            - valid: bool
            - total_entries: int
            - broken_at: int (if invalid)
        """
        if not self._log_path.exists():
            return {"valid": True, "total_entries": 0}

        entries = []
        with open(self._log_path) as f:
            for line in f:
                entries.append(json.loads(line))

        prev_hash = "GENESIS"
        for i, entry in enumerate(entries):
            if entry["prev_hash"] != prev_hash:
                return {"valid": False, "total_entries": i, "broken_at": i}
            computed = self._compute_hash(entry)
            if computed != entry["entry_hash"]:
                return {"valid": False, "total_entries": i, "broken_at": i}
            prev_hash = entry["entry_hash"]

        return {"valid": True, "total_entries": len(entries)}

    def get_events_for_job(self, job_id: str) -> list:
        """Retrieve all events for a specific job."""
        events = []
        if not self._log_path.exists():
            return events
        with open(self._log_path) as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("job_id") == job_id:
                    events.append(entry)
        return events
