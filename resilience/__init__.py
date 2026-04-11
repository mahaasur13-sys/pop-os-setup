"""
ATOMFederationOS Resilience Layer — v6.5

Modules:
  v6.4 (base closed-loop):
    - PolicyEngine       — 22 rules, trigger → action mapping
    - ResilienceReactor  — event-driven dispatcher
    - SelfHealingControlPlane — 7 healing actions (EVICT/RESTORE/...)
    - AdaptiveRouter     — DRL++: latency/loss-aware routing
    - StabilityMetricsEngine — rolling-window stability scoring
    - ClosedLoopResilienceController — wires all v6.4 components

  v6.5 (global control layer):
    - GlobalControlArbiter   — conflict resolution across subsystems
    - SystemOptimizer        — J() global objective + gradient descent
    - ContinuousStabilityEngine — 1Hz proactive tick loop
    - InvariantsEngine       — formal stability invariant verification
"""

from resilience.policy_engine import (
    PolicyEngine,
    PolicyRule,
    PolicyAction,
    ReactionTrigger,
    TriggerMatch,
)

from resilience.reactor import (
    ResilienceReactor,
    ReactionAction,
)

from resilience.healer import (
    SelfHealingControlPlane,
    HealingAction,
    HealingResult,
)

from resilience.adaptive_router import (
    AdaptiveRouter,
    PeerRouteState,
    RouteMetrics,
)

from resilience.metrics_engine import (
    StabilityMetricsEngine,
    StabilitySnapshot,
)

from resilience.closed_loop import (
    ClosedLoopResilienceController,
)

# v6.5
from resilience.arbitrer import (
    GlobalControlArbiter,
    ArbitrationDecision,
    ConflictType,
)

from resilience.optimizer import (
    SystemOptimizer,
    OptimizationResult,
    OptimizerWeights,
)

from resilience.continuous_stability import (
    ContinuousStabilityEngine,
    TickResult,
)

from resilience.invariants import (
    InvariantsEngine,
    Invariant,
    InvariantResult,
    InvariantSet,
    InvariantSeverity,
    StabilitySnapshot as InvariantSnapshot,
)

__all__ = [
    # v6.4 core
    "PolicyEngine",
    "PolicyRule",
    "PolicyAction",
    "ReactionTrigger",
    "TriggerMatch",
    "ResilienceReactor",
    "ReactionAction",
    "SelfHealingControlPlane",
    "HealingAction",
    "HealingResult",
    "AdaptiveRouter",
    "PeerRouteState",
    "RouteMetrics",
    "StabilityMetricsEngine",
    "StabilitySnapshot",
    "ClosedLoopResilienceController",
    # v6.5
    "GlobalControlArbiter",
    "ArbitrationDecision",
    "ConflictType",
    "SystemOptimizer",
    "OptimizationResult",
    "OptimizerWeights",
    "ContinuousStabilityEngine",
    "TickResult",
    "InvariantsEngine",
    "Invariant",
    "InvariantResult",
    "InvariantSet",
    "InvariantSeverity",
    "InvariantSnapshot",
]
