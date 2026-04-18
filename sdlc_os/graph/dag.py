"""DAG-based dependency graph for SDLC OS."""

from __future__ import annotations
from typing import Optional
from collections import deque

from ..sdlc_types import Node, Edge, NodeType, DependencyType


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the DAG."""
    pass


class NodeNotFoundError(Exception):
    """Raised when a node is not found in the graph."""
    pass


class DAG:
    """
    Directed Acyclic Graph for repository dependency modeling.
    
    This is the canonical truth of system architecture.
    All repository structure is represented as nodes and edges.
    """

    def __init__(self):
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._adjacency: dict[str, set[str]] = {}
        self._reverse_adjacency: dict[str, set[str]] = {}

    def add_node(self, node: Node) -> None:
        """Add a node to the graph."""
        self._nodes[node.module_name] = node
        if node.module_name not in self._adjacency:
            self._adjacency[node.module_name] = set()
        if node.module_name not in self._reverse_adjacency:
            self._reverse_adjacency[node.module_name] = set()

    def add_edge(self, edge: Edge) -> None:
        """
        Add an edge to the graph.
        Raises CycleDetectedError if it would create a cycle.
        """
        if edge.from_node not in self._nodes:
            raise NodeNotFoundError(f"from_node '{edge.from_node}' not found")
        if edge.to_node not in self._nodes:
            raise NodeNotFoundError(f"to_node '{edge.to_node}' not found")

        # Check for cycle before adding
        if self._would_create_cycle(edge.from_node, edge.to_node):
            raise CycleDetectedError(
                f"Adding edge {edge.from_node} -> {edge.to_node} would create cycle"
            )

        self._edges.append(edge)
        self._adjacency[edge.from_node].add(edge.to_node)
        self._reverse_adjacency[edge.to_node].add(edge.from_node)

    def _would_create_cycle(self, from_node: str, to_node: str) -> bool:
        """
        Check if adding an edge would create a cycle.
        Uses BFS from to_node to see if we can reach from_node.
        """
        if from_node == to_node:
            return True

        visited = set()
        queue = deque([to_node])

        while queue:
            current = queue.popleft()
            if current == from_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._adjacency.get(current, []))

        return False

    def get_node(self, module_name: str) -> Optional[Node]:
        """Get a node by module name."""
        return self._nodes.get(module_name)

    def get_all_nodes(self) -> list[Node]:
        """Return all nodes in the graph."""
        return list(self._nodes.values())

    def get_all_edges(self) -> list[Edge]:
        """Return all edges in the graph."""
        return self._edges

    def get_dependencies(self, module_name: str) -> list[str]:
        """Get direct dependencies of a node (outgoing edges)."""
        return list(self._adjacency.get(module_name, set()))

    def get_dependents(self, module_name: str) -> list[str]:
        """Get direct dependents of a node (incoming edges)."""
        return list(self._reverse_adjacency.get(module_name, set()))

    def get_imports(self) -> list[tuple[str, str]]:
        """Return all import edges as (from, to) tuples."""
        return [(e.from_node, e.to_node) for e in self._edges]

    def topological_sort(self) -> list[str]:
        """
        Return nodes in topological order.
        Raises CycleDetectedError if cycle exists.
        """
        # Kahn's algorithm
        in_degree = {n: 0 for n in self._nodes}
        for edge in self._edges:
            in_degree[edge.to_node] += 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._nodes):
            raise CycleDetectedError("Cycle detected in graph")

        return result

    def detect_cycles(self) -> list[list[str]]:
        """
        Detect all cycles in the graph.
        Returns list of cycles (each cycle is a list of node names).
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

            path.pop()
            rec_stack.remove(node)
            return False

        for node in self._nodes:
            if node not in visited:
                dfs(node)

        return cycles

    def node_count(self) -> int:
        """Return number of nodes."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Return number of edges."""
        return len(self._edges)

    def to_dict(self) -> dict:
        """Serialize graph to dictionary."""
        return {
            'nodes': [n.to_dict() for n in self.get_all_nodes()],
            'edges': [e.to_dict() for e in self.get_all_edges()],
            'stats': {
                'node_count': self.node_count(),
                'edge_count': self.edge_count()
            }
        }


class DependencyMapper:
    """
    Maps raw repository structure to graph nodes and edges.
    Stateless - only produces node/edge lists.
    """

    def __init__(self):
        self._node_counter = 0

    def classify_file(self, file_path: str) -> NodeType:
        """
        Classify a file into a NodeType based on path patterns.
        """
        path_lower = file_path.lower()

        # Core application logic
        if any(p in path_lower for p in ['/core/', '/kernel/', '/engine/', '/runtime/']):
            return NodeType.CORE
        # Service layer
        elif any(p in path_lower for p in ['/service', '/agent', '/api/', '/handler']):
            return NodeType.SERVICE
        # Utility functions
        elif any(p in path_lower for p in ['/util', '/helper', '/tool', '/lib/']):
            return NodeType.UTILITY
        # Infrastructure
        elif any(p in path_lower for p in ['/infra', '/terraform', '/ansible', '/k8s', '/docker']):
            return NodeType.INFRA
        else:
            return NodeType.UNKNOWN

    def extract_module_name(self, file_path: str) -> str:
        """
        Extract module name from file path.
        Example: /home/workspace/project/core/engine.py -> core.engine
        """
        parts = file_path.strip('/').split('/')
        if len(parts) >= 2:
            # Skip repo root, take last 2 parts without extension
            name_parts = parts[-2:]
        else:
            name_parts = parts

        name = '.'.join(name_parts)
        return name.replace('.py', '').replace('.tf', '')

    def build_graph(self, file_list: list[dict]) -> tuple[list[Node], list[Edge]]:
        """
        Build nodes and edges from raw file list.
        
        Args:
            file_list: list of dicts with 'path', 'imports', 'line_count'
        
        Returns:
            (nodes, edges)
        """
        nodes = []
        edges = []
        node_names = set()

        for f in file_list:
            file_path = f['path']
            module_name = self.extract_module_name(file_path)
            node_type = self.classify_file(file_path)

            node = Node(
                module_name=module_name,
                file_path=file_path,
                node_type=node_type,
                line_count=f.get('line_count', 0),
                imports=f.get('imports', [])
            )
            nodes.append(node)
            node_names.add(module_name)

        # Build edges from import relationships
        for node in nodes:
            for imported in node.imports:
                imported_name = imported.replace('.', '/')
                # Try to match imported to existing nodes
                matched = False
                for target in nodes:
                    if imported in target.module_name or target.module_name in imported:
                        if target.module_name != node.module_name:
                            edges.append(Edge(
                                from_node=node.module_name,
                                to_node=target.module_name,
                                dependency_type=DependencyType.IMPORT
                            ))
                            matched = True
                            break
                # If no match, create edge to closest parent
                if not matched:
                    parts = node.module_name.split('.')
                    if len(parts) > 1:
                        parent = '.'.join(parts[:-1])
                        if parent in node_names:
                            edges.append(Edge(
                                from_node=node.module_name,
                                to_node=parent,
                                dependency_type=DependencyType.IMPORT
                            ))

        return nodes, edges