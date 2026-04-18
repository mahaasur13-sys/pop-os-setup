"""
UESL v1 — Test Suite
Validates: DRL-CCL integration, UESL execution, determinism, partition safety,
replay equivalence, Byzantine handling.

Required tests (from spec):
  T1 — DRL distortion consistency (same seed → same loss/delay pattern)
  T2 — CCL deterministic contract (same input → same approve/reject)
  T3 — DRL-CCL divergence (partition → MUST block commit)
  T4 — Replay test (replay log → identical final state hash)
  T5 — Byzantine simulation (corrupted message → rejected before quorum)
  T6 — End-to-end determinism (full pipeline stable across 10 runs)
"""
from __future__ import annotations

import sys as _sys

# ── BOOTSTRAP ──────────────────────────────────────────────────────────────
# PROBLEM: "atomos_pkg/atomos" in sys.path[0] makes Python resolve stdlib
# modules like "enum", "types" as submodules of "atomos" package:
#   → import types → finds atomos_pkg/atomos/uesl/types.py (WRONG!)
# CAUSE: atomos.uesl.__path__ = ['.../atomos/uesl'] → pkg search includes
#         parent's __path__ entries → sys.path[0] gets scanned for submodules.
# FIX: prepend stdlib paths so Python finds the real stdlib modules first.
import os as _os
import importlib as _importlib

_STDLIB_PATHS = [
    p for p in _sys.path
    if "/atomos_pkg" not in p and p != ""
]
# Add atomos_pkg at the END (not beginning) so stdlib takes priority
if "/home/workspace/atomos_pkg" not in _sys.path:
    _sys.path.append("/home/workspace/atomos_pkg")

# Now stdlib imports work correctly
import enum as _stdlib_enum
import types as _stdlib_types
import dataclasses as _stdlib_dc
import abc as _stdlib_abc
import typing as _stdlib_typing

# Remove atomos_pkg from front of sys.path to prevent it shadowing stdlib
if "/home/workspace/atomos_pkg" in _sys.path:
    _sys.path.remove("/home/workspace/atomos_pkg")

# Place atomos_pkg at position 1 (after stdlib)
if "/home/workspace/atomos_pkg" not in _sys.path:
    _sys.path.insert(1, "/home/workspace/atomos_pkg")

# Load ALL submodules in safe dependency order via importlib
_importlib.import_module("atomos.uesl.semtypes")
_importlib.import_module("atomos.drl.message")
_importlib.import_module("atomos.drl.transport")
_importlib.import_module("atomos.drl.failures")
_importlib.import_module("atomos.drl.partition")
_importlib.import_module("atomos.drl.clock")
_importlib.import_module("atomos.drl.gateway")
_importlib.import_module("atomos.runtime.ccl_v1")
_importlib.import_module("atomos.uesl.adapter")
_importlib.import_module("atomos.uesl.statestore")
_importlib.import_module("atomos.uesl.engine")

# Now safe to import symbols
from atomos.uesl.engine import UESLEngine, ExecutionResult
from atomos.uesl.adapter import DRLToCCLAdapter
from atomos.uesl.statestore import UESLState
from atomos.uesl.semtypes import PartitionState, ExecutionContract
from atomos.drl.message import DRLMessage
from atomos.drl.gateway import DRLGateway
from atomos.drl.transport import TransportConfig
from atomos.drl.failures import FailureConfig
from atomos.drl.partition import PartitionModel, PartitionConfig
from atomos.runtime.ccl_v1 import TrackerSnapshot, QuorumContract


# ── Test harness ──────────────────────────────────────────────────────────

def _run_tests():
    print("╔" + "═"*64 + "╗")
    print("║  ATOMFederationOS v4.2 — UESL v1 TEST SUITE  ║")
    print("╚" + "═"*64 + "╝")
    results = []

    # ── T1: DRL distortion consistency ──────────────────────────────────
    def trial_t1(seed: int):
        gw1 = DRLGateway(
            node_id="A", peers=["B"],
            transport_cfg=TransportConfig(base_latency_ms=0, seed=seed),
            failure_cfg=FailureConfig(drop_rate=0.4, seed=seed),
            seed=seed,
        )
        gw2 = DRLGateway(
            node_id="A", peers=["B"],
            transport_cfg=TransportConfig(base_latency_ms=0, seed=seed),
            failure_cfg=FailureConfig(drop_rate=0.4, seed=seed),
            seed=seed,
        )
        drops1, drops2 = 0, 0
        for _ in range(10):
            r1 = gw1.send(sender="A", receiver="B", payload={})
            gw1.deliver()
            if r1 is None:
                drops1 += 1
            r2 = gw2.send(sender="A", receiver="B", payload={})
            gw2.deliver()
            if r2 is None:
                drops2 += 1
        return drops1, drops2

    (d1a, d1b), (d2a, d2b) = trial_t1(777), trial_t1(777)
    t1 = d1a == d2a and d1b == d2b
    results.append(("UESL-T1.DRL_DISTORTION_CONSISTENCY", t1))

    # ── T2: CCL deterministic contract ──────────────────────────────────────
    snap = TrackerSnapshot("PENDING", frozenset(), frozenset({"A", "B", "C"}), 3)
    d_a1 = QuorumContract.validate_ack(snap, "A")
    d_a2 = QuorumContract.validate_ack(snap, "A")
    t2 = d_a1.ok == d_a2.ok and d_a1.semantic == d_a2.semantic
    results.append(("UESL-T2.CCL_DETERMINISTIC_CONTRACT", t2))

    # ── T3: DRL-CCL divergence — partition → MUST block commit ─────────────
    pm_partition = PartitionModel(PartitionConfig(enabled=True, seed=888))
    pm_partition.apply_partition({"A"}, {"B", "C"})
    gw_partition = DRLGateway(
        node_id="A", peers=["B", "C"],
        transport_cfg=TransportConfig(base_latency_ms=0, seed=888),
        partition_cfg=PartitionConfig(
            enabled=True, seed=888,
            partition_groups=[{"A"}, {"B", "C"}],
        ),
        seed=888,
    )
    adapter_partition = DRLToCCLAdapter(
        node_id="A", peers=["A", "B", "C"],
        quorum_size=2,
        partition_model=pm_partition,
    )
    state_partition = UESLState(node_id="A", quorum_size=2, seed=888)
    engine_partition = UESLEngine(gw_partition, adapter_partition, state_partition)

    msg_id_ab = gw_partition.send(sender="A", receiver="B", payload={"term": 1})
    if msg_id_ab is None:
        t3 = True  # blocked at DRL partition level ✅
    else:
        for msg in gw_partition.deliver():
            _, contract, _ = engine_partition.execute(msg)
            t3 = (
                contract.partition_state == PartitionState.PARTITIONED
                and contract.ccl_approved is False
            )
    results.append(("UESL-T3.PARTITION_BLOCKS_COMMIT", t3))

    # ── T4: Replay test — replay log produces identical state hash ─────────
    state_t4 = UESLState(node_id="A", quorum_size=2, seed=999)
    gw_t4 = DRLGateway(
        node_id="A", peers=["B"],
        transport_cfg=TransportConfig(base_latency_ms=0, seed=999),
        seed=999,
    )
    adapter_t4 = DRLToCCLAdapter(node_id="A", peers=["A", "B"], quorum_size=2)
    engine_t4 = UESLEngine(gw_t4, adapter_t4, state_t4)

    gw_t4.send(sender="A", receiver="B", payload={"term": 1, "type": "vote"})
    for msg in gw_t4.deliver():
        engine_t4.execute(msg)
    live_snap = state_t4.current_snapshot()

    event_log = state_t4.event_log()
    replay_snap = engine_t4.replay(event_log)

    t4 = engine_t4.verify_replay_equivalence(live_snap, replay_snap)
    results.append(("UESL-T4.REPLAY_STATE_HASH_MATCH", t4))

    # ── T5: Byzantine simulation — corrupted message rejected before quorum ─
    gw_t5 = DRLGateway(
        node_id="A", peers=["B"],
        transport_cfg=TransportConfig(base_latency_ms=0, seed=555),
        failure_cfg=FailureConfig(drop_rate=0.0, corrupt_rate=1.0, seed=555),
        seed=555,
    )
    adapter_t5 = DRLToCCLAdapter(node_id="A", peers=["A", "B"], quorum_size=1)
    state_t5 = UESLState(node_id="A", quorum_size=1, seed=555)
    engine_t5 = UESLEngine(gw_t5, adapter_t5, state_t5)

    gw_t5.send(sender="A", receiver="B", payload={"term": 1})
    for msg in gw_t5.deliver():
        result, _, _ = engine_t5.execute(msg, is_corrupted=True)
        t5 = result == ExecutionResult.REJECTED_BYZANTINE
    results.append(("UESL-T5.BYZANTINE_REJECTED", t5))

    # ── T6: End-to-end determinism — stable across 10 runs ──────────────────
    def full_pipeline_run(seed: int) -> str:
        gw = DRLGateway(
            node_id="A", peers=["B"],
            transport_cfg=TransportConfig(base_latency_ms=0, seed=seed),
            failure_cfg=FailureConfig(drop_rate=0.2, seed=seed),
            seed=seed,
        )
        adapter = DRLToCCLAdapter(node_id="A", peers=["A", "B"], quorum_size=1)
        state = UESLState(node_id="A", quorum_size=1, seed=seed)
        engine = UESLEngine(gw, adapter, state)

        gw.send(sender="A", receiver="B", payload={"term": 1})
        for msg in gw.deliver():
            engine.execute(msg)
        return state.current_snapshot().hash

    hashes = [full_pipeline_run(i) for i in range(10)]
    # T6: determinism check — runs with DIFFERENT seeds produce different
    # hashes (correct, failure patterns differ). T6 FAILS here because the
    # hash does NOT include failure_cfg → structural hash is stable even
    # with different failure outcomes (which is fine), BUT different seeds
    # change the DRL delivery set → different tracker states → different hash.
    # FIX: use SAME seed (seed=7) for all 10 runs to prove intra-seed stability.
    hashes_same_seed = [full_pipeline_run(7) for _ in range(10)]
    t6 = len(set(hashes_same_seed)) == 1
    results.append(("UESL-T6.END_TO_END_DETERMINISM", t6))

    # ── T7: I1 — deterministic execution ────────────────────────────────
    def i1_check(seed: int):
        gw = DRLGateway(node_id="A", peers=["B"], seed=seed)
        adapter = DRLToCCLAdapter(node_id="A", peers=["A", "B"], quorum_size=1)
        state = UESLState(node_id="A", quorum_size=1, seed=seed)
        engine = UESLEngine(gw, adapter, state)
        gw.send(sender="A", receiver="B", payload={"term": 1})
        for msg in gw.deliver():
            result, _, _ = engine.execute(msg)
        return result

    r1a, r1b = i1_check(123), i1_check(123)
    t7 = r1a == r1b
    results.append(("UESL-T7.I1_DETERMINISTIC_EXECUTION", t7))

    # ── T8: I3 — partition safety ─────────────────────────────────────────
    contract_partitioned = ExecutionContract(
        msg_id="test",
        sender="A",
        receiver="B",
        term=1,
        quorum_required=2,
        pending_nodes=frozenset({"B"}),
        partition_state=PartitionState.PARTITIONED,
        clock_vector=(("A", 1), ("B", 1)),
        drl_dropped=False,
        drl_delayed=False,
        drl_duplicated=False,
        drl_corrupted=False,
        drl_reordered=False,
        ccl_approved=True,
        ccl_reject_reason="",
        causal_index=0,
    )
    ok_i3, reason_i3 = contract_partitioned.safety_check()
    t8 = not ok_i3  # I3 violation detected ✅
    results.append(("UESL-T8.I3_PARTITION_SAFETY", t8))

    # ── Print results ────────────────────────────────────────────────────
    for name, ok in results:
        print(f"  [{name}] {'✅ PASS' if ok else '❌ FAIL'}")
    print("─"*66)
    passed = sum(1 for _, o in results if o)
    print(f"  PASSED: {passed}/{len(results)}")
    print("═"*66)
    return all(ok for _, ok in results)


if __name__ == "__main__":
    _sys.exit(0 if _run_tests() else 1)
