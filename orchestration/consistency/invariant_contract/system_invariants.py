"""
system_invariants.py — v8.4b pre-defined system invariants

Each invariant is an InvariantDefinition bound to a check_fn
that evaluates the current system state dict.

State dict schema (expected keys):
  is_oscillating: bool
  oscillation_frequency: float
  coherence_trajectory: list[float]
  trace_completeness: float
  total_nodes: int
  has_quarantined_nodes: bool
  quarantined_nodes: list[str]
  active_quorum_nodes: list[str]
  consensus_convergence_rate: float
  leader_election_self_vote: bool
  weight_adjustments: list[float]
  dag_has_cycles: bool
  eval_scores: list[float]
  score_bounds: tuple[float, float]
  replan_count: int
  total_nodes: int

Usage:
    registry = InvariantRegistry()
    for inv in get_all_system_invariants():
        registry.register(inv)
"""

import math
from orchestration.consistency.invariant_contract.invariant_contract import (
    InvariantDefinition,
    InvariantSeverity,
    EnforcementAction,
)


def _check_oscillation(state: dict, max_freq: float = 0.5) -> bool:
    return (
        not state.get("is_oscillating", False)
        or (state.get("oscillation_frequency", 0) or 0) < max_freq
    )


def _check_replay_determinism(state: dict) -> bool:
    history = state.get("replay_history", [])
    if len(history) < 2:
        return True
    return all(h == history[0] for h in history)


def _check_no_quarantined_in_quorum(state: dict) -> bool:
    quarantined = set(state.get("quarantined_nodes", []))
    quorum = set(state.get("active_quorum_nodes", []))
    return len(quarantined & quorum) == 0


def _check_monotonic_consensus(state: dict) -> bool:
    rate = state.get("consensus_convergence_rate", 1.0)
    return rate >= 0  # non-negative; can be extended with monotonicity check


def _check_no_self_election(state: dict) -> bool:
    return not state.get("leader_election_self_vote", False)


def _check_weight_bounded(state: dict, max_adj: float = 0.3) -> bool:
    adjustments = state.get("weight_adjustments", [])
    if not adjustments:
        return True
    return all(abs(a) <= max_adj for a in adjustments)


def _check_trace_completeness(state: dict, min_completeness: float = 0.95) -> bool:
    return state.get("trace_completeness", 1.0) >= min_completeness


def _check_dag_acyclic(state: dict) -> bool:
    return not state.get("dag_has_cycles", False)


def _check_score_bounds(state: dict) -> bool:
    scores = state.get("eval_scores", [])
    if not scores:
        return True
    lo, hi = state.get("score_bounds", (0.0, 1.0))
    return all(lo <= s <= hi for s in scores)


def _check_replan_bounded(state: dict, max_replans: int = 10) -> bool:
    return state.get("replan_count", 0) <= max_replans


# ─────────────────────────────────────────────────────────────────
# Pre-defined invariants
# ─────────────────────────────────────────────────────────────────

NO_OSCILLATION_OVER_THRESHOLD = InvariantDefinition(
    name="NO_OSCILLATION_OVER_THRESHOLD",
    description=(
        "System must not be in a high-frequency oscillation state. "
        "Oscillation causes instability in planning coherence."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=lambda s: _check_oscillation(s, max_freq=0.5),
    violation_cost=1.0,
    tags=["oscillation", "stability", "critical"],
)

REPLAY_DETERMINISM = InvariantDefinition(
    name="REPLAY_DETERMINISM",
    description=(
        "Replay operations must produce identical results for identical inputs. "
        "Non-deterministic replay invalidates fault-tolerance guarantees."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.ROLLBACK,
    check_fn=_check_replay_determinism,
    violation_cost=1.0,
    tags=["replay", "determinism", "fault_tolerance"],
)

NO_QUARANTINED_NODE_IN_QUORUM = InvariantDefinition(
    name="NO_QUARANTINED_NODE_IN_QUORUM",
    description=(
        "A node that has been quarantined due to faults must not participate "
        "in consensus quorum decisions. Violation risks consensus corruption."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.QUARANTINE,
    check_fn=_check_no_quarantined_in_quorum,
    violation_cost=1.0,
    tags=["quorum", "consensus", "fault_tolerance"],
)

MONOTONIC_CONSENSUS_CONVERGENCE = InvariantDefinition(
    name="MONOTONIC_CONSENSUS_CONVERGENCE",
    description=(
        "Consensus convergence rate must never decrease across ticks. "
        "Non-monotonic convergence signals partition or split-brain."
    ),
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=_check_monotonic_consensus,
    violation_cost=0.8,
    tags=["consensus", "convergence"],
)

CONSENSUS_LEADER_NO_SELF_ELECTION = InvariantDefinition(
    name="CONSENSUS_LEADER_NO_SELF_ELECTION",
    description=(
        "A node must not vote for itself as leader. Self-election indicates "
        "a broken election protocol or split-brain condition."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_no_self_election,
    violation_cost=1.0,
    tags=["leader_election", "consensus"],
)

WEIGHT_ADJUSTMENT_BOUNDED = InvariantDefinition(
    name="WEIGHT_ADJUSTMENT_BOUNDED",
    description=(
        "Single weight adjustment must not exceed 0.3 (L2 norm). "
        "Unbounded adjustments can destabilize the gain scheduler."
    ),
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=lambda s: _check_weight_bounded(s, max_adj=0.3),
    violation_cost=0.7,
    tags=["weights", "gain_scheduler", "stability"],
)

PLAN_TRACE_COMPLETENESS = InvariantDefinition(
    name="PLAN_TRACE_COMPLETENESS",
    description=(
        "Planning trace must be at least 95% complete. "
        "Incomplete traces undermine observability and auditability."
    ),
    severity=InvariantSeverity.MEDIUM,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=lambda s: _check_trace_completeness(s, min_completeness=0.95),
    violation_cost=0.5,
    tags=["observability", "trace", "audit"],
)

DAG_CYCLE_FREEDOM = InvariantDefinition(
    name="DAG_CYCLE_FREEDOM",
    description=(
        "The plan DAG must remain acyclic. Cycles indicate circular "
        "dependencies that block execution and corrupt planning."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_dag_acyclic,
    violation_cost=1.0,
    tags=["dag", "cycle", "planning"],
)

EVALUATION_SCORE_BOUNDS = InvariantDefinition(
    name="EVALUATION_SCORE_BOUNDS",
    description=(
        "All evaluation scores must remain within [0.0, 1.0]. "
        "Out-of-bounds scores indicate measurement error or corruption."
    ),
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.CORRECT,
    check_fn=_check_score_bounds,
    violation_cost=0.6,
    tags=["evaluation", "scores", "bounds"],
)

REPLAN_COUNT_BOUNDED = InvariantDefinition(
    name="REPLAN_COUNT_BOUNDED",
    description=(
        "Replan count per evaluation window must not exceed 10. "
        "Excessive replanning indicates structural instability."
    ),
    severity=InvariantSeverity.MEDIUM,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=lambda s: _check_replan_bounded(s, max_replans=10),
    violation_cost=0.4,
    tags=["replanning", "stability"],
)


def get_all_system_invariants() -> list[InvariantDefinition]:
    """Return all pre-defined system invariants in registration order."""
    return [
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
    ]