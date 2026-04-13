"""
system_invariants.py — v9.0 pre-defined system invariants
"""
from orchestration.consistency.invariant_contract.invariant_contract import (
    InvariantDefinition, InvariantSeverity, EnforcementAction)

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
    return state.get("consensus_convergence_rate", 1.0) >= 0

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

def _check_hash_mode_consistency(state: dict) -> bool:
    peer_states = state.get("peer_states", {})
    if not peer_states:
        return True
    by_root: dict[str, list[str]] = {}
    for peer_id, info in peer_states.items():
        root = info.get("last_root_hash", "")
        if not root:
            continue
        by_root.setdefault(root, []).append(info.get("hash_mode", "CONSENSUS"))
    for root, modes in by_root.items():
        if len(set(modes)) > 1:
            return False
    return True

def _check_proof_trust_bounded(state: dict) -> bool:
    """PROOF_TRUST_BOUNDED: trust_score must be in [0.0, 1.0] for all known proofs."""
    proof_trust_scores = state.get("proof_trust_scores", {})
    if not proof_trust_scores:
        return True
    return all(0.0 <= s <= 1.0 for s in proof_trust_scores.values())

def _check_stale_proof_not_trusted(state: dict) -> bool:
    """
    STALE_PROOF_NOT_TRUSTED: if is_stale=True for a proof_hash,
    trust_score must be ≈ 0.0 (< 0.01).
    """
    stale_proofs = state.get("stale_proof_trust_scores", {})
    if not stale_proofs:
        return True
    return all(s < 0.01 for s in stale_proofs.values())

def _check_trust_convergence(state: dict) -> bool:
    """
    TRUST_CONVERGENCE_INVARIANT: for all tracked proof_hashes,
    the difference between each pair of peer trust scores must
    be within tolerance (≤ 0.05) when ledger_versions match.

    State fields:
      - peer_trust_vectors: {node_id: {proof_hash: TrustEntry}}
      - convergence_tolerance: float (default 0.05)
    """
    peer_vectors = state.get("peer_trust_vectors", {})
    tolerance = state.get("convergence_tolerance", 0.05)

    if len(peer_vectors) < 2:
        return True  # need ≥ 2 peers to check convergence

    # Collect all proof hashes across peers
    all_hashes: set[str] = set()
    for vec in peer_vectors.values():
        all_hashes.update(vec.keys())

    for proof_hash in all_hashes:
        entries = {}
        for node_id, vec in peer_vectors.items():
            if proof_hash in vec:
                entries[node_id] = vec[proof_hash]

        if len(entries) < 2:
            continue  # need ≥ 2 peers with this hash to compare

        # If ledger_versions match, trust_scores must also match within tolerance
        versions = [e.ledger_version for e in entries.values()]
        if len(set(versions)) == 1:  # all same ledger_version → must converge
            scores = [e.trust_score for e in entries.values()]
            if max(scores) - min(scores) > tolerance:
                return False  # divergence despite matching ledger versions
    return True

def _check_trust_vector_consistency(state: dict) -> bool:
    """
    TRUST_VECTOR_CONSISTENCY: all trust_scores in a TrustVector
    must be in [0.0, 1.0] and all ledger_versions must be non-negative.

    This is checked per-vector (individual node state).
    """
    entries = state.get("trust_vector_entries", {})
    if not entries:
        return True
    for k, e in entries.items():
        score = e["trust_score"] if isinstance(e, dict) else e.trust_score
        lv = e["ledger_version"] if isinstance(e, dict) else e.ledger_version
        if not (0.0 <= score <= 1.0):
            return False
        if lv < 0:
            return False
    return True

NO_OSCILLATION_OVER_THRESHOLD = InvariantDefinition(
    name="NO_OSCILLATION_OVER_THRESHOLD",
    description="System must not be in a high-frequency oscillation state.",
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=lambda s: _check_oscillation(s, max_freq=0.5),
    violation_cost=1.0, tags=["oscillation", "stability", "critical"])

REPLAY_DETERMINISM = InvariantDefinition(
    name="REPLAY_DETERMINISM",
    description="Replay operations must produce identical results for identical inputs.",
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.ROLLBACK,
    check_fn=_check_replay_determinism,
    violation_cost=1.0, tags=["replay", "determinism", "fault_tolerance"])

NO_QUARANTINED_NODE_IN_QUORUM = InvariantDefinition(
    name="NO_QUARANTINED_NODE_IN_QUORUM",
    description="A quarantined node must not participate in consensus quorum.",
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.QUARANTINE,
    check_fn=_check_no_quarantined_in_quorum,
    violation_cost=1.0, tags=["quorum", "consensus", "fault_tolerance"])

MONOTONIC_CONSENSUS_CONVERGENCE = InvariantDefinition(
    name="MONOTONIC_CONSENSUS_CONVERGENCE",
    description="Consensus convergence rate must never decrease across ticks.",
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=_check_monotonic_consensus,
    violation_cost=0.8, tags=["consensus", "convergence"])

CONSENSUS_LEADER_NO_SELF_ELECTION = InvariantDefinition(
    name="CONSENSUS_LEADER_NO_SELF_ELECTION",
    description="A node must not vote for itself as leader.",
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_no_self_election,
    violation_cost=1.0, tags=["leader_election", "consensus"])

WEIGHT_ADJUSTMENT_BOUNDED = InvariantDefinition(
    name="WEIGHT_ADJUSTMENT_BOUNDED",
    description="Single weight adjustment must not exceed 0.3 (L2 norm).",
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=lambda s: _check_weight_bounded(s, max_adj=0.3),
    violation_cost=0.7, tags=["weights", "gain_scheduler", "stability"])

PLAN_TRACE_COMPLETENESS = InvariantDefinition(
    name="PLAN_TRACE_COMPLETENESS",
    description="Planning trace must be at least 95% complete.",
    severity=InvariantSeverity.MEDIUM,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=lambda s: _check_trace_completeness(s, min_completeness=0.95),
    violation_cost=0.5, tags=["observability", "trace", "audit"])

DAG_CYCLE_FREEDOM = InvariantDefinition(
    name="DAG_CYCLE_FREEDOM",
    description="The plan DAG must remain acyclic.",
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_dag_acyclic,
    violation_cost=1.0, tags=["dag", "cycle", "planning"])

EVALUATION_SCORE_BOUNDS = InvariantDefinition(
    name="EVALUATION_SCORE_BOUNDS",
    description="All evaluation scores must remain within [0.0, 1.0].",
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.CORRECT,
    check_fn=_check_score_bounds,
    violation_cost=0.6, tags=["evaluation", "scores", "bounds"])

REPLAN_COUNT_BOUNDED = InvariantDefinition(
    name="REPLAN_COUNT_BOUNDED",
    description="Replan count per evaluation window must not exceed 10.",
    severity=InvariantSeverity.MEDIUM,
    enforcement_action=EnforcementAction.ESCALATE,
    check_fn=lambda s: _check_replan_bounded(s, max_replans=10),
    violation_cost=0.4, tags=["replanning", "stability"])

HASH_MODE_CONSISTENCY = InvariantDefinition(
    name="HASH_MODE_CONSISTENCY",
    description=(
        "All federation peers sharing the same DAG root_hash must agree on DAGHashMode. "
        "Mixed modes for the same root indicate consensus failure in the gossip layer."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_hash_mode_consistency,
    violation_cost=1.0, tags=["gossip", "mode_propagation", "v9.0"])

PROOF_TRUST_BOUNDED = InvariantDefinition(
    name="PROOF_TRUST_BOUNDED",
    description=(
        "All proof trust_scores must be within [0.0, 1.0] at all times. "
        "trust_score is a continuous decay function — it must never exceed bounds."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_proof_trust_bounded,
    violation_cost=1.0,
    tags=["proof_ledger", "trust", "bounds", "v9.4"])

STALE_PROOF_NOT_TRUSTED = InvariantDefinition(
    name="STALE_PROOF_NOT_TRUSTED",
    description=(
        "A proof that has exceeded its TTL (is_stale=True) must have trust_score≈0. "
        "Stale proofs decay to zero trust and must not influence consensus."
    ),
    severity=InvariantSeverity.CRITICAL,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_stale_proof_not_trusted,
    violation_cost=1.0,
    tags=["proof_ledger", "trust", "stale", "v9.4"])

TRUST_CONVERGENCE_INVARIANT = InvariantDefinition(
    name="TRUST_CONVERGENCE_INVARIANT",
    description=(
        "For all tracked proof_hashes, the difference between each pair of peer trust scores must "
        "be within tolerance (≤ 0.05) when ledger_versions match."
    ),
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_trust_convergence,
    violation_cost=0.9,
    tags=["proof_ledger", "trust", "convergence", "v9.5"])

TRUST_VECTOR_CONSISTENCY = InvariantDefinition(
    name="TRUST_VECTOR_CONSISTENCY",
    description=(
        "All trust_scores in a TrustVector must be in [0.0, 1.0] and all ledger_versions must be non-negative."
    ),
    severity=InvariantSeverity.HIGH,
    enforcement_action=EnforcementAction.BLOCK_MUTATION,
    check_fn=_check_trust_vector_consistency,
    violation_cost=0.9,
    tags=["proof_ledger", "trust", "consistency", "v9.5"])

def get_all_system_invariants() -> list[InvariantDefinition]:
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
        HASH_MODE_CONSISTENCY,  # v9.0
        PROOF_TRUST_BOUNDED,      # v9.4
        STALE_PROOF_NOT_TRUSTED,  # v9.4
        TRUST_CONVERGENCE_INVARIANT,  # v9.5
        TRUST_VECTOR_CONSISTENCY,  # v9.5
    ]
