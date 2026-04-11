"""
v6.7 — Meta-Coherence Controller

The master controller that wires v6.7 components into a coherent control layer:

  ModelRealityAligner      → validates self_model vs real cluster
  EigenstateDetector       → finds stable attractors + predicts transitions
  ObjectiveStabilityGovernor → prevents J-gate oscillation
  ComputeBudgetController  → bounds compute overhead

And closes the final loop:
  model ↔ reality ↔ objective ↔ execution

Usage:
  mc = MetaCoherenceController()
  mc.begin_tick()
  decision = mc.tick(...)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from resilience.self_model import SystemState, NodeRole
from resilience.decision_lattice import DecisionLattice, LatticeDecision
from resilience.predictive_controller import PredictiveController, PredictiveTickResult
from resilience.model_reality_aligner import (
    ModelRealityAligner,
    AlignmentSnapshot,
    DriftStatus,
)
from resilience.eigenstate_detector import (
    EigenstateDetector,
    EigenstateSnapshot,
    Eigenstate,
    EigenstateType,
)
from resilience.objective_stability_governor import (
    ObjectiveStabilityGovernor,
    GovernorMode,
    GovernorDecision,
)
from resilience.compute_budget_controller import (
    ComputeBudgetController,
    Subsystem,
    BudgetDecision,
)
from resilience.closed_loop import ClosedLoopResilienceController
from resilience.predictive_controller import PredictiveController
from resilience.optimizer import SystemOptimizer, OptimizationResult


@dataclass
class CoherenceMetrics:
    coherence_score: float           # 0..1, model ↔ reality alignment
    model_version: int
    current_eigenstate_id: Optional[str]
    eigenstate_type: Optional[str]
    J_raw: float
    J_governed: float
    J_allowed: bool
    oscillation_detected: bool
    compute_used_ms: float
    drift_status: str
    eigenstate_transition_pending: bool
    total_coherence_loops: int


@dataclass
class MetaCoherenceSnapshot:
    timestamp: float
    tick_number: int
    metrics: CoherenceMetrics
    alignment: AlignmentSnapshot
    eigenstate: EigenstateSnapshot
    governor_decision: GovernorDecision
    compute: ComputeBudgetSnapshot
    raw_decision: Optional[LatticeDecision]
    final_action: Optional[str]


class MetaCoherenceController:
    """
    Master v6.7 controller.

    Tick flow:
      1. begin_tick() → budget controller starts accounting
      2.感知 → self_model + aligner observe reality
      3. eigenstate detection → find current basin
      4. PredictiveController → forecast 30s stability
      5. SystemOptimizer.compute_J() → evaluate objective
      6. ObjectiveStabilityGovernor → damp oscillation
      7. DecisionLattice → formal arbitration
      8. end_tick() → budget accounting closes

    Closes the final gap:
      model (self_model) ↔ reality (observed cluster state)
                            ↕
                        objective (J)
                            ↕
                       execution (lattice decision)
    """

    def __init__(
        self,
        cluster_nodes: int = 5,
        tick_budget_ms: float = 50.0,
        governor_mode: GovernorMode = GovernorMode.DAMPED,
    ):
        self.aligner = ModelRealityAligner()
        self.eigenstate_detector = EigenstateDetector(n_features=8, learning_window=200)
        self.governor = ObjectiveStabilityGovernor(mode=governor_mode)
        self.compute = ComputeBudgetController(total_budget_ms=tick_budget_ms)

        self._ctrl = ClosedLoopResilienceController(
            node_id="meta-coherence-ctrl",
            peers=[f"node-{i}" for i in range(cluster_nodes)],
        )
        self.predictive = PredictiveController(self._ctrl, forecast_horizon_s=30.0)
        self.optimizer = SystemOptimizer()
        self.lattice = DecisionLattice()

        self._tick_count = 0
        self._state_buffer: list[dict[str, float]] = []
        self._last_snapshot: Optional[MetaCoherenceSnapshot] = None
        self._previous_J = 0.5

    def begin_tick(self) -> None:
        self.compute.begin_tick()
        self._tick_count += 1

    def tick(
        self,
        observed_state: dict,
        predicted_state: dict,
        node_roles: dict[str, NodeRole],
    ) -> MetaCoherenceSnapshot:
        now = time.time()

        # 1. Alignment: self_model vs reality
        self.compute.enter_subsystem(Subsystem.MODEL_ALIGNER)
        t0 = time.monotonic()
        alignment = self.aligner.observe(observed_state, predicted_state)
        elapsed = (time.monotonic() - t0) * 1000.0
        self.compute.exit_subsystem(Subsystem.MODEL_ALIGNER, elapsed)

        # 2. Eigenstate detection
        self.eigenstate_detector.ingest(observed_state)
        self.compute.enter_subsystem(Subsystem.EIGENSTATE_DETECTOR)
        t0 = time.monotonic()
        eigenstate_snap = self.eigenstate_detector.detect_current()
        elapsed = (time.monotonic() - t0) * 1000.0
        self.compute.exit_subsystem(Subsystem.EIGENSTATE_DETECTOR, elapsed)

        # 3. Predictive forecast
        self.compute.enter_subsystem(Subsystem.PREDICTIVE_CONTROLLER)
        adaptive_horizon = self.compute.get_adaptive_horizon(30.0, Subsystem.PREDICTIVE_CONTROLLER)
        self.predictive.forecast_horizon = adaptive_horizon
        t0 = time.monotonic()
        system_state = SystemState(
            node_count_total=len(node_roles),
            node_count_healthy=sum(1 for r in node_roles.values() if r == NodeRole.HEALTHY),
            stability_score=1.0 - alignment.drift_score,
            quorum_health=1.0 - alignment.drift_score,
            leader_count=1,
            node_roles=node_roles,
        )
        forecast = self.predictive.tick()
        elapsed = (time.monotonic() - t0) * 1000.0
        self.compute.exit_subsystem(Subsystem.PREDICTIVE_CONTROLLER, elapsed)

        # 4. J computation via optimizer
        self.compute.enter_subsystem(Subsystem.GOVERNORS)
        t0 = time.monotonic()
        try:
            snap = self._ctrl.get_snapshot()
            J_result: OptimizationResult = self.optimizer.compute_J(snap)
            J_raw = J_result.J
        except Exception:
            J_raw = self._previous_J
        J_governed = J_raw  # initial, may be adjusted by governor
        governor_decision = self.governor.evaluate(J_raw, confidence=0.8)
        elapsed = (time.monotonic() - t0) * 1000.0
        self.compute.exit_subsystem(Subsystem.GOVERNORS, elapsed)
        self._previous_J = J_raw

        # 5. Decision lattice
        self.compute.enter_subsystem(Subsystem.DECISION_LATTICE)
        t0 = time.monotonic()
        full_state = SystemState(
            node_count_total=len(node_roles),
            node_count_healthy=sum(1 for r in node_roles.values() if r == NodeRole.HEALTHY),
            stability_score=1.0 - alignment.drift_score,
            quorum_health=1.0 - alignment.drift_score,
            leader_count=1,
            node_roles=node_roles,
        )
        raw_decision = self.lattice.decide(full_state)
        elapsed = (time.monotonic() - t0) * 1000.0
        prune_happened = self.compute.should_prune(Subsystem.DECISION_LATTICE, raw_decision.branch_count)
        self.compute.exit_subsystem(
            Subsystem.DECISION_LATTICE,
            elapsed,
            nodes_visited=raw_decision.branch_count,
            pruned=prune_happened,
        )

        # 6. Final action gating
        final_allowed = governor_decision.allowed and J_raw > 0.0
        final_action = raw_decision.primary_action.name if final_allowed else "BLOCKED"

        # 7. Coherence score
        coherence = self._compute_coherence(
            alignment.drift_score,
            eigenstate_snap.trajectory_variance,
            governor_decision.oscillation_report.amplitude if governor_decision.oscillation_report else 0.0,
        )

        metrics = CoherenceMetrics(
            coherence_score=coherence,
            model_version=self.aligner._model_version,
            current_eigenstate_id=eigenstate_snap.current_eigenstate.id if eigenstate_snap.current_eigenstate else None,
            eigenstate_type=eigenstate_snap.current_eigenstate.type.value if eigenstate_snap.current_eigenstate else None,
            J_raw=J_raw,
            J_governed=governor_decision.enforced_J,
            J_allowed=governor_decision.allowed,
            oscillation_detected=governor_decision.oscillation_report.detected if governor_decision.oscillation_report else False,
            compute_used_ms=self.compute.snapshot().spent_ms,
            drift_status=alignment.drift_status.value,
            eigenstate_transition_pending=eigenstate_snap.transition_pending is not None,
            total_coherence_loops=self._tick_count,
        )

        snap = MetaCoherenceSnapshot(
            timestamp=now,
            tick_number=self._tick_count,
            metrics=metrics,
            alignment=alignment,
            eigenstate=eigenstate_snap,
            governor_decision=governor_decision,
            compute=self.compute.snapshot(),
            raw_decision=raw_decision,
            final_action=final_action,
        )
        self._last_snapshot = snap
        return snap

    def _compute_coherence(
        self,
        drift_score: float,
        trajectory_variance: float,
        oscillation_amplitude: float,
    ) -> float:
        drift_component = 1.0 - min(drift_score / 0.4, 1.0)
        variance_component = 1.0 - min(trajectory_variance / 0.5, 1.0)
        oscillation_component = 1.0 - min(oscillation_amplitude / 0.3, 1.0)
        return (drift_component * 0.4 + variance_component * 0.3 + oscillation_component * 0.3)

    def end_tick(self) -> BudgetDecision:
        return self.compute.snapshot()

    def force_model_rebuild(self, reason: str = "manual") -> AlignmentSnapshot:
        return self.aligner.force_correction(reason)

    def set_governor_mode(self, mode: GovernorMode) -> None:
        self.governor.set_mode(mode)

    def summary(self) -> dict:
        snap = self._last_snapshot
        return {
            "tick": self._tick_count,
            "coherence_score": snap.metrics.coherence_score if snap else 0.0,
            "drift_status": snap.metrics.drift_status if snap else "none",
            "governor_mode": self.governor.mode.value,
            "compute_utilization_pct": snap.compute.utilization_pct if snap else 0.0,
            "model_version": self.aligner._model_version,
            "eigenstate_count": self.eigenstate_detector.summary()["eigenstate_count"],
            "last_action": snap.final_action if snap else "none",
        }
