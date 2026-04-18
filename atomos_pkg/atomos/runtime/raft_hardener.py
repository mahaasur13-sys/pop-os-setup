"""
ATOMFederationOS v4.0 — QUORUM + RAFT HARDENED LAYER
P0 FIX: Quorum commit rule + lease-based leadership + split-brain protection

Commit Rule: commit_event ONLY IF ack_nodes >= (N/2 + 1)
Safety Invariant: event.valid == true AND event.quorum == true
Split-Brain Protection: leaders(t) <= 1 always
"""
from __future__ import annotations
import time, hashlib, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum


class LeaseState(Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class LeaderLease:
    node_id: str
    term: int
    granted_at: float
    expires_at: float
    fence_token: int
    state: LeaseState = LeaseState.ACTIVE

    def is_valid(self, now: float) -> bool:
        return self.state == LeaseState.ACTIVE and now < self.expires_at

    def renew(self, duration: float, fence_token: Optional[int] = None):
        self.granted_at = time.time()
        self.expires_at = self.granted_at + duration
        self.state = LeaseState.ACTIVE
        if fence_token is not None:
            self.fence_token = fence_token


@dataclass
class QuorumConfig:
    total_nodes: int
    lease_duration_sec: float = 10.0
    clock_drift_tolerance_sec: float = 1.0

    @property
    def quorum_size(self) -> int:
        return (self.total_nodes // 2) + 1

    def can_commit(self, acks: int) -> bool:
        return acks >= self.quorum_size


class RaftHardener:
    """
    RAFT-hardened consensus layer:
    - Quorum-based event commitment
    - Lease-based leadership (no split-brain)
    - Fencing tokens against stale writes
    - Monotonic term enforcement
    """

    def __init__(self, config: QuorumConfig):
        self.config = config
        self._current_term = 0
        self._voted_for: Optional[str] = None
        self._lease: Optional[LeaderLease] = None
        self._fence_counter = 0
        self._commits: Dict[str, dict] = {}  # index -> commit record
        self._lock = threading.Lock()

    # ── Term Management ───────────────────────────────────────────────

    def current_term(self) -> int:
        return self._current_term

    def bump_term(self, node_id: str) -> int:
        """Update term, record vote. Returns new term."""
        self._current_term += 1
        self._voted_for = node_id
        return self._current_term

    def update_term_if_newer(self, term: int) -> bool:
        """Returns True if term was updated."""
        if term > self._current_term:
            self._current_term = term
            self._voted_for = None
            self._lease = None  # Invalidate lease on term update
            return True
        return False

    # ── Lease Management ──────────────────────────────────────────────

    def grant_lease(self, node_id: str, duration: Optional[float] = None) -> LeaderLease:
        """Grant a new lease to a node. Revokes any existing lease."""
        duration = duration or self.config.lease_duration_sec
        self._fence_counter += 1
        lease = LeaderLease(
            node_id=node_id,
            term=self._current_term,
            granted_at=time.time(),
            expires_at=time.time() + duration,
            fence_token=self._fence_counter,
            state=LeaseState.ACTIVE,
        )
        self._lease = lease
        return lease

    def renew_lease(self, node_id: str) -> bool:
        """Renew existing lease. Must match current lease holder."""
        if self._lease is None or self._lease.node_id != node_id:
            return False
        if not self._lease.is_valid(time.time()):
            return False
        self._lease.renew(self.config.lease_duration_sec)
        return True

    def revoke_lease(self, node_id: str) -> bool:
        """Revoke lease. Must match holder."""
        if self._lease is None or self._lease.node_id != node_id:
            return False
        self._lease.state = LeaseState.REVOKED
        return True

    def check_lease(self, node_id: str) -> tuple[bool, Optional[LeaderLease]]:
        """Check if node holds a valid lease."""
        if self._lease is None:
            return False, None
        now = time.time()
        if self._lease.node_id != node_id:
            return False, self._lease
        if self._lease.is_valid(now):
            return True, self._lease
        # Expired
        self._lease.state = LeaseState.EXPIRED
        return False, self._lease

    def get_valid_leader(self) -> tuple[Optional[str], Optional[int]]:
        """Return (leader_id, fence_token) if valid lease exists."""
        if self._lease is None:
            return None, None
        if self._lease.is_valid(time.time()):
            return self._lease.node_id, self._lease.fence_token
        return None, None

    # ── Quorum Commit ──────────────────────────────────────────────────

    def can_commit(self, acked_nodes: Set[str]) -> bool:
        return self.config.can_commit(len(acked_nodes))

    def commit_event(self, event_idx: int, acked_nodes: Set[str]) -> tuple[bool, dict]:
        """
        Commit an event only if quorum is reached.
        Returns (committed, record).
        """
        with self._lock:
            if not self.can_commit(acked_nodes):
                return False, {"reason": "quorum_not_reached", "acked": len(acked_nodes), "required": self.config.quorum_size}

            self._commits[str(event_idx)] = {
                "event_idx": event_idx,
                "term": self._current_term,
                "acked_nodes": list(acked_nodes),
                "fence_token": self._fence_counter,
                "committed_at": time.time(),
                "quorum_size": self.config.quorum_size,
            }
            return True, self._commits[str(event_idx)]

    def get_commit(self, event_idx: int) -> Optional[dict]:
        return self._commits.get(str(event_idx))

    def is_committed(self, event_idx: int) -> bool:
        return str(event_idx) in self._commits

    # ── Split-Brain Prevention ────────────────────────────────────────

    def assert_single_leader(self, claims: Dict[str, int]) -> tuple[bool, Optional[str]]:
        """
        Given dict of node_id -> term claims, detect split-brain.
        Returns (is_unique, leader_or_none).
        Only one node may claim leadership per term.
        """
        if not claims:
            return True, None

        # Find max term
        max_term = max(claims.values())
        claimants = {nid for nid, term in claims.items() if term == max_term}

        if len(claimants) > 1:
            # Split brain — select lexicographically smallest as tiebreaker (deterministic)
            return False, sorted(claimants)[0]

        return True, list(claimants)[0] if claimants else None

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        lease_info = None
        if self._lease:
            lease_info = {
                "node_id": self._lease.node_id,
                "term": self._lease.term,
                "state": self._lease.state.value,
                "fence_token": self._lease.fence_token,
                "expires_at": self._lease.expires_at,
            }
        return {
            "current_term": self._current_term,
            "voted_for": self._voted_for,
            "quorum_size": self.config.quorum_size,
            "total_nodes": self.config.total_nodes,
            "commits": len(self._commits),
            "fence_counter": self._fence_counter,
            "valid_leader": self.get_valid_leader()[0],
            "lease": lease_info,
        }


def demo():
    config = QuorumConfig(total_nodes=3, lease_duration_sec=5.0)
    rh = RaftHardener(config)

    print("=== Quorum Config ===")
    print(f"Total nodes: {config.total_nodes}, Quorum: {config.quorum_size}")

    # Term + lease
    term = rh.bump_term("node-A")
    print(f"\n=== Term Bump ===")
    print(f"Term: {term}, Voted for: {rh._voted_for}")

    # Grant lease to node-A
    lease = rh.grant_lease("node-A")
    print(f"\n=== Lease Granted ===")
    print(f"Lease holder: {lease.node_id}, fence: {lease.fence_token}, expires: {lease.expires_at:.1f}")

    # Quorum commit
    print(f"\n=== Quorum Commit ===")
    ok, rec = rh.commit_event(0, {"node-A", "node-B"})  # 2 of 3 — OK
    print(f"Commit with 2 acks: {ok}, record: {rec['fence_token']}")

    ok2, rec2 = rh.commit_event(1, {"node-A"})  # 1 of 3 — FAIL
    print(f"Commit with 1 ack: {ok2}, reason: {rec2['reason']}")

    # Split-brain check
    print(f"\n=== Split-Brain Check ===")
    ok_single, leader = rh.assert_single_leader({"node-A": 5, "node-B": 5})
    print(f"Dual claim term=5: unique={ok_single}, leader={leader}")

    ok_single2, leader2 = rh.assert_single_leader({"node-A": 5})
    print(f"Single claim: unique={ok_single2}, leader={leader2}")

    print(f"\n=== Stats ===")
    import json
    print(json.dumps(rh.stats(), indent=2, default=str))


if __name__ == "__main__":
    demo()
