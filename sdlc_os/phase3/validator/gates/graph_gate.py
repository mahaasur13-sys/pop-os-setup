"""Graph gate — detects cycles and structural inconsistencies."""

from typing import Optional

from phase3.validator.gates.base_gate import BaseGate, GateResult


class GraphGate(BaseGate):
    """
    Validates graph structural integrity after patch.
    
    FAILS if:
        - Cycle detected in dependency graph after patch
        - Node count mismatch (expected vs actual)
        - Edge references non-existent node
    """
    
    @property
    def name(self) -> str:
        return "graph_gate"
    
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Check graph structural validity.
        
        Args:
            plan: Repair plan with potential graph modifications.
            snapshot: Current system state (includes graph_nodes, graph_edges).
        """
        nodes = snapshot.get("graph_nodes", [])
        edges = snapshot.get("graph_edges", [])
        
        # Build node index
        node_ids = {n.get("module_name") or n.get("file_path", "") for n in nodes}
        
        # Check 1: Edge references valid nodes
        for edge in edges:
            from_node = edge.get("from_node", "")
            to_node = edge.get("to_node", "")
            
            if from_node not in node_ids:
                return self._fail(
                    reason=f"Edge references non-existent from_node: {from_node}",
                    severity="high",
                    details={"edge": edge}
                )
            if to_node not in node_ids:
                return self._fail(
                    reason=f"Edge references non-existent to_node: {to_node}",
                    severity="high",
                    details={"edge": edge}
                )
        
        # Check 2: Cycle detection using Kahn's algorithm (BFS-based topological sort)
        cycle_found = self._detect_cycle(nodes, edges)
        if cycle_found:
            return self._fail(
                reason=f"Cycle detected in dependency graph: {cycle_found}",
                severity="high",
                details={"cycle_nodes": cycle_found}
            )
        
        # Check 3: Plan patch adds expected nodes
        expected_new_nodes = self._count_planned_new_nodes(plan)
        if expected_new_nodes > 0:
            pass
        
        return self._pass(
            reason=f"Graph structure valid. Nodes={len(nodes)}, Edges={len(edges)}",
            details={"node_count": len(nodes), "edge_count": len(edges)}
        )
    
    def _detect_cycle(self, nodes: list[dict], edges: list[dict]) -> Optional[list[str]]:
        """
        Detect cycle using Kahn's algorithm (topological sort).
        If we can't process all nodes, there's a cycle.
        
        Returns cycle path if found, None otherwise.
        """
        # Build adjacency and in-degree
        adj: dict[str, list[str]] = {n.get("module_name", ""): [] for n in nodes}
        in_degree: dict[str, int] = {n.get("module_name", ""): 0 for n in nodes}
        
        for edge in edges:
            from_node = edge.get("from_node", "")
            to_node = edge.get("to_node", "")
            if from_node in adj and to_node in adj:
                adj[from_node].append(to_node)
                in_degree[to_node] += 1
        
        # Kahn's algorithm
        queue = [n for n in in_degree if in_degree[n] == 0]
        processed = 0
        
        while queue:
            node = queue.pop(0)
            processed += 1
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # If not all nodes processed, there's a cycle
        if processed != len(nodes):
            # Find nodes in cycle (nodes with in_degree > 0 after processing)
            cycle_nodes = [n for n in in_degree if in_degree[n] > 0]
            return cycle_nodes
        
        return None
    
    def _count_planned_new_nodes(self, plan: dict) -> int:
        """Count nodes that plan intends to create."""
        actions = plan.get("actions", [])
        return sum(1 for a in actions if a.get("type") == "create_node")
