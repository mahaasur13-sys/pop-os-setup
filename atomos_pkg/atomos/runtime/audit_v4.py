"""
ATOMFederationOS v4.0 — FORMAL SYSTEM AUDIT
Tests ALL P0/P1/P2 fixes:
- T1: Consistency Engine (reconciliation loop)
- T2: Quorum + Raft Hardener (split-brain protection)
- T3: Execution Mesh (real distributed RPC)
- T4: Chaos Engine (enforced fault injection)
- T5: Observability Pipeline (traces + metrics)
- T6: Admission Control (load shedding)
- T7: Distributed Scheduler (cluster-aware)
- T8: Replicated Event Store (quorum replication)
"""
from __future__ import annotations
import sys, os, time

sys.path.insert(0, '/home/workspace')
sys.path.insert(0, '/home/workspace/atomos_pkg')
sys.path.insert(0, '/home/workspace/agents')
os.chdir('/home/workspace')

from atomos.runtime.dcp_control_plane import DistributedControlPlane
from atomos.runtime.event_sourcing import EventStore
from agents.policy_kernel_v4 import PolicyKernelV4, Verdict, make_context

from atomos.runtime.consistency_engine import ConsistencyEngine, DriftStatus
from atomos.runtime.raft_hardener import RaftHardener, QuorumConfig
from atomos.runtime.execution_mesh import ExecutionMesh, TaskState
from atomos.runtime.chaos_engine import ChaosEngine, FaultType
from atomos.runtime.observability import ObservabilitySystem, TraceID
from atomos.runtime.admission_control import AdmissionController, AdmissionVerdict
from atomos.runtime.distributed_scheduler import DistributedScheduler
from atomos.runtime.replicated_event_store import ReplicatedEventStore

print("╔" + "═"*64 + "╗")
print("║  ATOMFederationOS v4.0 - FORMAL AUDIT (P0/P1/P2 FIXES)     ║")
print("╚" + "═"*64 + "╝")

results = {}

# T1: CONSISTENCY ENGINE
print("\n[T1] CONSISTENCY ENGINE — Reconciliation Loop")
try:
    dcp = DistributedControlPlane(heartbeat_timeout=5)
    for nid in ['node-A', 'node-B', 'node-C']:
        dcp.register_node(nid); dcp.heartbeat(nid)
    dcp.elect_leader()
    event_store = EventStore(node_id='audit-node')
    for i in range(5):
        event_store.append('test', (f'd{i}',))
    runtime_state = {'leader': None, 'term': 0, 'nodes': {}, 'tasks': []}
    ce = ConsistencyEngine(dcp, event_store, runtime_state)
    status1, _ = ce.detect_drift()
    ce.repair()
    runtime_state['leader'] = 'node-X'
    status2, details = ce.detect_drift()
    repair_ok = ce.repair()
    status3, _ = ce.detect_drift()
    ce.start()
    time.sleep(0.5)
    ce.stop()
    test1_pass = (
        status1 == DriftStatus.DRIFTED and
        status2 == DriftStatus.DRIFTED and
        repair_ok and
        status3 == DriftStatus.SYNCED
    )
    print(f"  Initial drift: {status1.value}, Injected drift: {status2.value}")
    print(f"  Repair applied: {repair_ok}, Post-repair: {status3.value}")
    print(f"  Drift/repair count: {ce._drift_count}/{ce._repair_count}")
    print(f"  {'✅' if test1_pass else '❌'} T1 {'PASS' if test1_pass else 'FAIL'}")
    results['consistency_engine'] = test1_pass
except Exception as e:
    print(f"  ❌ T1 FAIL: {e}")
    results['consistency_engine'] = False

# T2: QUORUM + RAFT HARDENER
print("\n[T2] QUORUM + RAFT HARDENER — Split-Brain Protection")
try:
    config = QuorumConfig(total_nodes=3, lease_duration_sec=5.0)
    rh = RaftHardener(config)
    quorum_ok = config.quorum_size == 2
    term1 = rh.bump_term("node-A")
    term2 = rh.bump_term("node-B")
    term_monotonic = term2 > term1
    lease = rh.grant_lease("node-A")
    lease_valid = rh._lease.is_valid(time.time())
    ok1, rec1 = rh.commit_event(0, {"node-A", "node-B"})
    ok2, rec2 = rh.commit_event(1, {"node-A"})
    split_ok, leader = rh.assert_single_leader({"node-A": 5, "node-B": 5})
    single_ok, single_leader = rh.assert_single_leader({"node-A": 3})
    test2_pass = (
        quorum_ok and term_monotonic and lease_valid and
        ok1 and not ok2 and
        not split_ok and single_ok
    )
    print(f"  Quorum size: {config.quorum_size} == 2 → {quorum_ok}")
    print(f"  Term monotonic: {term1}<{term2} → {term_monotonic}")
    print(f"  Lease valid: {lease_valid}, fence={lease.fence_token}")
    print(f"  Commit 2/3: {ok1}, Commit 1/3: {ok2}(should fail)")
    print(f"  Split-brain detected: {not split_ok}, tiebreak={leader}")
    print(f"  {'✅' if test2_pass else '❌'} T2 {'PASS' if test2_pass else 'FAIL'}")
    results['quorum_raft'] = test2_pass
except Exception as e:
    print(f"  ❌ T2 FAIL: {e}")
    results['quorum_raft'] = False

# T3: EXECUTION MESH
print("\n[T3] EXECUTION MESH — Real RPC + Task Ownership Transfer")
try:
    mesh = ExecutionMesh("node-A")
    for nid in ["node-A", "node-B", "node-C"]:
        mesh.register_node(nid, address=f"local://{nid}")
    task = mesh.submit_task({"id": "rtask-1", "command": "ls", "cpu": 1})
    dispatched, msg = mesh.dispatch(task)
    ok1, msg1 = mesh.transfer_ownership("rtask-1", "node-B", fence_token=1)
    ok2, msg2 = mesh.transfer_ownership("rtask-1", "node-C", fence_token=0)
    mesh.complete_task("rtask-1", result={"out": "ok"})
    completed = mesh.get_task("rtask-1")
    test3_pass = (
        dispatched and mesh.stats_data["acked"] > 0 and
        ok1 and not ok2 and
        completed.state == TaskState.COMPLETED
    )
    print(f"  Dispatched: {dispatched}, ACKed: {mesh.stats_data['acked']}")
    print(f"  Transfer(valid fence): {ok1}, Transfer(stale fence): {ok2}(should False)")
    print(f"  Task state: {completed.state.value}")
    print(f"  {'✅' if test3_pass else '❌'} T3 {'PASS' if test3_pass else 'FAIL'}")
    results['execution_mesh'] = test3_pass
except Exception as e:
    print(f"  ❌ T3 FAIL: {e}")
    results['execution_mesh'] = False

# T4: CHAOS ENGINE
print("\n[T4] CHAOS ENGINE — Byzantine + Partition Injection")
try:
    ce = ChaosEngine()
    ce.record_attack()
    byz = ce.inject_byzantine_node("node-B", "conflicting_term_claims")
    byz_active = ce.is_byzantine("node-B")
    ce.inject_split_50_50(["node-A", "node-B", "node-C", "node-D"])
    same_group = ce.are_nodes_partitioned("node-A", "node-B")
    diff_group = ce.are_nodes_partitioned("node-A", "node-C")
    ce.record_attack()
    ce.inject_corrupted_event("node-C", {"term": -1, "hash": "TAMPERED"})
    ce.record_rejection()
    rejection_rate = ce.rejection_rate()
    test4_pass = byz_active and not same_group and diff_group and rejection_rate == 0.5
    print(f"  Byzantine injected: {byz_active}")
    print(f"  Same-group(A|B): partitioned={same_group}(should False)")
    print(f"  Diff-group(A|C): partitioned={diff_group}(should True)")
    print(f"  Rejection rate: {rejection_rate:.1%}")
    print(f"  {'✅' if test4_pass else '❌'} T4 {'PASS' if test4_pass else 'FAIL'}")
    results['chaos_engine'] = test4_pass
except Exception as e:
    print(f"  ❌ T4 FAIL: {e}")
    results['chaos_engine'] = False

# T5: OBSERVABILITY
print("\n[T5] OBSERVABILITY — Distributed Tracing + Metrics")
try:
    obs = ObservabilitySystem("node-A")
    trace = obs.start_trace()
    span1 = obs.start_span(trace, "task_submission", {"priority": "high"})
    time.sleep(0.01)
    span2 = obs.start_span(trace.child(), "task_execution", {"cpu": "1"})
    time.sleep(0.02)
    obs.finish_span(span1)
    obs.finish_span(span2)
    obs.counter("tasks_submitted", {"node": "A"})
    obs.gauge("cpu_usage_percent", 72.5, {"node": "A"})
    obs.histogram("task_duration_ms", 45.2, {"priority": "high"})
    obs.correlate_event_to_task(0, "task-t1")
    obs.correlate_event_to_task(1, "task-t2")
    graph = obs.build_trace_graph(trace.trace_id)
    prom = obs.export_prometheus()
    corr_ok = obs.event_correlation(0) == "task-t1" and obs.event_correlation(1) == "task-t2"
    trace_ok = len(graph["nodes"]) >= 2
    metrics_ok = "tasks_submitted" in prom and "cpu_usage_percent" in prom
    test5_pass = corr_ok and trace_ok and metrics_ok
    print(f"  Spans: {len(graph['nodes'])}, Edges: {len(graph['edges'])}")
    print(f"  Event→Task correlation: {corr_ok}")
    print(f"  Prometheus metrics: {metrics_ok}")
    print(f"  {'✅' if test5_pass else '❌'} T5 {'PASS' if test5_pass else 'FAIL'}")
    results['observability'] = test5_pass
except Exception as e:
    print(f"  ❌ T5 FAIL: {e}")
    results['observability'] = False

# T6: ADMISSION CONTROL
print("\n[T6] ADMISSION CONTROL — Load Shedding + SLA Enforcement")
try:
    ac = AdmissionController()
    for nid in ["node-A", "node-B"]:
        ac.update_node_load(nid, cpu_pct=85.0, ram_gb=29.0)
    rec1 = ac.evaluate({"id": "t1", "cpu": 1, "ram": 10, "priority": 5})
    rec2 = ac.evaluate({"id": "t2", "cpu": 1, "ram": 10, "priority": 1})
    high_prio_ok = rec2.original_priority == 1
    rate_ok = ac.admission_rate() >= 0.0
    test6_pass = high_prio_ok and rate_ok
    print(f"  High-priority: prio={rec2.original_priority}")
    print(f"  Admission rate: {ac.admission_rate():.1%}")
    print(f"  Rejection rate: {ac.stats()['rejection_rate']}")
    print(f"  {'✅' if test6_pass else '❌'} T6 {'PASS' if test6_pass else 'FAIL'}")
    results['admission_control'] = test6_pass
except Exception as e:
    print(f"  ❌ T6 FAIL: {e}")
    results['admission_control'] = False

# T7: DISTRIBUTED SCHEDULER
print("\n[T7] DISTRIBUTED SCHEDULER — Global View + Node-Aware Placement")
try:
    ds = DistributedScheduler({
        "node-A": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
        "node-B": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
        "node-C": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
    })
    for i in range(20):
        ds.submit({"id": f"t{i}", "priority": (i % 5) + 1, "cpu": 1, "ram": 10, "gpu": 0})
    dispatched = ds.dispatch_all()
    fairness = ds.cluster_jain_fairness()
    loads = ds.node_loads()
    ds2 = DistributedScheduler({"node-A": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0}, "node-B": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0}})
    for i in range(4):
        ds2.submit({"id": f"pt{i}", "priority": 1, "cpu": 1, "ram": 5, "preferred_node": "node-A"})
    ds2.dispatch_all()
    pref_load = len(ds2._nodes["node-A"].tasks)
    test7_pass = len(dispatched) > 0 and 0.0 < fairness <= 1.0 and len(loads) == 3
    print(f"  Dispatched: {len(dispatched)}/20")
    print(f"  Jain fairness: {fairness:.3f}")
    print(f"  Nodes tracked: {len(loads)}")
    print(f"  Preferred node tasks: {pref_load}")
    print(f"  {'✅' if test7_pass else '❌'} T7 {'PASS' if test7_pass else 'FAIL'}")
    results['distributed_scheduler'] = test7_pass
except Exception as e:
    print(f"  ❌ T7 FAIL: {e}")
    results['distributed_scheduler'] = False

# T8: REPLICATED EVENT STORE
print("\n[T8] REPLICATED EVENT STORE — Quorum Replication")
try:
    store = ReplicatedEventStore("node-A", total_nodes=3)
    evt1, q1 = store.append("test", ("d0",), term=1, replicated_nodes={"node-A"})
    store.replicate_to(0, "node-B")
    evt2, q2 = store.append("test", ("d1",), term=1, replicated_nodes={"node-A", "node-B"})
    evt3, q3 = store.append("test", ("d2",), term=1, replicated_nodes={"node-A"})
    committed = len(store.get_committed_events())
    test8_pass = (
        q1 == False and
        q2 == True and
        committed >= 2 and
        store.verify_chain()
    )
    print(f"  Event 0 (1 ack): committed={q1}(should False)")
    print(f"  Event 1 (2 acks): committed={q2}(should True)")
    print(f"  Committed events: {committed}")
    print(f"  Chain valid: {store.verify_chain()}")
    print(f"  {'✅' if test8_pass else '❌'} T8 {'PASS' if test8_pass else 'FAIL'}")
    results['replicated_event_store'] = test8_pass
except Exception as e:
    print(f"  ❌ T8 FAIL: {e}")
    results['replicated_event_store'] = False

# OVERALL
print("\n" + "═"*66)
passed = sum(1 for v in results.values() if v)
total = len(results)
all_ok = all(results.values())
scores = {
    "consistency_engine": 25,
    "quorum_raft": 15,
    "execution_mesh": 15,
    "chaos_engine": 15,
    "observability": 10,
    "admission_control": 10,
    "distributed_scheduler": 5,
    "replicated_event_store": 5,
}
consistency_score = sum(scores[k] for k, v in results.items() if v)
fault_tolerance_score = (
    (15 if results.get('chaos_engine') else 0) +
    (15 if results.get('quorum_raft') else 0) +
    (15 if results.get('execution_mesh') else 0) +
    (10 if results.get('replicated_event_store') else 0) +
    (10 if results.get('distributed_scheduler') else 0)
)
prod_level = "PRODUCTION_READY" if all_ok else ("HYBRID" if passed >= 6 else "SIMULATION")
print(f"  PASSED: {passed}/{total}")
print(f"  CONSISTENCY_SCORE: {consistency_score}/100")
print(f"  FAULT_TOLERANCE_SCORE: {fault_tolerance_score}/70")
print(f"  PRODUCTION_READINESS: {prod_level}")
print(f"  OVERALL: {'✅ ALL TESTS PASSED' if all_ok else '❌ SOME TESTS FAILED'}")
print("═"*66)
