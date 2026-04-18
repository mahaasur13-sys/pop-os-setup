"""Patch generator for SDLC OS Healer Engine."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RepairPlan:
    """
    A planned repair action to be reviewed before execution.
    
    Attributes:
        target_node: Module/node name affected
        issue_type: Type of issue being addressed
        proposed_fix: Description of the proposed fix
        risk_level: 0.0-1.0 risk assessment
        strategy_category: Which repair strategy applies
        estimated_impact: What will change if applied
    """
    target_node: str
    issue_type: str
    proposed_fix: str
    risk_level: float
    strategy_category: str
    estimated_impact: str


class PatchGenerator:
    """
    Generates repair plans based on detected anomalies.
    
    This is a NON-DESTRUCTIVE generator. It only creates plans,
    it does not apply them. Plans must be reviewed and approved
    before execution (future phase).
    """
    
    def __init__(self):
        self._plan_counter = 0
    
    def generate_plans(self, anomalies: list, snapshot: dict) -> list[RepairPlan]:
        """
        Generate repair plans from detected anomalies.
        
        Args:
            anomalies: List of drift signals from snapshot
            snapshot: Full system state snapshot
        
        Returns:
            List of RepairPlan objects (not executed)
        """
        plans = []
        nodes = {n['module_name']: n for n in snapshot.get('graph_nodes', [])}
        edges = snapshot.get('graph_edges', [])
        
        for anomaly in anomalies:
            signal_type = anomaly.get('signal_type', 'unknown')
            affected = anomaly.get('affected_components', [])
            
            plan = self._create_plan(signal_type, affected, nodes, edges)
            if plan:
                plans.append(plan)
        
        return plans
    
    def _create_plan(
        self, signal_type: str, affected: list, nodes: dict, edges: list
    ) -> Optional[RepairPlan]:
        """Create a single repair plan based on issue type."""
        
        if signal_type == 'orphan_modules':
            return self._plan_orphan_fix(affected, nodes, edges)
        
        if signal_type == 'unexpected_new_nodes':
            return self._plan_unexpected_nodes_fix(affected, nodes)
        
        if signal_type == 'dependency_inconsistency':
            return self._plan_dependency_fix(affected, edges)
        
        if signal_type == 'structural_drift':
            return self._plan_structural_fix(affected, nodes)
        
        return None
    
    def _plan_orphan_fix(self, affected: list, nodes: dict, edges: list) -> RepairPlan:
        """Plan repair for orphan modules."""
        self._plan_counter += 1
        
        target = affected[0] if affected else 'unknown'
        node = nodes.get(target, {})
        
        # Find if there's a parent module
        parent_hint = ""
        parts = target.split('.')
        if len(parts) > 1:
            parent = '.'.join(parts[:-1])
            parent_hint = f" Consider linking to parent module '{parent}' or adding __init__.py"
        
        return RepairPlan(
            target_node=target,
            issue_type="orphan_modules",
            proposed_fix=f"Add {target} to a package or create dependency links.{parent_hint}",
            risk_level=0.2,
            strategy_category="orphan_link",
            estimated_impact=f"New edges from {target} to parent module"
        )
    
    def _plan_unexpected_nodes_fix(self, affected: list, nodes: dict) -> RepairPlan:
        """Plan repair for unexpected new nodes."""
        self._plan_counter += 1
        
        target = affected[0] if affected else 'unknown'
        node = nodes.get(target, {})
        node_type = node.get('node_type', 'unknown')
        
        return RepairPlan(
            target_node=target,
            issue_type="unexpected_new_nodes",
            proposed_fix=f"Classify {target} (type: {node_type}) and establish module boundary",
            risk_level=0.3,
            strategy_category="structural_repair",
            estimated_impact=f"Node type validated, may require __init__.py or classification"
        )
    
    def _plan_dependency_fix(self, affected: list, edges: list) -> RepairPlan:
        """Plan repair for dependency inconsistencies."""
        self._plan_counter += 1
        
        target = affected[0] if affected else 'unknown'
        
        return RepairPlan(
            target_node=target,
            issue_type="dependency_inconsistency",
            proposed_fix=f"Reconcile import graph for {target}. Check for stale imports or missing deps.",
            risk_level=0.5,
            strategy_category="dependency_fix",
            estimated_impact=f"May add or remove edges from {target}"
        )
    
    def _plan_structural_fix(self, affected: list, nodes: dict) -> RepairPlan:
        """Plan repair for structural drift."""
        self._plan_counter += 1
        
        target = affected[0] if affected else 'unknown'
        
        return RepairPlan(
            target_node=target,
            issue_type="structural_drift",
            proposed_fix=f"Review structural changes in {target}. Validate against canonical architecture.",
            risk_level=0.6,
            strategy_category="structural_repair",
            estimated_impact=f"Core module structure validated, may require restoration"
        )