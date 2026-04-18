"""
ATOMFederationOS v4.1 — PART 2: Leader Controller + Fencing
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import threading, time


class LeaderLeaseState(Enum):
    INACTIVE = "inactive"; CANDIDATE = "candidate"
    ACTIVE = "active"; EXPIRED = "expired"; REVOKED = "revoked"


@dataclass
class FenceToken:
    token: int; term: int; leader_id: str
    issued_at: float; expires_at: float
    def is_valid(self, now: float) -> bool:
        return now < self.expires_at


class PartitionSafeLeaderController:
    def __init__(self, node_id: str, total_nodes: int, lease_ttl_sec: float = 10.0):
        self.node_id = node_id; self.total_nodes = total_nodes
        self.quorum_size = (total_nodes // 2) + 1
        self.lease_ttl_sec = lease_ttl_sec
        self._current_term: int = 0
        self._lease: Optional[FenceToken] = None
        self._fence_counter: int = 0
        self._leader_history: List[tuple[int,str]] = []
        self._lock = threading.Lock()

    def current_term(self) -> int:
        return self._current_term

    def bump_term(self, candidate_id: str) -> int:
        with self._lock:
            self._current_term += 1
            self._leader_history.append((self._current_term, candidate_id))
            return self._current_term

    def update_term_if_newer(self, term: int) -> bool:
        with self._lock:
            if term > self._current_term:
                self._current_term = term; return True
            return False

    def grant_lease(self, leader_id: str, term: int) -> FenceToken:
        with self._lock:
            self._fence_counter += 1
            now = time.time()
            fence = FenceToken(token=self._fence_counter, term=term,
                leader_id=leader_id, issued_at=now, expires_at=now + self.lease_ttl_sec)
            self._lease = fence; return fence

    def renew_lease(self, leader_id: str) -> bool:
        with self._lock:
            if self._lease is None or self._lease.leader_id != leader_id:
                return False
            now = time.time()
            if now >= self._lease.expires_at: return False
            self._lease.expires_at = now + self.lease_ttl_sec; return True

    def revoke_lease(self, leader_id: str) -> bool:
        with self._lock:
            if self._lease is None or self._lease.leader_id != leader_id: return False
            self._lease = None; return True

    def get_valid_leader(self) -> tuple[Optional[str], Optional[FenceToken]]:
        with self._lock:
            if self._lease is None: return None, None
            now = time.time()
            if now < self._lease.expires_at: return self._lease.leader_id, self._lease
            return None, None

    def check_leader_lease(self, leader_id: str) -> tuple[bool, Optional[int]]:
        valid_leader, lease = self.get_valid_leader()
        if valid_leader == leader_id and lease is not None:
            return True, lease.token
        return False, None

    def is_split_brain(self, claims: Dict[str,int]) -> tuple[bool, Optional[str]]:
        if not claims: return False, None
        max_term = max(claims.values())
        claimants = {nid for nid, t in claims.items() if t == max_term}
        if len(claimants) > 1: return True, sorted(claimants)[0]
        return False, list(claimants)[0] if claimants else None

    def get_fence_token(self) -> tuple[int, int]:
        with self._lock:
            if self._lease is None: return -1, self._current_term
            return self._lease.token, self._lease.term

    def validate_fence_token(self, token: int, term: int) -> bool:
        with self._lock:
            if self._lease is None: return False
            return token >= self._lease.token and term == self._current_term

    def stats(self) -> dict:
        with self._lock:
            valid_leader, fence = self.get_valid_leader()
            return {"current_term": self._current_term,
                    "valid_leader": valid_leader,
                    "lease_active": fence is not None,
                    "fence_token": fence.token if fence else None,
                    "quorum_size": self.quorum_size}
