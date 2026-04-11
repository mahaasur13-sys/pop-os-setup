"""
ChaosScenarios — pre-built Jepsen-style fault scenarios.

Named scenarios that inject coordinated faults across layers
to test specific failure modes (split-brain, quorum loss, etc.).

Usage
-----
    from chaos.scenarios import ChaosScenarios

    ChaosScenarios.split_brain(adapter)
    ChaosScenarios.quorum_loss(adapter)
    ChaosScenarios.temporal_drift(adapter)
"""

from __future__ import annotations

from chaos.harness import FAULT_TYPE, LayerFaultAdapter


class ChaosScenarios:
    """
    Pre-built fault scenarios aligned with Jepsen's fault model:
    https://jepsen.io/faults

    Each scenario targets a specific failure mode and is designed
    to expose invariants violations if the system is not resilient.
    """

    # ── Split-brain scenarios ────────────────────────────────────────────────

    @staticmethod
    def split_brain_50_50(adapter: LayerFaultAdapter) -> None:
        """
        Split the cluster into two equal partitions.
        Tests: leader uniqueness, quorum safety, split-brain detection.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.PARTITION)

    @staticmethod
    def split_brain_asymmetric(adapter: LayerFaultAdapter) -> None:
        """
        Asymmetric split: majority vs minority partition.
        Tests: quorum violation detection in minority partition.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("ccl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.PARTITION)

    @staticmethod
    def heal_partition(adapter: LayerFaultAdapter) -> None:
        """
        Heal an active partition and verify convergence.
        Tests: recovery, monotonic commit index, state reconciliation.
        """
        adapter.inject("drl", FAULT_TYPE.RECOVER)
        adapter.inject("f2", FAULT_TYPE.RECOVER)

    # ── Message loss scenarios ───────────────────────────────────────────────

    @staticmethod
    def message_loss_low(adapter: LayerFaultAdapter) -> None:
        """
        Inject 10-20% message loss.
        Tests: basic retry / ACK timeout handling.
        """
        adapter.inject("drl", FAULT_TYPE.DROP, loss_rate=0.15)

    @staticmethod
    def message_loss_high(adapter: LayerFaultAdapter) -> None:
        """
        Inject 30-50% message loss.
        Tests: quorum maintenance under severe loss.
        """
        adapter.inject("f2", FAULT_TYPE.DROP, loss_rate=0.4)

    @staticmethod
    def message_loss_cascade(adapter: LayerFaultAdapter) -> None:
        """
        Multi-layer message loss across DRL + F2.
        Tests: consensus resilience under coordinated loss.
        """
        adapter.inject("drl", FAULT_TYPE.DROP, loss_rate=0.3)
        adapter.inject("f2", FAULT_TYPE.DROP, loss_rate=0.3)

    # ── Latency / delay scenarios ────────────────────────────────────────────

    @staticmethod
    def latency_spike(adapter: LayerFaultAdapter) -> None:
        """
        Inject moderate latency spike (50-200ms).
        Tests: timeout handling, leader heartbeat.
        """
        adapter.inject("drl", FAULT_TYPE.DELAY, lo=50, hi=200)

    @staticmethod
    def latency_severe(adapter: LayerFaultAdapter) -> None:
        """
        Inject severe latency (200-500ms).
        Tests: quorum timeout, leader re-election.
        """
        adapter.inject("drl", FAULT_TYPE.DELAY, lo=200, hi=500)
        adapter.inject("ccl", FAULT_TYPE.DELAY, lo=200, hi=500)

    @staticmethod
    def latency_partition_combo(adapter: LayerFaultAdapter) -> None:
        """
        Combined latency + partition attack.
        Tests: split-brain detection under latency.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("drl", FAULT_TYPE.DELAY, lo=100, hi=400)

    # ── Duplicate message scenarios ─────────────────────────────────────────

    @staticmethod
    def duplicate_acks_low(adapter: LayerFaultAdapter) -> None:
        """
        Inject low-rate duplicate ACKs (10-20%).
        Tests: duplicate detection, idempotency.
        """
        adapter.inject("f2", FAULT_TYPE.DUPLICATE, dup_rate=0.15)

    @staticmethod
    def duplicate_acks_high(adapter: LayerFaultAdapter) -> None:
        """
        Inject high-rate duplicate ACKs (40-60%).
        Tests: Byzantine signal detection.
        """
        adapter.inject("f2", FAULT_TYPE.DUPLICATE, dup_rate=0.5)

    # ── Byzantine / corruption scenarios ────────────────────────────────────

    @staticmethod
    def data_corruption(adapter: LayerFaultAdapter) -> None:
        """
        Inject data corruption into DRL state.
        Tests: checksum validation, state integrity invariants.
        """
        adapter.inject("drl", FAULT_TYPE.CORRUPT)

    @staticmethod
    def byzantine_equivocation(adapter: LayerFaultAdapter) -> None:
        """
        Inject Byzantine behavior (equivocation) in F2 layer.
        Tests: leadership uniqueness, no equivocation invariants.
        """
        adapter.inject("f2", FAULT_TYPE.BYZANTINE)

    @staticmethod
    def byzantine_fork(adapter: LayerFaultAdapter) -> None:
        """
        Simulate a fork attack (conflicting writes to different nodes).
        Tests: DESC append-only, sequence integrity invariants.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.DUPLICATE, dup_rate=0.4)

    # ── Temporal scenarios ─────────────────────────────────────────────────

    @staticmethod
    def clock_skew_moderate(adapter: LayerFaultAdapter) -> None:
        """
        Inject moderate clock skew (50-100ms).
        Tests: temporal drift detection threshold.
        """
        adapter.inject("drl", FAULT_TYPE.CLOCK_SKEW, skew_ms=75.0)

    @staticmethod
    def clock_skew_severe(adapter: LayerFaultAdapter) -> None:
        """
        Inject severe clock skew (>150ms).
        Tests: TEMPORAL_DRIFT invariant violation.
        """
        adapter.inject("drl", FAULT_TYPE.CLOCK_SKEW, skew_ms=200.0)

    # ── Quorum scenarios ────────────────────────────────────────────────────

    @staticmethod
    def quorum_degradation(adapter: LayerFaultAdapter) -> None:
        """
        Degrade quorum by combining partition + message loss.
        Tests: QUORUM_VIOLATION detection.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.DROP, loss_rate=0.4)

    @staticmethod
    def quorum_loss_complete(adapter: LayerFaultAdapter) -> None:
        """
        Complete quorum loss: partition all nodes.
        Tests: system halts correctly, no unsafe commits.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("ccl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.PARTITION)

    # ── Recovery scenarios ─────────────────────────────────────────────────

    @staticmethod
    def partition_and_recover(adapter: LayerFaultAdapter) -> None:
        """
        Split then heal. Tests post-partition recovery and convergence.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("ccl", FAULT_TYPE.PARTITION)
        adapter.inject("drl", FAULT_TYPE.RECOVER)
        adapter.inject("ccl", FAULT_TYPE.RECOVER)

    @staticmethod
    def rapid_partition_heal_cycle(adapter: LayerFaultAdapter, cycles: int = 3) -> None:
        """
        Rapid cycle: partition → heal → partition → heal.
        Tests: state machine idempotency and recovery speed.
        """
        for _ in range(cycles):
            adapter.inject("drl", FAULT_TYPE.PARTITION)
            adapter.inject("f2", FAULT_TYPE.PARTITION)
            adapter.inject("drl", FAULT_TYPE.RECOVER)
            adapter.inject("f2", FAULT_TYPE.RECOVER)

    # ── Composite attack scenarios ─────────────────────────────────────────

    @staticmethod
    def composite_byzantine_partition(adapter: LayerFaultAdapter) -> None:
        """
        Combined Byzantine + partition attack.
        Tests: SBS invariants under simultaneous fault modes.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.BYZANTINE)
        adapter.inject("drl", FAULT_TYPE.DELAY, lo=100, hi=300)

    @staticmethod
    def composite_loss_and_skew(adapter: LayerFaultAdapter) -> None:
        """
        Combined message loss + clock skew.
        Tests: consensus under temporal and network stress.
        """
        adapter.inject("drl", FAULT_TYPE.DROP, loss_rate=0.3)
        adapter.inject("drl", FAULT_TYPE.CLOCK_SKEW, skew_ms=150.0)

    @staticmethod
    def jepsen_register(adapter: LayerFaultAdapter) -> None:
        """
        Jepsen's classic register test: concurrent writes under network faults.
        Tests: linearizability, serializability of commits.
        """
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        adapter.inject("f2", FAULT_TYPE.DUPLICATE, dup_rate=0.3)
        adapter.inject("ccl", FAULT_TYPE.DELAY, lo=50, hi=200)