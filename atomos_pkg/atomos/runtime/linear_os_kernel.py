"""
ATOMFederationOS v4.1 — LINEARIZABLE DISTRIBUTED OS KERNEL
Corrective Upgrade: v4.1 (CONSISTENCY + LINEARIZABILITY + FAULT MODEL HARDENING)
"""
from __future__ import annotations
from enum import Enum
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from collections import defaultdict
import threading, hashlib, time, copy


# ── All enums in one place ─────────────────────────────────────────────
class ConvergenceState(Enum):
    DIVERGED   = "diverged"
    DETECTED   = "detected"
    PROPOSED   = "proposed"
    COMMITTED  = "committed"
    CONVERGED  = "converged"


class EventCommitState(Enum):
    APPENDING   = "appending"
    REPLICATING = "replicating"
    COMMITTED   = "committed"
    STABLE      = "stable"


class AckStatus(Enum):
    PENDING = "pending"
    ACKED   = "acked"
    NACKED  = "nacked"
    TIMEOUT = "timeout"


class AckSemantics(Enum):
    """F2 QuorumCommitEngine ACK semantic mode.
    STRICT:  duplicate ACK = rejected (False). REQUIRED for Byzantine audit & formal verification.
    IDEMPOTENT: duplicate ACK = success (True). Best for Raft/log systems with retries.
    """
    STRICT     = "strict"
    IDEMPOTENT = "idempotent"


# ── F2: SYSTEM-WIDE ACK SEMANTIC MODE ──────────────────────────────────
# ALL quorum decisions in ATOMFederationOS MUST respect this mode.
# To switch to IDEMPOTENT: ACK_SEMANTICS = AckSemantics.IDEMPOTENT
ACK_SEMANTICS = AckSemantics.STRICT


class LeaderLeaseState(Enum):
    INACTIVE  = "inactive"
    CANDIDATE = "candidate"
    ACTIVE    = "active"
    EXPIRED   = "expired"
    REVOKED   = "revoked"


class ReadOrigin(Enum):
    LEADER   = "leader"
    QUORUM   = "quorum"
    STALE    = "stale"


class ThrottleLevel(Enum):
    NONE     = "none"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class FaultType(Enum):
    CORRUPTED_LEADER = "corrupted_leader"
    PARTIAL_WRITE    = "partial_write"
    DELAYED_ACK      = "delayed_ack"
    DUPLICATE_REPLAY = "duplicate_replay"
    BYZANTINE_NODE   = "byzantine_node"
    PARTITION       = "partition"
    STALE_LEADER     = "stale_leader"


# ── F1: GLOBAL COMMIT INDEX ─────────────────────────────────────────────
@dataclass
class GlobalEvent:
    global_index: int
    term: int
    leader_id: str
    event_type: str
    payload: tuple
    timestamp: float
    causality_id: str
    parent_event_id: Optional[str]
    prev_global_index: int
    self_hash: str
    replicated_on: set = field(default_factory=set)
    commit_state: EventCommitState = EventCommitState.APPENDING

    def is_valid_leader(self, current_leader: str, current_term: int) -> bool:
        return self.leader_id == current_leader and self.term == current_term

    def is_quorum_committed(self, quorum_size: int) -> bool:
        return len(self.replicated_on) >= quorum_size


class GlobalCommitIndex:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._lock = threading.Lock()
        self._index: int = 0
        self._term: int = 0
        self._leader_id: Optional[str] = None
        self._node_indices: Dict[str, int] = defaultdict(int)

    def next_index(self, term: int, leader_id: str, _reserve: bool = False) -> int:
        with self._lock:
            idx = self._index + 1
            if not _reserve:
                self._index = idx
                self._term = term
                self._leader_id = leader_id
                self._node_indices[leader_id] = idx
            return idx

    def update_from_node(self, node_id: str, index: int) -> int:
        with self._lock:
            if index > self._node_indices[node_id]:
                gap = index - self._node_indices[node_id]
                self._node_indices[node_id] = index
                return gap
            return 0

    def get_global_index(self) -> int:
        return self._index

    def verify_ordering(self, events: List[GlobalEvent]) -> bool:
        for i in range(1, len(events)):
            if events[i].global_index != events[i-1].global_index + 1:
                return False
            if events[i].prev_global_index != events[i-1].global_index:
                return False
        return True


# ── F3: QUORUM COMMIT ENGINE ─────────────────────────────────────────────
@dataclass
class AckTracker:
    event_index: int
    term: int
    acks: Set[str] = field(default_factory=set)
    nacks: Set[str] = field(default_factory=set)
    pending: Set[str] = field(default_factory=set)
    status: AckStatus = AckStatus.PENDING
    created_at: float = field(default_factory=time.time)
    committed_at: Optional[float] = None


class QuorumCommitEngine:
    def __init__(self, total_nodes: int, node_ids: List[str]):
        self.total_nodes = total_nodes
        self.node_ids = set(node_ids)
        self.quorum_size: int = (total_nodes // 2) + 1
        self._trackers: Dict[int, AckTracker] = {}
        self._committed: Set[int] = set()
        self._lock = threading.Lock()

    def create_tracker(self, event_index: int, term: int,
                       initial_acks: Optional[Set[str]] = None) -> AckTracker:
        with self._lock:
            tracker = AckTracker(
                event_index=event_index, term=term,
                acks=set(initial_acks or set()),
                pending=set(self.node_ids - (initial_acks or set())),
            )
            self._trackers[event_index] = tracker
            self._check_quorum(tracker)
            return tracker

    def record_ack(self, event_index: int, node_id: str) -> tuple[bool, AckTracker]:
        """STRICT semantic: duplicate ACK = rejected (False).
        Required for Byzantine audit, formal verification, replay determinism.
        """
        with self._lock:
            if event_index not in self._trackers:
                return False, None
            tracker = self._trackers[event_index]

            # ── STRICT: reject if tracker already terminal ──────────────
            if tracker.status in (AckStatus.ACKED, AckStatus.NACKED):
                return False, tracker

            # ── STRICT: reject duplicate ACK (node already in acks set) ─
            if node_id in tracker.acks:
                return False, tracker

            # ── accept only if node is in pending set ───────────────────
            if node_id not in tracker.pending:
                return False, tracker

            tracker.pending.discard(node_id)
            tracker.acks.add(node_id)
            self._check_quorum(tracker)
            return tracker.status == AckStatus.ACKED, tracker

    def record_nack(self, event_index: int, node_id: str) -> bool:
        with self._lock:
            if event_index not in self._trackers:
                return False
            tracker = self._trackers[event_index]
            tracker.nacks.add(node_id)
            tracker.pending.discard(node_id)
            tracker.acks.discard(node_id)
            tracker.status = AckStatus.NACKED
            return True

    def _check_quorum(self, tracker: AckTracker):
        if tracker.status in (AckStatus.NACKED, AckStatus.ACKED):
            return
        if len(tracker.acks) >= self.quorum_size:
            tracker.status = AckStatus.ACKED
            tracker.committed_at = time.time()
            self._committed.add(tracker.event_index)

    def is_committed(self, event_index: int) -> bool:
        return event_index in self._committed

    def get_quorum_info(self, event_index: int) -> dict:
        if event_index not in self._trackers:
            return {"found": False}
        t = self._trackers[event_index]
        return {
            "found": True, "quorum_size": self.quorum_size,
            "acks": list(t.acks), "pending": list(t.pending),
            "nacks": list(t.nacks), "status": t.status.value,
            "committed": t.event_index in self._committed,
        }
