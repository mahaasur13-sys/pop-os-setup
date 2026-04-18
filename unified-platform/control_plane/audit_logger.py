"""
Audit Logger — Immutable Event Chain

Writes SHA-256-chained JSONL entries.
Supports chain verification via hash continuity check.
"""

import hashlib
import json
import os
import threading
from typing import Optional


class AuditLogger:
    """
    Immutable audit chain with hash linking.
    """

    def __init__(self, log_path: Optional[str] = None):
        self._log_path = log_path or os.environ.get(
            "CONTROL_PLANE_AUDIT_PATH",
            "/tmp/audit.jsonl",
        )
        self._lock = threading.Lock()
        self._last_hash = "0" * 64

    def log_event(
        self,
        event_type: str,
        job_id: str = "",
        metadata: Optional[dict] = None,
    ) -> str:
        entry = {
            "event_type": event_type,
            "job_id": job_id,
            "metadata": metadata or {},
            "prev_hash": self._last_hash,
        }
        entry_bytes = json.dumps(entry, sort_keys=True, default=str).encode()
        entry_hash = hashlib.sha256(entry_bytes).hexdigest()
        entry["hash"] = entry_hash

        with self._lock:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            self._last_hash = entry_hash

        return entry_hash

    def verify_chain(self) -> dict:
        if not os.path.exists(self._log_path):
            return {"valid": True, "total_entries": 0}

        with self._lock:
            with open(self._log_path) as f:
                lines = f.readlines()

        if not lines:
            return {"valid": True, "total_entries": 0}

        prev_hash = "0" * 64
        for line in lines:
            entry = json.loads(line)
            if entry.get("prev_hash") != prev_hash:
                return {"valid": False, "total_entries": len(lines)}
            prev_hash = entry.get("hash", "")
            if len(prev_hash) != 64:
                return {"valid": False, "total_entries": len(lines)}

        return {"valid": True, "total_entries": len(lines)}

    def read_events(self, job_id: Optional[str] = None) -> list:
        if not os.path.exists(self._log_path):
            return []
        with self._lock:
            with open(self._log_path) as f:
                lines = f.readlines()
        events = [json.loads(l) for l in lines]
        if job_id:
            events = [e for e in events if e.get("job_id") == job_id]
        return events
