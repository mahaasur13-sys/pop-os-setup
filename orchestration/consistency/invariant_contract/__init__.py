"""
consistency/invariant_contract — v8.4b System Invariant Contract Kernel

Formal safety constraints that define "what MUST NEVER happen"
in system behavior. Closes the loop from reactive safety to
proactive enforcement.

Invariant layer: define → enforce → prevent
(Replaces detect → react → correct)

Modules:
  invariant_contract   — core classes (InvariantDefinition, Registry, Evaluator, Enforcer)
  system_invariants    — pre-defined system-level invariants

Usage:
    registry = InvariantRegistry()
    registry.register(NO_OSCILLATION_OVER_THRESHOLD)
    registry.register(REPLAY_DETERMINISM)

    enforcer = InvariantEnforcer(registry)
    violations = enforcer.evaluate(state)
    enforcer.enforce(violations)  # blocks / rolls back / alerts
"""

from orchestration.consistency.invariant_contract.invariant_contract import (
    InvariantDefinition,
    InvariantRegistry,
    InvariantEvaluator,
    InvariantEnforcer,
    InvariantViolation,
    InvariantSeverity,
    EnforcementAction,
    InvariantResult,
    SystemRiskProfile,
)

from orchestration.consistency.invariant_contract.system_invariants import (
    NO_OSCILLATION_OVER_THRESHOLD,
    REPLAY_DETERMINISM,
    NO_QUARANTINED_NODE_IN_QUORUM,
    MONOTONIC_CONSENSUS_CONVERGENCE,
    CONSENSUS_LEADER_NO_SELF_ELECTION,
    WEIGHT_ADJUSTMENT_BOUNDED,
    PLAN_TRACE_COMPLETENESS,
    DAG_CYCLE_FREEDOM,
    EVALUATION_SCORE_BOUNDS,
    REPLAN_COUNT_BOUNDED,
    get_all_system_invariants,
)

__all__ = [
    # core
    "InvariantDefinition",
    "InvariantRegistry",
    "InvariantEvaluator",
    "InvariantEnforcer",
    "InvariantViolation",
    "InvariantSeverity",
    "EnforcementAction",
    "InvariantResult",
    "SystemRiskProfile",
    # pre-defined
    "NO_OSCILLATION_OVER_THRESHOLD",
    "REPLAY_DETERMINISM",
    "NO_QUARANTINED_NODE_IN_QUORUM",
    "MONOTONIC_CONSENSUS_CONVERGENCE",
    "CONSENSUS_LEADER_NO_SELF_ELECTION",
    "WEIGHT_ADJUSTMENT_BOUNDED",
    "PLAN_TRACE_COMPLETENESS",
    "DAG_CYCLE_FREEDOM",
    "EVALUATION_SCORE_BOUNDS",
    "REPLAN_COUNT_BOUNDED",
    "get_all_system_invariants",
]
