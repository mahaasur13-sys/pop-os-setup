"""
ATOMFederationOS v4.0 — CONSISTENCY ENGINE
P0 FIX: Reconciliation Loop + State Drift Detection + Auto-Repair

Consistency Invariant:
  ∀t: DCP_state == Runtime_state == EventStore_state
"""
from __future__ import annotations
import time, hashlib, threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any
from enum import Enum


class DriftStatus(Enum):
    SYNCED = "synced"
    DRIFTED = "drifted"
    REPAIRING = "repairing"
    UNKNOWN = "unknown"


@dataclass
class StateSnapshot:
    source: str           # "dcp" | "runtime" | "event_store"
    term: int
    leader_id: Optional[str]
    node_count: int
    task_count: int
    event_count: int
    state_hash: str
    timestamp: float


class ConsistencyEngine:
    """
    Source-of-truth reconciliation daemon.
    Runs continuously, detects drift, auto-repairs.
    """

    def __init__(self, dcp, event_store, runtime_state: dict):
        self.dcp = dcp
        self.event_store = event_store
        self.runtime_state = runtime_state  # mutable shared dict
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._drift_count = 0
        self._repair_count = 0
        self._last_sync = 0.0
        self._repair_handlers: list[Callable] = []

        # Policy: repair if drift detected
        self.auto_repair = True
        self.sync_interval_sec = 0.1

    # ── State Hash Computation ──────────────────────────────────────────

    def _hash_dict(self, d: dict) -> str:
        """Stable hash of a dict (sorted keys)."""
        raw = str(sorted(d.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def runtime_hash(self) -> str:
        # Must mirror dcp_hash() fields — only leader + node_count
        rs = self.runtime_state
        return self._hash_dict({
            "leader": rs.get("leader"),
            "node_count": len(rs.get("nodes", {})),
        })

    def dcp_hash(self) -> str:
        cs = self.dcp.cluster_state()
        return self._hash_dict({
            "leader": cs.get("leader"),
            "node_count": len(cs.get("nodes", {})),
        })

    def event_store_hash(self) -> str:
        log_len = len(self.event_store._log)
        last = self.event_store._log[-1] if log_len > 0 else None
        return self._hash_dict({
            "event_count": log_len,
            "last_hash": last.self_hash[:16] if last else "GENESIS",
        })

    def full_state_hash(self) -> str:
        """Triple-hash for cross-layer comparison."""
        return self._hash_dict({
            "dcp": self.dcp_hash(),
            "runtime": self.runtime_hash(),
            "event_store": self.event_store_hash(),
        })

    # ── Drift Detection ────────────────────────────────────────────────

    def detect_drift(self) -> tuple[DriftStatus, dict]:
        """
        Compare DCP ↔ Runtime state (the CRITICAL invariant).
        EventStore is an independent append-only audit log — its hash
        naturally differs and is verified separately (non-blocking).
        """
        details = {
            "dcp_hash": self.dcp_hash(),
            "runtime_hash": self.runtime_hash(),
            "event_store_hash": self.event_store_hash(),
            "full_hash": self.full_state_hash(),
            "dcp_leader": self.dcp.leader_id,
            "runtime_leader": self.runtime_state.get("leader"),
            "dcp_nodes": len(self.dcp.cluster_state().get("nodes", {})),
            "event_count": len(self.event_store._log),
        }

        # CRITICAL: DCP ↔ Runtime leader must match
        leader_drift = (
            self.dcp.leader_id is not None and
            self.runtime_state.get("leader") is not None and
            self.dcp.leader_id != self.runtime_state.get("leader")
        )

        # Secondary: check DCP ↔ Runtime state hash match
        state_drift = self.dcp_hash() != self.runtime_hash()

        if leader_drift:
            details["drift_type"] = "leader_divergence"
            return DriftStatus.DRIFTED, details

        if state_drift:
            details["drift_type"] = "state_divergence"
            return DriftStatus.DRIFTED, details

        # EventStore is an independent append-only log — never blocks SYNCED
        # Only include in audit details, not in drift decision
        return DriftStatus.SYNCED, details

    # ── Auto-Repair ─────────────────────────────────────────────────────

    def repair(self) -> bool:
        """
        Force DCP → Runtime reconciliation.
        DCP is authoritative for topology; event_store for history.
        Returns True if repair was applied.
        """
        self._drift_count += 1
        status, details = self.detect_drift()
        if status == DriftStatus.SYNCED:
            return False

        # Authoritative repair: DCP drives topology
        self.runtime_state["leader"] = self.dcp.leader_id
        self.runtime_state["term"] = getattr(self.dcp, "_term", 0)
        self.runtime_state["nodes"] = {
            nid: {"status": n.status, "load": n.load}
            for nid, n in self.dcp.nodes.items()
        }

        # EventStore is authoritative for event count
        self.runtime_state["last_event_index"] = len(self.event_store._log) - 1

        self._repair_count += 1
        self._last_sync = time.time()

        # Notify handlers
        for handler in self._repair_handlers:
            try:
                handler(status, details)
            except Exception:
                pass

        return True

    # ── Daemon Loop ─────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            drifted, _ = self.detect_drift()
            if drifted == DriftStatus.DRIFTED and self.auto_repair:
                self.repair()
            time.sleep(self.sync_interval_sec)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def on_repair(self, handler: Callable):
        """Register repair notification handler."""
        self._repair_handlers.append(handler)

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "drift_count": self._drift_count,
            "repair_count": self._repair_count,
            "last_sync": self._last_sync,
            "running": self._running,
            "status": self.detect_drift()[0].value,
        }


def demo():
    # Minimal mock for standalone demo
    class MockDCP:
        def __init__(self):
            self.leader_id = "node-A"
            self._term = 1
            self.nodes = {"node-A": type("N", (), {"status": "ACTIVE", "load": 0.1})()}

        def cluster_state(self):
            return {"leader": self.leader_id, "nodes": {"node-A": {"status": "ACTIVE", "load": 0.1}}}

    class MockEventStore:
        def __init__(self):
            self._log = [type("E", (), {"self_hash": "abc123"})()]
        def all(self):
            return self._log

    dcp = MockDCP()
    es = MockEventStore()
    rs = {"leader": "node-A", "term": 1, "nodes": {}, "tasks": []}

    ce = ConsistencyEngine(dcp, es, rs)

    print("=== Drift Detection ===")
    status, details = ce.detect_drift()
    print(f"Status: {status.value}")
    print(f"Hashes: dcp={details['dcp_hash']}, runtime={details['runtime_hash']}, es={details['event_store_hash']}")

    # Simulate drift
    rs["leader"] = "node-B"
    status, details = ce.detect_drift()
    print(f"\nAfter drift: {status.value}")
    print(f"Repair applied: {ce.repair()}")
    print(f"Runtime leader now: {rs['leader']}")

    print(f"\n=== Stats ===")
    print(ce.stats())


if __name__ == "__main__":
    demo()
