"""Policy gate — enforces architectural and import policies."""

from phase3.validator.gates.base_gate import BaseGate, GateResult


# Forbidden import patterns — direct architecture violations
FORBIDDEN_IMPORTS = {
    "control_plane->infra",  # control plane cannot import infra layer
    "infra->control_plane",  # infra cannot import control plane
    "service->unknown",      # service layer cannot import unknown
}

# Layer hierarchy — defines allowed dependency directions
LAYER_HIERARCHY = [
    "core",      # highest
    "service",
    "utility",
    "infra",     # lowest
    "unknown",
]

# Forbidden patterns for specific layer transitions
LAYER_VIOLATION_PATTERNS = [
    # (from_layer, to_layer) — forbidden
    ("control_plane", "infra"),
    ("infra", "core"),
]


class PolicyGate(BaseGate):
    """
    Validates architectural policies and layer compliance.
    
    FAILS if:
        - Forbidden imports detected
        - Layer violation (e.g. higher layer imports lower layer without justification)
        - Service imports from unknown layer
    """
    
    @property
    def name(self) -> str:
        return "policy_gate"
    
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Check architectural policy compliance.
        
        Args:
            plan: Repair plan with potential architectural changes.
            snapshot: Current system state.
        """
        edges = snapshot.get("graph_edges", [])
        nodes = snapshot.get("graph_nodes", [])
        
        # Build node -> layer map
        node_layer: dict[str, str] = {}
        for node in nodes:
            module = node.get("module_name", "")
            ntype = node.get("node_type", {}).get("value", "unknown") if isinstance(node.get("node_type"), dict) else str(node.get("node_type", "unknown"))
            node_layer[module] = ntype
        
        violations = []
        
        for edge in edges:
            from_node = edge.get("from_node", "")
            to_node = edge.get("to_node", "")
            dep_type = edge.get("dependency_type", "")
            
            # Check for forbidden imports
            violation_key = f"{from_layer}->{to_layer}"
            from_layer = node_layer.get(from_node, "unknown")
            to_layer = node_layer.get(to_node, "unknown")
            
            # Check layer hierarchy violations
            for forbidden_from, forbidden_to in LAYER_VIOLATION_PATTERNS:
                if from_layer == forbidden_from and to_layer == forbidden_to:
                    violations.append(
                        f"Layer violation: {forbidden_from} cannot import {forbidden_to} "
                        f"(edge: {from_node} -> {to_node})"
                    )
            
            # Check import type violations
            if from_layer == "service" and to_layer == "unknown":
                violations.append(
                    f"Service layer cannot import from unknown layer: {from_node} -> {to_node}"
                )
        
        # Check plan for policy violations
        actions = plan.get("actions", [])
        for action in actions:
            action_type = action.get("type", "")
            if action_type == "add_dependency":
                # This would introduce new edge — validate before adding
                from_node = action.get("from_node", "")
                to_node = action.get("to_node", "")
                
                from_layer = node_layer.get(from_node, "unknown")
                to_layer = node_layer.get(to_node, "unknown")
                
                for forbidden_from, forbidden_to in LAYER_VIOLATION_PATTERNS:
                    if from_layer == forbidden_from and to_layer == forbidden_to:
                        violations.append(
                            f"Plan introduces layer violation: {forbidden_from} -> {forbidden_to}"
                        )
        
        if violations:
            return self._fail(
                reason=f"Policy violations detected: {len(violations)} violation(s)",
                severity="high",
                details={"violations": violations}
            )
        
        return self._pass(
            reason=f"Policy check passed. {len(edges)} edges validated.",
            details={"edges_checked": len(edges), "violations_found": 0}
        )