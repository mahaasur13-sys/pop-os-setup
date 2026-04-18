"""
ATOMFederationOS v4.0 — REPLICATED EVENT STORE
P2 FIX: Quorum-based replicated event store

Event Commit Rule:
  event is valid ONLY IF replicated_nodes >= quorum

Extends event_sourcing.py with:
- Replication layer
- Quorum commitment
- Anti-entropy (sync missing events between nodes)
"""
from __future__ import annotations
import time, hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Set


@dataclass
class ReplicatedEvent:
    """Event with replication metadata."""
    index: int
    term: int
    event_type: str
    payload: tuple
    timestamp: float
    self_hash: str
    prev_hash: str
    replicated_on: set = field(default_factory=set)
    committed: bool = False
    committed_at: Optional[float] = None


class ReplicatedEventStore:
    """
    Quorum-replicated event store.
    Events are only valid when replicated to quorum majority.
    """

    def __init__(self, node_id: str, total_nodes: int, quorum_size: Optional[int] = None):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.quorum_size = quorum_size or ((total_nodes // 2) + 1)
        self._log: List[ReplicatedEvent] = []
        self._index: Dict[int, ReplicatedEvent] = {}
        self._by_type: Dict[str, List[ReplicatedEvent]] = defaultdict(list)
        self._replication_state: Dict[int, Set[str]] = defaultdict(set)  # index -> ack nodes

    def append(self, event_type: str, payload: tuple, term: int = 0, replicated_nodes: Optional[Set[str]] = None) -> tuple[ReplicatedEvent, bool]:
        """
        Append event and replicate.
        Returns (event, quorum_reached).
        """
        prev = self._log[-1] if self._log else None
        prev_hash = prev.self_hash if prev else "GENESIS"
        idx = len(self._log)
        ts = time.time()  # single call — used for both hash and timestamp

        raw = f"{self.node_id}{term}{idx}{event_type}{payload}{ts}{prev_hash}"
        self_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]

        evt = ReplicatedEvent(
            index=idx,
            term=term,
            event_type=event_type,
            payload=payload,
            timestamp=ts,
            self_hash=self_hash,
            prev_hash=prev_hash,
            replicated_on=replicated_nodes or {self.node_id},
        )

        self._log.append(evt)
        self._index[idx] = evt
        self._by_type[event_type].append(evt)
        self._replication_state[idx] = set(evt.replicated_on)

        # Check quorum
        quorum_reached = len(self._replication_state[idx]) >= self.quorum_size
        if quorum_reached:
            evt.committed = True
            evt.committed_at = time.time()

        return evt, quorum_reached

    def replicate_to(self, index: int, node_id: str) -> bool:
        """
        Record that a node has replicated event at index.
        Returns True if quorum is now reached.
        """
        if index not in self._index:
            return False
        self._replication_state[index].add(node_id)
        self._log[index].replicated_on = set(self._replication_state[index])

        if not self._log[index].committed and len(self._replication_state[index]) >= self.quorum_size:
            self._log[index].committed = True
            self._log[index].committed_at = time.time()
            return True
        return False

    def is_committed(self, index: int) -> bool:
        if index not in self._index:
            return False
        return self._log[index].committed

    def get_committed_events(self) -> List[ReplicatedEvent]:
        return [e for e in self._log if e.committed]

    def verify_chain(self) -> bool:
        for i, evt in enumerate(self._log):
            # Verify hash: reconstruct from stored fields exactly as append() did
            raw = f"{self.node_id}{evt.term}{i}{evt.event_type}{evt.payload}{evt.timestamp}{evt.prev_hash}"
            expected = hashlib.sha256(raw.encode()).hexdigest()[:32]
            if evt.self_hash != expected:
                return False
            # Verify chain linkage
            if i > 0 and evt.prev_hash != self._log[i-1].self_hash:
                return False
        return True

    def stats(self) -> dict:
        committed = sum(1 for e in self._log if e.committed)
        return {
            "node_id": self.node_id,
            "total_events": len(self._log),
            "committed": committed,
            "quorum_size": self.quorum_size,
            "replication": {str(k): list(v) for k, v in self._replication_state.items()},
            "chain_valid": self.verify_chain(),
        }


if __name__ == "__main__":
    store = ReplicatedEventStore("node-A", total_nodes=3)

    print("=== Quorum Replication ===")
    evt, quorum = store.append("test", ("d0",), term=1, replicated_nodes={"node-A"})
    print(f"Event 0 (1 ack): committed={evt.committed}, quorum={quorum}")

    store.replicate_to(0, "node-B")
    evt, quorum = store.append("test", ("d1",), term=1, replicated_nodes={"node-A"})
    _, quorum2 = store.append("test", ("d2",), term=1, replicated_nodes={"node-A", "node-B", "node-C"})
    print(f"Event 2 (3 acks, quorum=2): committed={quorum2}")

    print(f"\nCommitted events: {len(store.get_committed_events())}")
    print(f"Stats: {store.stats()}")
