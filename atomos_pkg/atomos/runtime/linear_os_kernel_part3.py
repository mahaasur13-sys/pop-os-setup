"""
ATOMFederationOS v4.1 — PART 3: ConvergenceSM + LinearizableSM + Byzantine
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from collections import defaultdict
import threading, hashlib, time, copy

# Single source of truth — all parts import from here
import linear_os_kernel
ConvergenceState = linear_os_kernel.ConvergenceState


class ReadOrigin(Enum):
    LEADER = "leader"; QUORUM = "quorum"; STALE = "stale"


class FaultType(Enum):
    CORRUPTED_LEADER = "corrupted_leader"; PARTIAL_WRITE = "partial_write"
    DELAYED_ACK = "delayed_ack"; DUPLICATE_REPLAY = "duplicate_replay"
    BYZANTINE_NODE = "byzantine_node"; PARTITION = "partition"; STALE_LEADER = "stale_leader"


# ── F5: ConvergenceStateMachine ─────────────────────────────────────────
@dataclass
class ReconciliationRecord:
    state: ConvergenceState; source_state: dict; target_state: dict
    repair_action: str; repair_id: str; proposed_at: float
    committed_at: Optional[float] = None; converged_at: Optional[float] = None


class ConvergenceStateMachine:
    def __init__(self, max_repair_age_sec: float = 30.0):
        self.max_repair_age_sec = max_repair_age_sec
        self._records: Dict[str, ReconciliationRecord] = {}
        self._lock = threading.Lock()

    def _hash_state(self, state: dict) -> str:
        raw = str(sorted(state.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def detect_divergence(self, source: dict, target: dict,
                          repair_action: str) -> tuple[ConvergenceState, str]:
        with self._lock:
            repair_id = f"r-{self._hash_state(source)}-{self._hash_state(target)}"
            if repair_id in self._records:
                return self._records[repair_id].state, repair_id
            rec = ReconciliationRecord(
                state=ConvergenceState.DIVERGED,
                source_state=copy.deepcopy(source),
                target_state=copy.deepcopy(target),
                repair_action=repair_action, repair_id=repair_id,
                proposed_at=time.time())
            self._records[repair_id] = rec
            return ConvergenceState.DIVERGED, repair_id

    def advance(self, repair_id: str, new_state: ConvergenceState) -> bool:
        with self._lock:
            if repair_id not in self._records: return False
            rec = self._records[repair_id]
            valid_from = {
                ConvergenceState.DIVERGED: {ConvergenceState.DETECTED},
                ConvergenceState.DETECTED: {ConvergenceState.PROPOSED},
                ConvergenceState.PROPOSED: {ConvergenceState.COMMITTED},
                ConvergenceState.COMMITTED: {ConvergenceState.CONVERGED},
                ConvergenceState.CONVERGED: set()}
            if new_state not in valid_from.get(rec.state, set()): return False
            rec.state = new_state
            if new_state == ConvergenceState.COMMITTED: rec.committed_at = time.time()
            elif new_state == ConvergenceState.CONVERGED: rec.converged_at = time.time()
            return True

    def get_record(self, repair_id: str) -> Optional[ReconciliationRecord]:
        return self._records.get(repair_id)

    def get_active_repairs(self) -> List[ReconciliationRecord]:
        return [r for r in self._records.values()
                if r.state != ConvergenceState.CONVERGED]


# ── F2: LinearizableStateMachine ────────────────────────────────────────
class PartitionSafeLeaderController: pass  # forward ref, filled by part2
class QuorumCommitEngine: pass


@dataclass
class ReadIndexEntry:
    index: int; term: int; leader_id: str; read_at: float
    fence_token: int; valid_until: float; origin: ReadOrigin


class LinearizableStateMachine:
    def __init__(self, leader_controller, quorum_engine):
        self.lc = leader_controller; self.qe = quorum_engine
        self._state: Dict[str, Any] = {}
        self._read_index_history: List[ReadIndexEntry] = []
        self._lock = threading.Lock()
        self._last_applied_index: int = 0

    def read(self, key: str, require_linearizable: bool = True) -> tuple[Any, ReadOrigin]:
        with self._lock:
            valid_leader, fence = self.lc.get_valid_leader()
            if not require_linearizable:
                return self._state.get(key), ReadOrigin.STALE
            if valid_leader is not None:
                self._read_index_history.append(ReadIndexEntry(
                    index=self._last_applied_index, term=self.lc.current_term(),
                    leader_id=valid_leader, read_at=time.time(),
                    fence_token=fence.token if fence else -1,
                    valid_until=time.time() + self.lc.lease_ttl_sec,
                    origin=ReadOrigin.LEADER))
                return self._state.get(key), ReadOrigin.LEADER
            committed = [idx for idx in self.qe._committed if self.qe.is_committed(idx)]
            max_committed = max(committed) if committed else 0
            if max_committed > 0:
                self._last_applied_index = max_committed
                return self._state.get(f"idx_{max_committed}"), ReadOrigin.QUORUM
            return None, ReadOrigin.STALE

    def apply(self, key: str, value: Any, global_index: int) -> bool:
        with self._lock:
            if not self.qe.is_committed(global_index): return False
            self._state[key] = value
            self._state[f"idx_{global_index}"] = value
            self._last_applied_index = max(self._last_applied_index, global_index)
            return True


# ── F6: ByzantineFaultInjector ──────────────────────────────────────────
@dataclass
class FaultInjection:
    fault_type: FaultType; target_node: str; injected_at: float; payload: dict


class ByzantineFaultInjector:
    def __init__(self, total_nodes: int):
        self.total_nodes = total_nodes
        self.quorum_size = (total_nodes // 2) + 1
        self._faults: List[FaultInjection] = []
        self._byzantine_nodes: Set[str] = set()
        self._partitions: List[Set[str]] = []
        self._delayed_acks: Dict[str, float] = {}
        self._duplicate_events: Dict[str, List[float]] = defaultdict(list)
        self._corrupted_leaders: Dict[str, int] = {}
        self._lock = threading.Lock()

    def inject_byzantine_node(self, node_id: str, fault_desc: str = "") -> FaultInjection:
        with self._lock:
            fi = FaultInjection(FaultType.BYZANTINE_NODE, node_id, time.time(), {"desc": fault_desc})
            self._faults.append(fi); self._byzantine_nodes.add(node_id); return fi

    def inject_corrupted_leader_claim(self, node_id: str, fake_term: int) -> FaultInjection:
        with self._lock:
            fi = FaultInjection(FaultType.CORRUPTED_LEADER, node_id, time.time(), {"fake_term": fake_term})
            self._faults.append(fi); self._corrupted_leaders[node_id] = fake_term; return fi

    def inject_network_partition(self, partition_a: Set[str], partition_b: Set[str]) -> FaultInjection:
        with self._lock:
            fi = FaultInjection(FaultType.PARTITION, "NET", time.time(),
                {"partition_a": list(partition_a), "partition_b": list(partition_b)})
            self._faults.append(fi)
            self._partitions.append(partition_a); self._partitions.append(partition_b); return fi

    def inject_delayed_ack(self, node_id: str, delay_sec: float) -> FaultInjection:
        with self._lock:
            fi = FaultInjection(FaultType.DELAYED_ACK, node_id, time.time(), {"delay_sec": delay_sec})
            self._faults.append(fi); self._delayed_acks[node_id] = time.time() + delay_sec; return fi

    def inject_duplicate_event(self, event_id: str) -> FaultInjection:
        with self._lock:
            fi = FaultInjection(FaultType.DUPLICATE_REPLAY, "ALL", time.time(), {"event_id": event_id})
            self._faults.append(fi); self._duplicate_events[event_id].append(time.time()); return fi

    def is_byzantine(self, node_id: str) -> bool:
        return node_id in self._byzantine_nodes

    def are_nodes_partitioned(self, node_a: str, node_b: str) -> bool:
        for pa in self._partitions:
            for pb in self._partitions:
                if node_a in pa and node_b in pb and pa != pb: return True
        return False

    def is_ack_delayed(self, node_id: str) -> bool:
        return node_id in self._delayed_acks and time.time() < self._delayed_acks[node_id]

    def get_corrupted_term(self, node_id: str) -> Optional[int]:
        return self._corrupted_leaders.get(node_id)

    def is_excluded_from_quorum(self, node_ids: Set[str]) -> bool:
        return bool(self._byzantine_nodes & node_ids)

    def isolate_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id in self._byzantine_nodes:
                self._byzantine_nodes.discard(node_id); return True
            return False

    def get_fault_count(self) -> int: return len(self._faults)
    def get_byzantine_nodes(self) -> Set[str]: return set(self._byzantine_nodes)

    def stats(self) -> dict:
        return {"total_faults": len(self._faults),
                "byzantine_nodes": list(self._byzantine_nodes),
                "active_partitions": len(self._partitions) // 2,
                "delayed_acks": {n: t for n, t in self._delayed_acks.items() if time.time() < t},
                "corrupted_leaders": self._corrupted_leaders}
