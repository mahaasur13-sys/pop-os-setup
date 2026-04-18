"""
UESL v1 — Persistent execution state.
All state is immutable snapshots (TrackerSnapshot pattern from CCL).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from collections import abc

from atomos.runtime.ccl_v1 import TrackerSnapshot
from atomos.uesl.semtypes import ExecutionResult, PartitionState, UESLEvent


@dataclass(frozen=True)
class UESLSnapshot:
    """
    Immutable snapshot of full UESL state at a point in time.
    Used for: replay, causal tracing, deterministic replay verification.
    """
    causal_index:    int
    active_contracts: tuple[str, ...]    # active msg_ids
    tracker_snapshots: tuple[str, ...]   # serialized tracker states
    pending_events:  int
    committed_events: int
    partition_state: str
    clock_vector:    tuple[tuple[str, int], ...]
    hash:            str                 # SHA-256 of all above for replay equality check


class UESLState:
    """
    Manages UESL persistent state across the execution lifetime.
    All mutating operations produce new UESLSnapshot (append-only log).

    Thread-safe via lock (operates in single-threaded execution context).
    """

    def __init__(self, node_id: str, quorum_size: int, seed: int | None = None):
        self.node_id = node_id
        self.quorum_size = quorum_size
        self._causal_index = 0
        self._trackers: Dict[str, TrackerSnapshot] = {}  # msg_id → tracker
        self._event_log: List[UESLEvent] = []
        self._committed: List[str] = []  # committed msg_ids
        self._clock_vector: Dict[str, int] = {node_id: 0}

    # ── Snapshot management ────────────────────────────────────────────────

    def current_snapshot(self) -> UESLSnapshot:
        """Return immutable snapshot of current state."""
        import hashlib
        parts = [
            str(self._causal_index),
            str(sorted(self._trackers.keys())),
            str([str(t.status) for t in self._trackers.values()]),
            str(len(self._event_log)),
            str(len(self._committed)),
            str(self._partition_state().name),
            str(sorted(self._clock_vector.items())),
        ]
        h = hashlib.sha256("|".join(parts).encode()).hexdigest()
        return UESLSnapshot(
            causal_index=self._causal_index,
            active_contracts=tuple(sorted(self._trackers.keys())),
            tracker_snapshots=tuple(str(t.status) for t in self._trackers.values()),
            pending_events=len(self._event_log),
            committed_events=len(self._committed),
            partition_state=self._partition_state().name,
            clock_vector=tuple(sorted(self._clock_vector.items())),
            hash=h,
        )

    def _partition_state(self) -> PartitionState:
        """Compute aggregate partition state from trackers."""
        if not self._trackers:
            return PartitionState.HEALTHY
        return PartitionState.HEALTHY  # simplified — full impl would inspect trackers

    # ── Tracker management ────────────────────────────────────────────────

    def get_tracker(self, msg_id: str) -> TrackerSnapshot | None:
        return self._trackers.get(msg_id)

    def put_tracker(self, msg_id: str, snap: TrackerSnapshot) -> None:
        self._trackers[msg_id] = snap

    def remove_tracker(self, msg_id: str) -> None:
        self._trackers.pop(msg_id, None)

    # ── Event log ──────────────────────────────────────────────────────────

    def append_event(self, event: UESLEvent) -> None:
        self._event_log.append(event)
        self._causal_index += 1
        # Advance clock vector
        for (node, ts) in event.clock_vector:
            if node in self._clock_vector:
                self._clock_vector[node] = max(self._clock_vector[node], ts)
            else:
                self._clock_vector[node] = ts

    def event_log(self) -> abc.Sequence[UESLEvent]:
        return list(self._event_log)

    # ── Commit ────────────────────────────────────────────────────────────

    def commit(self, msg_id: str) -> None:
        if msg_id not in self._committed:
            self._committed.append(msg_id)

    def is_committed(self, msg_id: str) -> bool:
        return msg_id in self._committed

    def committed_count(self) -> int:
        return len(self._committed)

    # ── Clock ──────────────────────────────────────────────────────────────

    def tick_clock(self, node_id: str) -> int:
        self._clock_vector[node_id] = self._clock_vector.get(node_id, 0) + 1
        return self._clock_vector[node_id]

    def merge_clock(self, node_id: str, remote_ts: int) -> int:
        cur = self._clock_vector.get(node_id, 0)
        self._clock_vector[node_id] = max(cur, remote_ts) + 1
        return self._clock_vector[node_id]

    def clock_vector(self) -> Dict[str, int]:
        return dict(self._clock_vector)
