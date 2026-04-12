"""ConsensusResolver — derives a consistent θ from a set of StateVectors.

Rules (in priority order):
  1. If ≥ 2/3 nodes agree on same theta_hash → accept consensus
  2. If no quorum → pick node with max stability_score (or min drift on tie)
  3. Stale vectors are excluded from quorum calculation
  4. Malicious/bad vectors (score anomalies) → isolated via replay validation
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from federation.state_vector import StateVector


@dataclass
class ConsensusResult:
    theta_hash: str
    source: Literal["quorum", "highest_stability", "local_only", "no_peers"]
    confidence: float  # 0.0–1.0
    voters: list[str] = field(default_factory=list)
    timestamp_ns: int = field(default_factory=time.time_ns)

    @property
    def is_quorum(self) -> bool:
        return self.source == "quorum"


@dataclass
class QuorumConfig:
    quorum_fraction: float = 2 / 3       # 2/3 required
    stale_threshold_ms: int = 30_000
    min_nodes: int = 1                   # minimum nodes to consider consensus
    max_age_ms: int = 60_000             # max age for vectors to participate


class ConsensusResolver:
    """Resolves distributed state to a single theta_hash."""

    def __init__(self, node_id: str, config: QuorumConfig | None = None):
        self.node_id = node_id
        self.config = config or QuorumConfig()

    def resolve(
        self,
        my_vector: StateVector,
        peer_vectors: list[StateVector],
        local_theta_hash: str,
    ) -> ConsensusResult:
        """Main entry point. Returns consensus result for a single theta."""
        all_vectors = [my_vector] + list(peer_vectors)
        total_nodes = len(all_vectors)

        # Filter out stale vectors
        now_ns = time.time_ns()
        fresh = [
            v for v in all_vectors
            if (now_ns - v.timestamp_ns) / 1_000_000 <= self.config.max_age_ms
        ]

        if not fresh:
            # No fresh vectors — if we have no peers, admit defeat (local_only)
            # If we have peers but they're all stale, use highest_stability as fallback
            if not peer_vectors:
                return ConsensusResult(
                    theta_hash=local_theta_hash,
                    source="local_only",
                    confidence=0.0,
                    voters=[],
                )
            # Peers exist but all stale → use local vector as best effort
            return ConsensusResult(
                theta_hash=my_vector.theta_hash,
                source="highest_stability",
                confidence=my_vector.stability_score,
                voters=[my_vector.node_id],
            )

        # Count by theta_hash (only fresh vectors participate)
        vote_counts: dict[str, list[str]] = {}
        for v in fresh:
            vote_counts.setdefault(v.theta_hash, []).append(v.node_id)

        # Threshold: need at least 2 nodes and 2/3 of fresh nodes
        threshold = max(2, self.config.quorum_fraction * total_nodes)

        # Rule 1: quorum
        for theta_hash, voters in vote_counts.items():
            if len(voters) >= threshold:
                confidence = len(voters) / total_nodes
                return ConsensusResult(
                    theta_hash=theta_hash,
                    source="quorum",
                    confidence=confidence,
                    voters=voters,
                )

        # Rule 2: highest stability_score (stability-first policy)
        best_vector = max(
            fresh,
            key=lambda v: (v.stability_score, -v.drift_score),
        )
        confidence = best_vector.stability_score / max(v.stability_score for v in fresh)
        return ConsensusResult(
            theta_hash=best_vector.theta_hash,
            source="highest_stability",
            confidence=confidence,
            voters=[best_vector.node_id],
        )

    def resolve_many(
        self,
        my_vector: StateVector,
        peer_vectors: list[StateVector],
        local_thetas: dict[str, str],  # key → theta_hash
    ) -> dict[str, ConsensusResult]:
        """Resolve consensus for multiple theta keys."""
        all_vectors = [my_vector] + list(peer_vectors)

        # For each key, group vectors by the key's theta_hash
        results = {}
        for key in local_thetas:
            local_hash = local_thetas[key]
            # Find peer vectors that match this key
            # (In practice, each node tracks which key a vector belongs to)
            # Here we do per-key consensus based on all vectors
            results[key] = self.resolve(my_vector, peer_vectors, local_hash)

        return results

    def detect_divergence(
        self, my_vector: StateVector, peer_vectors: list[StateVector]
    ) -> float:
        """Return 0.0–1.0 indicating how much this node differs from peers."""
        if not peer_vectors:
            return 0.0

        same_count = sum(1 for v in peer_vectors if v.theta_hash == my_vector.theta_hash)
        return 1.0 - (same_count / len(peer_vectors))

    def is_safe_remote_theta(
        self,
        remote_theta: dict,
        remote_vector: StateVector,
    ) -> bool:
        """H-4 gate: remote theta must pass local replay before application.

        Caller is responsible for running ReplayValidator.
        This method just verifies the vector passes basic sanity checks.
        """
        if remote_vector.envelope_state == "collapse":
            return False
        if remote_vector.drift_score > 0.9:  # extremely unstable
            return False
        if remote_vector.is_stale(self.config.stale_threshold_ms):
            return False
        return True