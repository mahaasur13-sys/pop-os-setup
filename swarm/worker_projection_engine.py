"""
Worker Projection Engine — v7.3
Each worker projects its local causal state into a shared swarm causal space.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum, auto
import hashlib
import json


class ProjectionMode(Enum):
    L1 = "L1"          # Manhattan / sum of absolute differences
    L2 = "L2"          # Euclidean / sqrt of squared differences
    HAMMING = "hamming"  # for discrete/categorical fields
    CAUSAL = "causal"    # causal-graph aware projection


@dataclass
class WorkerStateSnapshot:
    worker_id: str
    sequence_number: int
    timestamp_ms: int
    raw_state: Dict[str, Any]
    fingerprint: str  # SHA-256 of raw_state canonical JSON
    causal_graph: Dict[str, List[str]]  # {effect: [causes]}


@dataclass
class ProjectedAxis:
    axis_name: str
    projection_mode: ProjectionMode
    vector: List[float]
    magnitude: float


@dataclass
class WorkerProjection:
    worker_id: str
    sequence_number: int
    timestamp_ms: int
    axes: Dict[str, ProjectedAxis]  # axis_name → ProjectedAxis
    projected_state_hash: str  # hash of all axis vectors concatenated
    local_fingerprint: str
    causal_graph: Dict[str, List[str]]


class WorkerProjectionEngine:
    """
    Projects each worker's local causal state into a shared N-dimensional
    causal space, one axis per logical dimension of the system.

    Swarm-level challenge addressed:
      - worker-1 sees A→B→C
      - worker-2 sees A→C (B skipped, different observation window)
      Both projections must land in the SAME shared space for comparability.
    """

    def __init__(self, causal_dimensions: List[str]):
        self.causal_dimensions = causal_dimensions  # e.g. ["state", "delta", "rate", "depth", "time"]
        self.mode = ProjectionMode.CAUSAL
        self._worker_states: Dict[str, WorkerStateSnapshot] = {}

    # ------------------------------------------------------------------
    # Canonicalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonicalize(state: Dict[str, Any]) -> str:
        def _sort_key(kv):
            k, v = kv
            if isinstance(v, dict):
                return (k, "dict", sorted(v.items()))
            return (k, type(v).__name__, v)
        canonical = json.dumps(state, sort_keys=True, default=str)
        return canonical

    @staticmethod
    def _fingerprint(state: Dict[str, Any]) -> str:
        return hashlib.sha256(WorkerProjectionEngine._canonicalize(state).encode()).hexdigest()

    @staticmethod
    def _flatten_state(state: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        result = {}
        for k, v in state.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(WorkerProjectionEngine._flatten_state(v, new_key))
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        result.update(WorkerProjectionEngine._flatten_state(item, f"{new_key}[{i}]"))
                    else:
                        result[f"{new_key}[{i}]"] = item
            else:
                result[new_key] = v
        return result

    # ------------------------------------------------------------------
    # Core projection
    # ------------------------------------------------------------------

    def project_worker_state(
        self,
        worker_id: str,
        sequence_number: int,
        timestamp_ms: int,
        raw_state: Dict[str, Any],
        causal_graph: Optional[Dict[str, List[str]]] = None,
    ) -> WorkerProjection:
        """
        Project raw state into N causal axes.
        For "causal" mode: each axis gets a scalar derived from causal depth weighting.
        """
        flat = self._flatten_state(raw_state)

        axes: Dict[str, ProjectedAxis] = {}
        for dim in self.causal_dimensions:
            vec = self._project_onto_axis(flat, dim, causal_graph)
            magnitude = self._vector_magnitude(vec)
            axes[dim] = ProjectedAxis(
                axis_name=dim,
                projection_mode=self.mode,
                vector=vec,
                magnitude=magnitude,
            )

        # Build projected state hash from axis magnitudes concatenated
        mag_string = "|".join(f"{k}:{v.magnitude:.6f}" for k, v in sorted(axes.items()))
        projected_hash = hashlib.sha256(mag_string.encode()).hexdigest()

        proj = WorkerProjection(
            worker_id=worker_id,
            sequence_number=sequence_number,
            timestamp_ms=timestamp_ms,
            axes=axes,
            projected_state_hash=projected_hash,
            local_fingerprint=self._fingerprint(raw_state),
            causal_graph=causal_graph or {},
        )
        self._worker_states[worker_id] = WorkerStateSnapshot(
            worker_id=worker_id,
            sequence_number=sequence_number,
            timestamp_ms=timestamp_ms,
            raw_state=raw_state,
            fingerprint=proj.local_fingerprint,
            causal_graph=causal_graph or {},
        )
        return proj

    def _project_onto_axis(
        self, flat_state: Dict[str, Any], axis: str, causal_graph: Optional[Dict[str, List[str]]]
    ) -> List[float]:
        """
        Project flat state dict onto one causal dimension axis.
        Returns a vector of per-field values along that axis.
        """
        if axis == "state":
            # Raw values of all leaf fields
            return [float(v) if isinstance(v, (int, float)) else 0.0 for v in flat_state.values()]

        elif axis == "delta":
            # Rate of change of each numeric field (1-element window = just the value)
            return [1.0 if isinstance(v, (int, float)) else 0.0 for v in flat_state.values()]

        elif axis == "rate":
            # Second-derivative proxy: uniform 1.0 for now (placeholder for real sampling)
            return [1.0 if isinstance(v, (int, float)) else 0.0 for v in flat_state.values()]

        elif axis == "depth":
            # Causal depth weight per field
            depth_weights: List[float] = []
            if causal_graph:
                max_depth = self._max_causal_depth(causal_graph)
                for k in flat_state.keys():
                    field_depth = self._field_causal_depth(k, causal_graph)
                    depth_weights.append(field_depth / max_depth if max_depth > 0 else 0.0)
            else:
                depth_weights = [1.0] * len(flat_state)
            return depth_weights

        elif axis == "time":
            # Temporal recency proxy: uniform for now
            return [1.0] * len(flat_state)

        else:
            return [0.0] * len(flat_state)

    def _vector_magnitude(self, vec: List[float]) -> float:
        if not vec:
            return 0.0
        return (sum(x * x for x in vec)) ** 0.5

    def _max_causal_depth(self, causal_graph: Dict[str, List[str]]) -> int:
        """Compute the maximum depth in a DAG (longest path)."""
        memo: Dict[str, int] = {}

        def depth(node: str) -> int:
            if node not in causal_graph:
                return 0
            if node in memo:
                return memo[node]
            causes = causal_graph[node]
            if not causes:
                memo[node] = 0
                return 0
            d = 1 + max((depth(c) for c in causes), default=0)
            memo[node] = d
            return d

        return max((depth(n) for n in causal_graph), default=0)

    def _field_causal_depth(self, field_key: str, causal_graph: Dict[str, List[str]]) -> int:
        """Infer causal depth of a field from graph edges that mention it."""
        parts = field_key.split(".")
        node_candidate = parts[-1]
        if node_candidate in causal_graph:
            return self._max_causal_depth({node_candidate: causal_graph[node_candidate]})
        return 0

    # ------------------------------------------------------------------
    # Pairwise projection similarity
    # ------------------------------------------------------------------

    @staticmethod
    def pairwise_axis_distance(p1: WorkerProjection, p2: WorkerProjection, axis: str) -> float:
        """
        L2 distance between two projections on a single axis.
        Returns 0.0 if axes are identical, >0 if divergent.
        """
        ax1 = p1.axes.get(axis)
        ax2 = p2.axes.get(axis)
        if ax1 is None or ax2 is None:
            return float("inf")

        v1 = ax1.vector
        v2 = ax2.vector
        min_len = min(len(v1), len(v2))
        if min_len == 0:
            return 0.0
        # Pad shorter
        if len(v1) < len(v2):
            v1 = v1 + [0.0] * (len(v2) - len(v1))
        elif len(v2) < len(v1):
            v2 = v2 + [0.0] * (len(v1) - len(v2))

        return sum((a - b) ** 2 for a, b in zip(v1, v2)) ** 0.5

    def pairwise_swarm_distance(self, p1: WorkerProjection, p2: WorkerProjection) -> Dict[str, float]:
        """Per-axis L2 distances + total L2."""
        distances: Dict[str, float] = {}
        for axis in self.causal_dimensions:
            distances[axis] = self.pairwise_axis_distance(p1, p2, axis)
        distances["total_L2"] = (sum(d * d for d in distances.values())) ** 0.5
        return distances
