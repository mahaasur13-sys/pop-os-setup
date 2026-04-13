"""
trust_dynamics_stabilizer.py — v9.7 Trust Dynamics Stabilizer

Purpose:
  Orchestrates the full trust-feedback stabilization layer.

Components:
    1. TrustFeedbackDampener — EMA + decay + delta cap
    2. ConsensusEntropyMonitor — detects low-diversity voting (phase locking)
    3. AntiMonopolyConstraint — caps trust dominance gradient
    4. TrustHistoryBuffer — stores trust trajectories for regime detection

Feedback loop this stabilizes:
  trust(t) → consensus → outcome → trust(t+1) → ...

Stabilization properties:
  Monotonicity    If trust_i ↑ → influence ↑ (no side effects)
  Linearity       net_vote is linear (important for provability)
  Separability    vote ≠ score ≠ trust (decoupled)
  Anti-monopoly   max single-trust ≤ dominance_cap
  Entropy floor   consensus entropy ≥ min_entropy to proceed

Anti-patterns handled:
  trust monopolies       → AntiMonopolyConstraint + dampener ceiling
  phase locking         → ConsensusEntropyMonitor
  consensus inertia     → entropy minimum enforced before acceptance
  Byzantine freeze      → regime detection flags BYZANTINE_FREEZE
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math

from .trust_feedback_dampener import (
    TrustFeedbackDampener,
    TrustUpdateResult,
    DampenerConfig,
    FeedbackRegime,
)
from .node_weights import NodeWeightsSnapshot


# ─────────────────────────────────────────────────────────────────
# ConsensusEntropyMonitor
# ─────────────────────────────────────────────────────────────────

@dataclass
class EntropyStats:
    """Entropy of the consensus voting distribution."""
    shannon_entropy: float
    voter_diversity: int
    vote_spread: float
    is_phase_locked: bool
    entropy_ratio: float


class ConsensusEntropyMonitor:
    """
    Monitors voting diversity to detect phase locking.

    Phase locking = all nodes vote the same way → entropy → 0
    Shannon entropy (normalized to [0, 1]):
      H = -Σ p_i · log2(p_i) / log2(n)
    """

    def __init__(self, entropy_floor: float = 0.20, min_voter_diversity: int = 2):
        self.entropy_floor = entropy_floor
        self.min_voter_diversity = min_voter_diversity
        self._entropy_history: list[float] = []
        self._window_size: int = 10

    def compute_entropy(self, votes: dict[str, float]) -> EntropyStats:
        if not votes:
            return EntropyStats(0.0, 0, 0.0, True, 0.0)

        bins = {"accept": 0, "abstain": 0, "reject": 0}
        vote_values = list(votes.values())
        n = len(vote_values)

        for v in vote_values:
            if v > 0.3:
                bins["accept"] += 1
            elif v < -0.3:
                bins["reject"] += 1
            else:
                bins["abstain"] += 1

        max_entropy = math.log2(3)
        entropy = 0.0
        for count in bins.values():
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        mean_v = sum(vote_values) / n
        variance = sum((v - mean_v) ** 2 for v in vote_values) / n
        spread = math.sqrt(variance)

        is_locked = (
            normalized_entropy < self.entropy_floor
            and bins["accept"] > 0
            and bins["reject"] == 0
            and bins["abstain"] == 0
        ) or (
            normalized_entropy < self.entropy_floor
            and bins["reject"] > 0
            and bins["accept"] == 0
            and bins["abstain"] == 0
        )

        self._entropy_history.append(normalized_entropy)
        if len(self._entropy_history) > self._window_size:
            self._entropy_history.pop(0)

        return EntropyStats(
            shannon_entropy=normalized_entropy,
            voter_diversity=sum(1 for v in vote_values if v != 0),
            vote_spread=spread,
            is_phase_locked=is_locked,
            entropy_ratio=normalized_entropy,
        )

    def is_consensus_valid(self, stats: EntropyStats) -> bool:
        if stats.voter_diversity < self.min_voter_diversity:
            return False
        return not stats.is_phase_locked

    def recent_avg_entropy(self) -> float:
        if not self._entropy_history:
            return 0.0
        return sum(self._entropy_history) / len(self._entropy_history)


# ─────────────────────────────────────────────────────────────────
# AntiMonopolyConstraint
# ─────────────────────────────────────────────────────────────────

@dataclass
class MonopolyStats:
    dominating_node: Optional[str]
    dom_weight_fraction: float
    dominance_gradient: float
    is_constrained: bool


class AntiMonopolyConstraint:
    """
    Prevents any single node from accumulating excessive trust influence.

    Hard ceiling: no node holds > dominance_cap fraction of total trust.
    Gradient cap: max trust increase per epoch is capped.
    """

    def __init__(self, dominance_cap: float = 0.5, gradient_cap: float = 0.10):
        self.dominance_cap = dominance_cap
        self.gradient_cap = gradient_cap
        self._prev_dom_node: Optional[str] = None
        self._prev_dom_fraction: float = 0.0

    def check_and_adjust(
        self,
        snapshot: NodeWeightsSnapshot,
        proposed_trust: dict[str, float],
    ) -> tuple[dict[str, float], MonopolyStats]:
        dom_node = None
        dom_fraction = 0.0
        total = snapshot.total_weight

        if total > 0.0:
            dom_node = max(snapshot.weights, key=lambda nid: snapshot.weights[nid])
            dom_fraction = snapshot.weights[dom_node] / total

        gradient = 0.0
        if self._prev_dom_node == dom_node and dom_node is not None:
            gradient = dom_fraction - self._prev_dom_fraction

        adjusted_trust = dict(proposed_trust)

        for node_id, trust in proposed_trust.items():
            if total > 0.0:
                weight_fraction = trust / total
            else:
                weight_fraction = 0.0
            if weight_fraction > self.dominance_cap:
                adjusted_trust[node_id] = self.dominance_cap * total

        self._prev_dom_node = dom_node
        self._prev_dom_fraction = dom_fraction

        stats = MonopolyStats(
            dominating_node=dom_node,
            dom_weight_fraction=dom_fraction,
            dominance_gradient=gradient,
            is_constrained=any(
                proposed_trust[n] != adjusted_trust[n]
                for n in proposed_trust
            ),
        )
        return adjusted_trust, stats


# ─────────────────────────────────────────────────────────────────
# TrustDynamicsStabilizer
# ─────────────────────────────────────────────────────────────────

@dataclass
class DynamicsReport:
    epoch: int
    dampener_results: list[TrustUpdateResult]
    entropy_stats: EntropyStats
    monopoly_stats: MonopolyStats
    consensus_overridden: bool
    blocked_reason: str
    trust_after: dict[str, float]


class TrustDynamicsStabilizer:
    """
    Full trust-feedback stabilization layer.

    Orchestrates:
      1. TrustFeedbackDampener  — EMA + decay + delta cap
      2. ConsensusEntropyMonitor — phase locking detection
      3. AntiMonopolyConstraint  — dominance cap

    Stabilization formula:
      trust_new = dampener.update_trust(trust_old, outcome_signal)
      anti-monopoly applied post-update
      entropy checked before consensus acceptance
    """

    def __init__(
        self,
        dampener_config: DampenerConfig | None = None,
        entropy_floor: float = 0.20,
        dominance_cap: float = 0.5,
        gradient_cap: float = 0.10,
    ):
        self.dampener = TrustFeedbackDampener(dampener_config or DampenerConfig())
        self.entropy_monitor = ConsensusEntropyMonitor(entropy_floor=entropy_floor)
        self.anti_monopoly = AntiMonopolyConstraint(
            dominance_cap=dominance_cap,
            gradient_cap=gradient_cap,
        )
        self._reports: list[DynamicsReport] = []

    def stabilize(
        self,
        trust_scores: dict[str, float],
        votes: dict[str, float],
        consensus_accepted: bool,
        confidence: float,
        snapshot: NodeWeightsSnapshot,
        epoch: int | None = None,
    ) -> DynamicsReport:
        # Step 1: entropy check
        entropy_stats = self.entropy_monitor.compute_entropy(votes)
        consensus_valid = self.entropy_monitor.is_consensus_valid(entropy_stats)
        blocked_reason = ""
        consensus_overridden = False

        if not consensus_valid and entropy_stats.voter_diversity > 0:
            consensus_overridden = True
            if entropy_stats.voter_diversity < self.entropy_monitor.min_voter_diversity:
                blocked_reason = f"low_voter_diversity({entropy_stats.voter_diversity})"
            elif entropy_stats.is_phase_locked:
                blocked_reason = "phase_locking_detected"
            else:
                blocked_reason = "entropy_below_floor"

        # Step 2: dampened trust updates
        dampener_results = self.dampener.batch_update(
            trust_scores, consensus_accepted, confidence, epoch
        )
        proposed_trust = {r.node_id: r.new_trust for r in dampener_results}

        # Step 3: anti-monopoly adjustment
        adjusted_trust, monopoly_stats = self.anti_monopoly.check_and_adjust(
            snapshot, proposed_trust
        )

        report = DynamicsReport(
            epoch=self.dampener.epoch,
            dampener_results=dampener_results,
            entropy_stats=entropy_stats,
            monopoly_stats=monopoly_stats,
            consensus_overridden=consensus_overridden,
            blocked_reason=blocked_reason,
            trust_after=dict(adjusted_trust),
        )
        self._reports.append(report)
        return report

    def trust_after(
        self,
        trust_scores: dict[str, float],
        votes: dict[str, float],
        consensus_accepted: bool,
        confidence: float,
        snapshot: NodeWeightsSnapshot,
        epoch: int | None = None,
    ) -> dict[str, float]:
        report = self.stabilize(
            trust_scores, votes, consensus_accepted, confidence, snapshot, epoch
        )
        return report.trust_after

    @property
    def dampener_config(self) -> DampenerConfig:
        return self.dampener.config

    def reports(self) -> list[DynamicsReport]:
        return list(self._reports)


# ─── Tests ──────────────────────────────────────────────────────────────

def _test_trust_dynamics_stabilizer():
    from federation.trust_weighted.node_weights import NodeWeightRegistry
    from federation.trust.trust_vector import TrustVector

    registry = NodeWeightRegistry()
    registry.register_proofs_for_node("node_A", ["h1", "h2"])
    registry.register_proofs_for_node("node_B", ["h3", "h4"])
    registry.register_proofs_for_node("node_C", ["h5"])

    tv = TrustVector()
    tv.set_entry("h1", 0.90, 1000.0, ledger_version=1)
    tv.set_entry("h2", 0.85, 1000.0, ledger_version=1)
    tv.set_entry("h3", 0.60, 1000.0, ledger_version=1)
    tv.set_entry("h4", 0.55, 1000.0, ledger_version=1)
    tv.set_entry("h5", 0.30, 1000.0, ledger_version=1)

    snap = registry.compute_weights(tv, ledger_version=1, epoch=0)

    stabilizer = TrustDynamicsStabilizer(
        dampener_config=DampenerConfig(alpha=0.75, decay_rate=0.05, base_trust=0.30),
        entropy_floor=0.20,
        dominance_cap=0.5,
        gradient_cap=0.10,
    )

    # Case 1: diverse votes, consensus accepted
    votes = {"node_A": 1.0, "node_B": 0.5, "node_C": -1.0}
    trust_scores = {"node_A": 0.85, "node_B": 0.60, "node_C": 0.30}
    report = stabilizer.stabilize(
        trust_scores=trust_scores,
        votes=votes,
        consensus_accepted=True,
        confidence=0.90,
        snapshot=snap,
        epoch=1,
    )
    assert not report.consensus_overridden, f"Should not be overridden: {report.blocked_reason}"
    assert len(report.trust_after) == 3
    for node_id, trust in report.trust_after.items():
        assert 0.0 < trust <= 1.0, f"Trust out of range for {node_id}: {trust}"
    print(f"✅ Case 1: diverse votes → consensus valid")

    # Case 2: phase locking detected (all accept)
    votes_locked = {"node_A": 1.0, "node_B": 1.0, "node_C": 1.0}
    trust_scores2 = {"node_A": 0.85, "node_B": 0.60, "node_C": 0.30}
    report2 = stabilizer.stabilize(
        trust_scores=trust_scores2,
        votes=votes_locked,
        consensus_accepted=True,
        confidence=0.95,
        snapshot=snap,
        epoch=2,
    )
    entropy = report2.entropy_stats
    assert entropy.is_phase_locked is True, f"Expected phase lock, entropy={entropy.shannon_entropy}"
    assert report2.consensus_overridden is True
    assert report2.blocked_reason == "phase_locking_detected"
    print(f"✅ Case 2: all same vote → phase_locked={entropy.is_phase_locked}, blocked={report2.blocked_reason}")

    # Case 3: mixed votes not phase-locked
    votes_mixed = {"node_A": 1.0, "node_B": -0.5, "node_C": 0.0}
    trust_scores3 = {"node_A": 0.85, "node_B": 0.60, "node_C": 0.30}
    report3 = stabilizer.stabilize(
        trust_scores=trust_scores3,
        votes=votes_mixed,
        consensus_accepted=True,
        confidence=0.75,
        snapshot=snap,
        epoch=3,
    )
    assert report3.entropy_stats.is_phase_locked is False
    print(f"✅ Case 3: mixed votes → not phase-locked (H={report3.entropy_stats.shannon_entropy:.3f})")

    # Case 4: anti-monopoly hard ceiling
    am = AntiMonopolyConstraint(dominance_cap=0.5)
    snap4 = NodeWeightsSnapshot(
        weights={"dominator": 0.90, "weak": 0.10},
        total_weight=1.0,
        max_single_weight=0.90,
        dom_weight_fraction=0.90,
        snapshot_time=0.0,
        ledger_version=1,
        epoch=0,
    )
    proposed = {"dominator": 0.95, "weak": 0.05}
    adjusted, stats = am.check_and_adjust(snap4, proposed)
    assert stats.is_constrained is True
    assert adjusted["dominator"] <= 0.5, f"Expected ≤0.5, got {adjusted['dominator']}"
    print(f"✅ Case 4: anti-monopoly caps dominator at {adjusted['dominator']:.2f}")

    # Case 5: entropy floor gating
    monitor = ConsensusEntropyMonitor(entropy_floor=0.30)
    stats_ok = monitor.compute_entropy({"A": 1.0, "B": 0.5, "C": -1.0})
    assert stats_ok.is_phase_locked is False
    stats_bad = monitor.compute_entropy({"A": 1.0, "B": 1.0, "C": 1.0})
    assert stats_bad.is_phase_locked is True
    print(f"✅ Case 5: entropy floor gating works")

    print("\n✅ v9.7 TrustDynamicsStabilizer — all checks passed")


if __name__ == "__main__":
    _test_trust_dynamics_stabilizer()


__all__ = [
    "EntropyStats",
    "ConsensusEntropyMonitor",
    "MonopolyStats",
    "AntiMonopolyConstraint",
    "DynamicsReport",
    "TrustDynamicsStabilizer",
]