"""v6.8 — Global Coherence Engine.

Four components:
  DriftController       P+threshold hybrid with hysteresis
  TemporalCoherenceSmoother  adaptive W, prevents lattice oscillation
  GlobalObjectiveStabilizer  J(t) = α·stability + β·consistency − γ·control_cost
  SystemCoherenceInvariant   hard gate: FAIL FAST if bounds violated

Backward compatibility: dual-mode J system (v6.8 / legacy).
"""

from coherence.drift_controller import DriftController, DriftSnapshot
from coherence.temporal_smoother import TemporalCoherenceSmoother, SmootherSnapshot
from coherence.objective_stabilizer import GlobalObjectiveStabilizer, StabilizerSnapshot
from coherence.invariant import SystemCoherenceInvariant, CoherenceViolation

__all__ = [
    "DriftController", "DriftSnapshot",
    "TemporalCoherenceSmoother", "SmootherSnapshot",
    "GlobalObjectiveStabilizer", "StabilizerSnapshot",
    "SystemCoherenceInvariant", "CoherenceViolation",
]
