"""
DRL v1 — PartitionModel: Network partition simulator.
Models split-brain, asymmetric connectivity, cluster fragmentation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Set, List
import threading
import random


@dataclass
class PartitionConfig:
    """Configuration for PartitionModel behavior."""
    enabled: bool = False          # Global kill-switch
    seed: int | None = None        # Random seed for determinism
    # Asymmetric connectivity: node_id -> set of reachable nodes
    asymmetric_rules: Dict[str, Set[str]] = field(default_factory=dict)
    # Global partition groups (mutually isolated sets)
    partition_groups: List[Set[str]] = field(default_factory=list)


class PartitionModel:
    """
    Simulates network partitions.

    can_communicate(a, b) returns False when:
      1. Global `enabled` is False  →  always True (no partition)
      2. Nodes are in different partition_groups
      3. Asymmetric rule blocks one direction

    Thread-safe.
    """

    def __init__(self, config: PartitionConfig | None = None):
        self._config = config or PartitionConfig()
        self._lock = threading.Lock()
        if self._config.seed is not None:
            random.seed(self._config.seed)

    # ── Core query ────────────────────────────────────────────────────────────

    def can_communicate(self, node_a: str, node_b: str) -> bool:
        """
        Returns True if node_a can send to node_b under current partition state.
        False = message should be blocked by DRL transport layer.
        """
        with self._lock:
            if not self._config.enabled:
                return True

            # Check partition groups
            if self._config.partition_groups:
                group_of_a = self._find_group(node_a)
                group_of_b = self._find_group(node_b)
                if group_of_a != group_of_b:
                    return False  # Different partition groups = isolated

            # Check asymmetric rules
            allowed = self._config.asymmetric_rules.get(node_a, None)
            if allowed is not None and node_b not in allowed:
                return False  # node_a cannot reach node_b by rule

            return True

    def _find_group(self, node: str) -> int | None:
        """Return partition group index, or None if ungrouped."""
        for idx, group in enumerate(self._config.partition_groups):
            if node in group:
                return idx
        return None

    # ── Dynamic partition injection ───────────────────────────────────────────

    def apply_partition(self, group_a: Set[str], group_b: Set[str]) -> bool:
        """
        Isolate group_a from group_b.
        Messages crossing the boundary will be blocked.
        """
        with self._lock:
            self._config.partition_groups.append(group_a)
            self._config.partition_groups.append(group_b)
            self._config.enabled = True
        return True

    def apply_split_50_50(self, all_nodes: List[str]) -> bool:
        """Split cluster exactly 50/50."""
        mid = len(all_nodes) // 2
        group_a = set(all_nodes[:mid])
        group_b = set(all_nodes[mid:])
        return self.apply_partition(group_a, group_b)

    def apply_asymmetric(self, from_node: str, to_node: str) -> bool:
        """Make from_node unable to reach to_node (but reverse is allowed)."""
        with self._lock:
            if from_node not in self._config.asymmetric_rules:
                self._config.asymmetric_rules[from_node] = set()
            # Remove from reachable set
            self._config.asymmetric_rules[from_node].discard(to_node)
            self._config.enabled = True
        return True

    def heal_partition(self) -> bool:
        """Remove all partition groups and asymmetric rules."""
        with self._lock:
            self._config.partition_groups.clear()
            self._config.asymmetric_rules.clear()
            self._config.enabled = False
        return True

    # ── Status ────────────────────────────────────────────────────────────────

    def is_partitioned(self) -> bool:
        with self._lock:
            return self._config.enabled and bool(self._config.partition_groups)

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._config.enabled,
                "partition_groups": [list(g) for g in self._config.partition_groups],
                "asymmetric_rules": {
                    k: list(v) for k, v in self._config.asymmetric_rules.items()
                },
            }
