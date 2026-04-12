"""
Causal Merge Protocol — v7.3
Merges inconsistent DAGs from N workers into ONE canonical swarm DAG.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
from enum import Enum, auto


class ConflictType(Enum):
    EDGE_DIRECTION_REVERSED = auto()   # A→B in worker-1, B→A in worker-2
    EDGE_MISSING_IN_ONE = auto()      # A→B exists in worker-1 but not in worker-2
    NODE_MISSING_IN_ONE = auto()      # node appears in one DAG, not another
    CYCLIC_CONFLICT = auto()          # merge creates a cycle; needs ranking tiebreak


@dataclass
class CausalEdge:
    source: str
    target: str
    worker_ids: List[str]  # which workers observed this edge
    direction_agreed: bool  # True if ALL workers agree on source→target


@dataclass
class MergeConflict:
    conflict_type: ConflictType
    nodes: Tuple[str, ...]
    conflicting_workers: Tuple[str, ...]
    resolution: str  # human-readable resolution applied


@dataclass
class SwarmDAG:
    """Canonical DAG after merging all worker causal graphs."""
    nodes: List[str]
    edges: List[Tuple[str, str]]  # (source, target)
    conflicts_resolved: List[MergeConflict]
    edge_origin_count: Dict[Tuple[str, str], int]  # (A,B)→N workers saw it


class CausalMergeProtocol:
    """
    Merges N worker DAGs into ONE canonical swarm DAG.

    Core challenge addressed (NON-ISOMORPHIC DAGs):
      worker-1: A→B→C   (B observed)
      worker-2: A→C     (B skipped, different observation window)

    Both must collapse into ONE canonical DAG for cross-worker comparisons.

    Resolution rules (in order):
      1. Majority vote on edge direction
      2. If tied → prefer edge present (more observed information)
      3. If cycle forms → topological sort with worker-0 as tiebreaker
      4. Missing nodes added as orphan nodes (observed by at least 1 worker)
    """

    def merge_worker_dags(
        self, worker_dags: Dict[str, Dict[str, List[str]]]
    ) -> SwarmDAG:
        """
        Merge dict of {worker_id: {effect: [causes]}} into a canonical SwarmDAG.
        """
        if not worker_dags:
            return SwarmDAG(nodes=[], edges=[], conflicts_resolved=[], edge_origin_count={})

        all_nodes: Set[str] = set()
        edge_multiset: Dict[Tuple[str, str], List[str]] = defaultdict(list)

        for worker_id, dag in worker_dags.items():
            for target, causes in dag.items():
                all_nodes.add(target)
                for cause in causes:
                    all_nodes.add(cause)
                    edge_multiset[(cause, target)].append(worker_id)
                if not causes:
                    all_nodes.add(target)

        # Detect conflicts
        resolved_edges: List[Tuple[str, str]] = []
        conflicts: List[MergeConflict] = []

        for (src, tgt), workers in edge_multiset.items():
            # Check for reversed edge
            reversed_key = (tgt, src)
            if reversed_key in edge_multiset:
                # There is BOTH A→B and B→A — conflict
                conflict = MergeConflict(
                    conflict_type=ConflictType.EDGE_DIRECTION_REVERSED,
                    nodes=(src, tgt),
                    conflicting_workers=tuple(set(list(workers) + list(edge_multiset.get(reversed_key, [])))),
                    resolution="apply majority vote; prefer direction with more witnesses; "
                              "if equal, prefer present edge over absent",
                )
                conflicts.append(conflict)
                # Resolution: keep the direction with MORE workers
                fwd_count = len(workers)
                rev_count = len(edge_multiset.get(reversed_key, []))
                if fwd_count >= rev_count:
                    resolved_edges.append((src, tgt))
                else:
                    resolved_edges.append(reversed_key)
            else:
                resolved_edges.append((src, tgt))

        # Topological sort + cycle detection
        try:
            sorted_nodes = self._topo_sort_with_fallback(list(all_nodes), resolved_edges)
        except ValueError:
            # Cycle detected — break with worker-0 tiebreaker
            sorted_nodes = self._break_cycle(list(all_nodes), resolved_edges)
            conflicts.append(MergeConflict(
                conflict_type=ConflictType.CYCLIC_CONFLICT,
                nodes=tuple(all_nodes),
                conflicting_workers=tuple(worker_dags.keys()),
                resolution="cycle broken via topological sort fallback with worker-0 ranking",
            ))

        # Count per edge
        edge_origin_count = {
            edge: len(workers)
            for edge, workers in edge_multiset.items()
        }

        return SwarmDAG(
            nodes=sorted_nodes,
            edges=resolved_edges,
            conflicts_resolved=conflicts,
            edge_origin_count=edge_origin_count,
        )

    def _topo_sort_with_fallback(self, nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
        """Topological sort with deterministic tiebreaker."""
        in_degree: Dict[str, int] = {n: 0 for n in nodes}
        adj: Dict[str, List[str]] = {n: [] for n in nodes}
        for src, tgt in edges:
            adj[src].append(tgt)
            in_degree[tgt] += 1

        queue = [n for n in nodes if in_degree[n] == 0]
        queue.sort()  # deterministic
        sorted_nodes: List[str] = []

        while queue:
            node = queue.pop(0)
            sorted_nodes.append(node)
            for nb in adj[node]:
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    queue.append(nb)
                    queue.sort()

        if len(sorted_nodes) != len(nodes):
            raise ValueError("Cycle detected in DAG")
        return sorted_nodes

    def _break_cycle(self, nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
        """
        Break cycles by removing the edge with the lowest witness count.
        Retry until acyclic.
        """
        remaining_edges: List[Tuple[str, str]] = list(edges)
        edge_witnesses: Dict[Tuple[str, str], int] = {}
        for (src, tgt), workers in defaultdict(list).items():
            edge_witnesses[(src, tgt)] = len(workers)

        while True:
            in_degree = {n: 0 for n in nodes}
            adj = {n: [] for n in nodes}
            for src, tgt in remaining_edges:
                adj[src].append(tgt)
                in_degree[tgt] += 1

            try:
                queue = [n for n in nodes if in_degree[n] == 0]
                queue.sort()
                sorted_nodes = []
                while queue:
                    node = queue.pop(0)
                    sorted_nodes.append(node)
                    for nb in adj[node]:
                        in_degree[nb] -= 1
                        if in_degree[nb] == 0:
                            queue.append(nb)
                            queue.sort()
                if len(sorted_nodes) == len(nodes):
                    return sorted_nodes
            except Exception:
                pass

            # Remove lowest-witness edge to break cycle
            if remaining_edges:
                # Find edge to remove: prefer edges with few witnesses
                to_remove = min(remaining_edges, key=lambda e: edge_witnesses.get(e, 0))
                remaining_edges.remove(to_remove)
            else:
                return nodes  # fallback

    def compute_swarm_causal_depth(self, swarm_dag: SwarmDAG) -> Dict[str, int]:
        """Compute depth (longest-path from roots) for each node in the canonical swarm DAG."""
        depth: Dict[str, int] = {}
        memo: Dict[str, int] = {}

        def compute_depth(node: str) -> int:
            if node in memo:
                return memo[node]
            incoming = [(src, tgt) for src, tgt in swarm_dag.edges if tgt == node]
            if not incoming:
                memo[node] = 0
                return 0
            d = 1 + max((compute_depth(src) for src, _ in incoming), default=0)
            memo[node] = d
            return d

        for node in swarm_dag.nodes:
            depth[node] = compute_depth(node)
        return depth
