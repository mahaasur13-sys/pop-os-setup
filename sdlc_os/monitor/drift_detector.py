"""Drift detection engine for SDLC OS."""

from __future__ import annotations

from ..sdlc_types import DriftSignal, DriftLevel, Severity, SystemStateSnapshot
from ..graph.dag import DAG
from typing import Optional


class DriftDetector:
    """
    Detects architectural drift in repository state.
    
    Drift score formula:
        drift_score = 0.4 * dependency_inconsistency
                    + 0.3 * structural_changes
                    + 0.2 * unexpected_new_nodes
                    + 0.1 * orphan_modules
    """

    def __init__(self):
        self.previous_state: Optional[SystemStateSnapshot] = None

    def compute_drift(self, snapshot: SystemStateSnapshot) -> tuple[float, DriftLevel, list[DriftSignal]]:
        """
        Compute drift score and detect anomalies.
        
        Args:
            snapshot: current system state snapshot
        
        Returns:
            (drift_score, drift_level, anomalies)
        """
        anomalies = []

        # Calculate components
        dep_inconsistency = self._calc_dependency_inconsistency(snapshot)
        structural_changes = self._calc_structural_changes(snapshot)
        unexpected_nodes = self._calc_unexpected_nodes(snapshot)
        orphan_modules = self._calc_orphan_modules(snapshot)

        # Weighted drift score
        drift_score = (
            0.4 * dep_inconsistency +
            0.3 * structural_changes +
            0.2 * unexpected_nodes +
            0.1 * orphan_modules
        )
        drift_score = min(1.0, max(0.0, drift_score))

        # Determine drift level
        if drift_score < 0.3:
            drift_level = DriftLevel.STABLE
        elif drift_score < 0.7:
            drift_level = DriftLevel.DEGRADED
        else:
            drift_level = DriftLevel.CRITICAL

        # Generate anomaly signals
        if dep_inconsistency > 0.5:
            anomalies.append(DriftSignal(
                signal_type='dependency_inconsistency',
                level=Severity.HIGH if dep_inconsistency > 0.7 else DriftLevel.MEDIUM,
                affected_components=self._get_inconsistent_deps(snapshot),
                description='Dependency graph inconsistencies detected',
                drift_score_delta=0.4 * dep_inconsistency
            ))

        if structural_changes > 0.6:
            anomalies.append(DriftSignal(
                signal_type='structural_drift',
                level=Severity.HIGH if structural_changes > 0.8 else DriftLevel.MEDIUM,
                affected_components=self._get_structural_changes(snapshot),
                description='Significant structural changes in architecture',
                drift_score_delta=0.3 * structural_changes
            ))

        if unexpected_nodes > 0.7:
            anomalies.append(DriftSignal(
                signal_type='unexpected_new_nodes',
                level=Severity.MEDIUM,
                affected_components=self._get_new_nodes(snapshot),
                description='New unexpected modules detected',
                drift_score_delta=0.2 * unexpected_nodes
            ))

        if orphan_modules > 0.5:
            anomalies.append(DriftSignal(
                signal_type='orphan_modules',
                level=Severity.LOW,
                affected_components=self._get_orphan_modules(snapshot),
                description='Orphan modules without dependencies detected',
                drift_score_delta=0.1 * orphan_modules
            ))

        return drift_score, drift_level, anomalies

    def _calc_dependency_inconsistency(self, snapshot: SystemStateSnapshot) -> float:
        """
        Calculate dependency inconsistency score.
        High value when import graph differs significantly from actual usage.
        """
        if not self.previous_state:
            return 0.0

        # Compare edge counts
        prev_edges = len(self.previous_state.graph_edges)
        curr_edges = len(snapshot.graph_edges)

        if prev_edges == 0:
            return 0.0

        edge_diff = abs(curr_edges - prev_edges) / max(prev_edges, curr_edges)

        # Compare node import patterns
        prev_imports = set()
        for edge in self.previous_state.graph_edges:
            prev_imports.add((edge.get('from_node', ''), edge.get('to_node', '')))

        curr_imports = set()
        for edge in snapshot.graph_edges:
            curr_imports.add((edge.get('from_node', ''), edge.get('to_node', '')))

        if len(prev_imports) == 0:
            return 0.0

        changed_imports = len(prev_imports.symmetric_difference(curr_imports))
        import_inconsistency = changed_imports / max(len(prev_imports), len(curr_imports), 1)

        return min(1.0, (edge_diff + import_inconsistency) / 2)

    def _calc_structural_changes(self, snapshot: SystemStateSnapshot) -> float:
        """Calculate how much the structural layout changed."""
        if not self.previous_state:
            return 0.0

        prev_nodes = len(self.previous_state.graph_nodes)
        curr_nodes = len(snapshot.graph_nodes)

        # Node count change
        if prev_nodes == 0:
            return 0.0

        node_change = abs(curr_nodes - prev_nodes) / max(prev_nodes, curr_nodes)

        # Check for deleted core modules
        prev_cores = {n['module_name'] for n in self.previous_state.graph_nodes 
                     if n.get('node_type') == 'core'}
        curr_cores = {n['module_name'] for n in snapshot.graph_nodes 
                     if n.get('node_type') == 'core'}
        
        deleted_cores = len(prev_cores - curr_cores)
        core_deletion_rate = deleted_cores / max(len(prev_cores), 1)

        return min(1.0, node_change + core_deletion_rate)

    def _calc_unexpected_nodes(self, snapshot: SystemStateSnapshot) -> float:
        """
        Calculate unexpected new nodes score.
        Nodes that don't fit standard patterns.
        """
        if not self.previous_state:
            prev_names = set()
        else:
            prev_names = {n['module_name'] for n in self.previous_state.graph_nodes}

        curr_names = {n['module_name'] for n in snapshot.graph_nodes}
        new_nodes = curr_names - prev_names

        if len(curr_names) == 0:
            return 0.0

        # Unexpected = UNKNOWN type or non-standard naming
        unexpected = 0
        for name in new_nodes:
            for node in snapshot.graph_nodes:
                if node['module_name'] == name:
                    if node.get('node_type') == 'unknown':
                        unexpected += 1
                    break

        return unexpected / max(len(curr_names), 1)

    def _calc_orphan_modules(self, snapshot: SystemStateSnapshot) -> float:
        """Calculate orphan modules score (nodes with no dependencies)."""
        if not snapshot.graph_nodes:
            return 0.0

        orphan_count = 0
        for node in snapshot.graph_nodes:
            node_name = node['module_name']
            # Check if node has any incoming or outgoing edges
            has_deps = any(
                e['from_node'] == node_name or e['to_node'] == node_name
                for e in snapshot.graph_edges
            )
            if not has_deps:
                orphan_count += 1

        return orphan_count / max(len(snapshot.graph_nodes), 1)

    def _get_inconsistent_deps(self, snapshot: SystemStateSnapshot) -> list[str]:
        """Get list of nodes with inconsistent dependencies."""
        return [n['module_name'] for n in snapshot.graph_nodes[-5:]]

    def _get_structural_changes(self, snapshot: SystemStateSnapshot) -> list[str]:
        """Get list of structurally changed nodes."""
        return [n['module_name'] for n in snapshot.graph_nodes 
                if n.get('node_type') == 'core'][:3]

    def _get_new_nodes(self, snapshot: SystemStateSnapshot) -> list[str]:
        """Get newly added nodes."""
        if not self.previous_state:
            return []
        prev_names = {n['module_name'] for n in self.previous_state.graph_nodes}
        return [n['module_name'] for n in snapshot.graph_nodes 
                if n['module_name'] not in prev_names]

    def _get_orphan_modules(self, snapshot: SystemStateSnapshot) -> list[str]:
        """Get orphan module names."""
        orphans = []
        for node in snapshot.graph_nodes:
            node_name = node['module_name']
            has_edges = any(
                e['from_node'] == node_name or e['to_node'] == node_name
                for e in snapshot.graph_edges
            )
            if not has_edges:
                orphans.append(node_name)
        return orphans[:5]

    def update_previous_state(self, snapshot: SystemStateSnapshot) -> None:
        """Store snapshot for next comparison."""
        self.previous_state = snapshot