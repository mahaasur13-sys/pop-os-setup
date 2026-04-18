"""
ATOMFederationOS v4.1 — PART 5: Integrated Kernel + Tests
"""
from __future__ import annotations
from typing import Dict, List, Optional, Set, Any
import threading, hashlib, time, sys, os

sys.path.insert(0, os.path.dirname(__file__))

# All enums imported from linear_os_kernel — DO NOT redefine
from linear_os_kernel import (
    ConvergenceState,  # single source of truth
    QuorumCommitEngine, AckStatus, AckTracker, ACK_SEMANTICS, AckSemantics
)
from linear_os_kernel_part2 import PartitionSafeLeaderController, FenceToken
from linear_os_kernel_part3 import (
    ConvergenceStateMachine, ReconciliationRecord,
    LinearizableStateMachine, ReadOrigin, ReadIndexEntry,
    ByzantineFaultInjector, FaultType, FaultInjection
)
from linear_os_kernel_part4 import (
    ThrottleLevel, BackpressureConfig, AdmissionThrottler,
    CausalTraceSystem, CausalSpan
)
from linear_os_kernel import GlobalCommitIndex, GlobalEvent, EventCommitState


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATED LINEARIZABLE OS KERNEL
# ═══════════════════════════════════════════════════════════════════════

class LinearizableOSKernel:
    def __init__(self, node_id: str, total_nodes: int, node_ids: List[str]):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.quorum_size = (total_nodes // 2) + 1

        self.gci = GlobalCommitIndex(node_id)
        self.qe  = QuorumCommitEngine(total_nodes, node_ids)
        self.lc  = PartitionSafeLeaderController(node_id, total_nodes)
        self.csm = ConvergenceStateMachine()
        self.lsm = LinearizableStateMachine(self.lc, self.qe)
        self.bfi = ByzantineFaultInjector(total_nodes)
        self.at  = AdmissionThrottler(BackpressureConfig())
        self.ct  = CausalTraceSystem(node_id)

        self._event_log: List[GlobalEvent] = []
        self._lock = threading.Lock()

    def _make_genesis_event(self) -> GlobalEvent:
        """Placeholder genesis event at index 0."""
        return GlobalEvent(
            global_index=0, term=0, leader_id="GENESIS",
            event_type="_genesis", payload=(), timestamp=0.0,
            causality_id="0-0", parent_event_id=None,
            prev_global_index=0, self_hash="GENESIS",
            replicated_on=set(), commit_state=EventCommitState.STABLE,
        )

    def bootstrap_leader(self, term: int) -> tuple[FenceToken, int]:
        self.lc.bump_term(self.node_id)
        self.lc.update_term_if_newer(term)
        fence = self.lc.grant_lease(self.node_id, term)
        self._event_log.append(self._make_genesis_event())
        idx = self.gci.next_index(term, self.node_id)  # claims index 1
        return fence, idx

    def submit_event(self, event_type: str, payload: tuple,
                    parent_causality_id: Optional[str] = None) -> GlobalEvent:
        valid_leader, fence = self.lc.get_valid_leader()
        if valid_leader != self.node_id:
            raise PermissionError(f"Not leader: {valid_leader}")

        term = self.lc.current_term()
        prev_idx = self.gci.get_global_index()
        idx = self.gci.next_index(term, self.node_id)
        ts = time.time()
        prev_hash = self._event_log[-1].self_hash
        raw = f"{self.node_id}{term}{idx}{event_type}{payload}{ts}{prev_hash}"
        self_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]

        evt = GlobalEvent(
            global_index=idx, term=term, leader_id=self.node_id,
            event_type=event_type, payload=payload, timestamp=ts,
            causality_id=f"{idx}-{ts}",
            parent_event_id=parent_causality_id,
            prev_global_index=prev_idx, self_hash=self_hash,
            replicated_on={self.node_id},
            commit_state=EventCommitState.REPLICATING,
        )
        with self._lock:
            self._event_log.append(evt)
        self.qe.create_tracker(idx, term, initial_acks={self.node_id})
        return evt

    def replicate_ack(self, event_index: int, from_node: str) -> bool:
        committed, tracker = self.qe.record_ack(event_index, from_node)
        # Find event by global_index in our log (if not present, ack was recorded anyway)
        for ev in self._event_log:
            if ev.global_index == event_index:
                ev.replicated_on.update(tracker.acks)
                if committed and ev.commit_state != EventCommitState.COMMITTED:
                    ev.commit_state = EventCommitState.COMMITTED
                    self.ct.correlate_event_to_task(event_index, f"evt-{event_index}")
                break
        return committed

    def is_leader_valid(self) -> bool:
        leader, fence = self.lc.get_valid_leader()
        return leader == self.node_id and fence is not None

    def get_current_fence(self) -> tuple[int, int]:
        return self.lc.get_fence_token()

    def linearizable_read(self, key: str) -> tuple[Any, ReadOrigin]:
        return self.lsm.read(key, require_linearizable=True)

    def reconcile(self, dcp_state: dict, runtime_state: dict) -> ReconciliationRecord:
        state, rid = self.csm.detect_divergence(dcp_state, runtime_state, "DCP-Runtime sync")
        if state == ConvergenceState.DIVERGED:
            for s in [ConvergenceState.DETECTED, ConvergenceState.PROPOSED,
                     ConvergenceState.COMMITTED, ConvergenceState.CONVERGED]:
                self.csm.advance(rid, s)
        return self.csm.get_record(rid)

    def stats(self) -> dict:
        return {"node_id": self.node_id, "global_index": self.gci.get_global_index(),
                "quorum_size": self.quorum_size, "leader_ctrl": self.lc.stats(),
                "quorum_committed": len(self.qe._committed),
                "byzantine_nodes": list(self.bfi.get_byzantine_nodes()),
                "throttle_level": self.at.stats(),
                "traces": self.ct.export_prometheus()}


# ═══════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════

def _run_tests():
    print("╔" + "═"*64 + "╗")
    print("║  ATOMFederationOS v4.1 — LINEARIZABLE OS KERNEL AUDIT  ║")
    print("╚" + "═"*64 + "╝")
    results = {}

    # T1: GlobalCommitIndex sequential monotonicity
    gci = GlobalCommitIndex("node-A")
    idxs = [gci.next_index(1, "node-A") for _ in range(5)]
    # After 5 events, update all nodes to index 5 — no gaps remain
    for n in ["node-A", "node-B", "node-C"]:
        gci.update_from_node(n, 5)
    no_gaps = all(gci.update_from_node(n, 5) == 0 for n in ["node-A", "node-B", "node-C"])
    t1 = idxs == [1, 2, 3, 4, 5] and no_gaps
    print(f"[T1] GCI ordering: {idxs} no_gaps={no_gaps} | {'✅ PASS' if t1 else '❌ FAIL'}")

    # T2: QuorumCommitEngine quorum gating (STRICT semantic)
    qe = QuorumCommitEngine(3, ["A","B","C"])
    t = qe.create_tracker(0, 1, initial_acks={"A"})  # 1/3 — PENDING
    # Capture initial state BEFORE any record_ack calls (tracker is mutated in-place)
    initial_pending = qe._trackers[0].status == AckStatus.PENDING
    ok1, _ = qe.record_ack(0, "B")   # 2/3 → quorum reached → ACKED
    ok2, _ = qe.record_ack(0, "C")   # STRICT: tracker already ACKED → rejected (False)
    # STRICT semantic: duplicate ACK on terminal tracker = False
    t2 = initial_pending and ok1 and not ok2
    print(f"[T2] QE: initial_pending={initial_pending} quorum_2of3={ok1} reject_dup={not ok2} | {'✅ PASS' if t2 else '❌ FAIL'}")

    # T3: PartitionSafeLeaderController split-brain
    lc = PartitionSafeLeaderController("node-A", 3)
    lc.bump_term("node-A"); fence = lc.grant_lease("node-A", 1)
    ok1, tok = lc.check_leader_lease("node-A")
    ok2, _ = lc.check_leader_lease("node-B")
    split, leader = lc.is_split_brain({"A":5,"B":5})
    lc.update_term_if_newer(3); lc.bump_term("node-C")
    lc.grant_lease("node-C", 4)
    split2, leader2 = lc.is_split_brain({"A":3,"C":4})
    t3 = ok1 and not ok2 and split and not split2
    print(f"[T3] PSLC: valid={ok1} split={split} | {'✅ PASS' if t3 else '❌ FAIL'}")

    # T4: ConvergenceStateMachine idempotent state transitions
    csm = ConvergenceStateMachine()
    s1, rid = csm.detect_divergence({"a":1},{"a":2},"sync")
    for s in [ConvergenceState.DETECTED, ConvergenceState.PROPOSED,
              ConvergenceState.COMMITTED, ConvergenceState.CONVERGED]:
        csm.advance(rid, s)
    rec = csm.get_record(rid)
    t4 = s1 == ConvergenceState.DIVERGED and rec is not None and \
          rec.state == ConvergenceState.CONVERGED
    print(f"[T4] CSM: {s1.value}→{rec.state.value} | {'✅ PASS' if t4 else '❌ FAIL'}")

    # T5: ByzantineFaultInjector
    bfi = ByzantineFaultInjector(3)
    bfi.inject_byzantine_node("node-B", "corrupt")
    bfi.inject_network_partition({"A"},{"B","C"})
    bfi.inject_corrupted_leader_claim("node-C", 999)
    t5 = bfi.is_byzantine("node-B") and bfi.are_nodes_partitioned("A","B") and \
          bfi.get_corrupted_term("node-C") == 999
    print(f"[T5] BFI: byz={bfi.is_byzantine('node-B')} partition | {'✅ PASS' if t5 else '❌ FAIL'}")

    # T6: AdmissionThrottler backpressure
    at = AdmissionThrottler(BackpressureConfig(queue_depth_threshold=10))
    at.update_system_load(5, 50.0, 16.0)
    ok1, _, _ = at.evaluate_task({"id":"t1","priority":1})
    at.update_system_load(15, 90.0, 30.0)
    ok2, level, _ = at.evaluate_task({"id":"t2","priority":5})
    ok3, _, _ = at.evaluate_task({"id":"t3","priority":10})
    t6 = ok1 and not ok2 and ok3
    print(f"[T6] Throttler: stale={ok1} loaded={not ok2} | {'✅ PASS' if t6 else '❌ FAIL'}")

    # T7: CausalTraceSystem causal linking
    ct = CausalTraceSystem("A")
    tr = ct.start_trace()
    sp1 = ct.start_span(tr, "submit", consensus_term=1, commit_index=1)
    sp2 = ct.start_span(tr, "exec", parent_span_id=sp1, consensus_term=1, commit_index=1)
    ct.finish_span(sp1); ct.finish_span(sp2)
    ct.correlate_event_to_task(1, "task-1")
    g = ct.build_trace_graph(tr)
    finished = len([s for s in ct._spans.values() if s.finished_at])
    t7 = ct.event_correlation(1) == "task-1" and finished >= 2 and len(g["edges"]) >= 1
    print(f"[T7] CausalTrace: corr={ct.event_correlation(1)} edges={len(g['edges'])} | {'✅ PASS' if t7 else '❌ FAIL'}")

    # T8: Integrated LinearizableOSKernel
    k = LinearizableOSKernel("node-A", 3, ["A","B","C"])
    fence, base_idx = k.bootstrap_leader(1)
    t8a = k.is_leader_valid()
    evt1 = k.submit_event("test", ("d0",))
    t8b = evt1.global_index == base_idx + 1
    committed = k.replicate_ack(evt1.global_index, "B")
    t8c = committed  # 2/3 quorum reached
    k.replicate_ack(evt1.global_index, "C")
    t8d = evt1.commit_state == EventCommitState.COMMITTED
    k.lsm.apply("key1", "value1", evt1.global_index)
    val, origin = k.linearizable_read("key1")
    t8e = val == "value1" and origin == ReadOrigin.LEADER
    rec = k.reconcile({"leader":"A"},{"leader":"B"})
    t8f = rec.state == ConvergenceState.CONVERGED
    t8 = t8a and t8b and t8c and t8d and t8e and t8f
    print(f"[T8] Kernel: leader={t8a} idx={t8b} ack={t8c} commit={t8d} read={t8e} | {'✅ PASS' if t8 else '❌ FAIL'}")

    # T9: Fence token monotonicity
    lc2 = PartitionSafeLeaderController("node-A", 3)
    lc2.bump_term("node-A")
    f1 = lc2.grant_lease("node-A", 1)
    lc2.bump_term("node-A")
    f2 = lc2.grant_lease("node-A", 2)
    t9 = f2.token > f1.token and f2.term > f1.term
    print(f"[T9] Fence monotonic: {f1.token}→{f2.token} | {'✅ PASS' if t9 else '❌ FAIL'}")

    # T10: NACK permanently blocks commit
    qe2 = QuorumCommitEngine(3, ["A","B","C"])
    qe2.create_tracker(0, 1)
    qe2.record_ack(0, "B")
    qe2.record_nack(0, "C")
    t10 = not qe2.is_committed(0)
    print(f"[T10] NACK blocks commit: committed={qe2.is_committed(0)} | {'✅ PASS' if t10 else '❌ FAIL'}")

    print("═"*66)
    all_t = [t1,t2,t3,t4,t5,t6,t7,t8,t9,t10]
    passed = sum(all_t)
    w = {'T1':10,'T2':10,'T3':15,'T4':10,'T5':10,'T6':10,'T7':10,'T8':15,'T9':5,'T10':5}
    total_w = sum(w.values())
    score = sum(w[f'T{i+1}'] for i,t in enumerate(all_t) if t)
    prod = 'PRODUCTION_READY' if all(all_t) else ('DEGRADED' if passed>=7 else 'SIMULATION_MODE')
    print(f"  PASSED: {passed}/{len(all_t)}  SCORE:{score}/{total_w}  → {prod}")
    print(f"  {'✅ ALL TESTS PASSED' if all(all_t) else '❌ SOME TESTS FAILED'}")
    print("═"*66)
    return all(all_t)


if __name__ == "__main__":
    ok = _run_tests()
    sys.exit(0 if ok else 1)
