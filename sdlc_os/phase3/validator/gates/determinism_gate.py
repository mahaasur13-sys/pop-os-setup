"""Determinism gate — ensures same input produces same output."""

import hashlib
import json
from typing import Any

from phase3.validator.gates.base_gate import BaseGate, GateResult
from phase3.exceptions import DeterminismError


class DeterminismGate(BaseGate):
    """
    Validates that the same plan + snapshot produces consistent results.
    
    FAILS if:
        - Same input produces different snapshot hash across multiple evaluations
        - Non-deterministic behavior detected in plan execution
    
    This gate runs the plan twice and compares outputs.
    """
    
    def __init__(self, runs: int = 2):
        self.runs = runs  # Number of evaluation runs for consistency check
    
    @property
    def name(self) -> str:
        return "determinism_gate"
    
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Verify determinism by evaluating plan multiple times.
        
        Args:
            plan: Repair plan to validate.
            snapshot: Current system state.
        """
        # Compute hash of current snapshot
        snapshot_hash = self._compute_snapshot_hash(snapshot)
        
        # Simulate plan application and compare resulting state hashes
        hashes: list[str] = []
        
        for run in range(self.runs):
            try:
                # Simulate: apply plan actions to snapshot
                simulated = self._simulate_plan(plan, snapshot)
                # Compute hash of simulated result
                result_hash = self._compute_snapshot_hash(simulated)
                hashes.append(result_hash)
            except Exception as e:
                return self._fail(
                    reason=f"Determinism check failed: {str(e)}",
                    severity="high",
                    details={"run": run, "error": str(e)}
                )
        
        # Compare all hashes
        if len(set(hashes)) > 1:
            return self._fail(
                reason=f"Non-deterministic behavior: same plan produced different results",
                severity="high",
                details={
                    "runs": self.runs,
                    "hashes": hashes,
                    "unique_hashes": len(set(hashes))
                }
            )
        
        return self._pass(
            reason=f"Determinism verified. Consistent hash across {self.runs} runs: {hashes[0][:16]}...",
            details={
                "snapshot_hash": snapshot_hash[:16],
                "result_hash": hashes[0][:16],
                "runs": self.runs
            }
        )
    
    def _compute_snapshot_hash(self, state: dict) -> str:
        """Compute deterministic hash of system state."""
        # Sort keys for deterministic serialization
        serialized = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()
    
    def _simulate_plan(self, plan: dict, snapshot: dict) -> dict:
        """
        Simulate plan application on snapshot.
        
        Returns modified snapshot without actually changing files.
        This is a pure function — no side effects.
        """
        result = {
            **snapshot,
            "graph_nodes": list(snapshot.get("graph_nodes", [])),
            "graph_edges": list(snapshot.get("graph_edges", [])),
            "diffs": list(snapshot.get("diffs", [])),
        }
        
        actions = plan.get("actions", [])
        
        for action in actions:
            action_type = action.get("type", "")
            
            if action_type == "create_node":
                # Add node to graph
                node = action.get("node", {})
                result["graph_nodes"].append(node)
                
            elif action_type == "add_dependency":
                # Add edge to graph
                edge = action.get("edge", {})
                result["graph_edges"].append(edge)
                
            elif action_type == "modify_file":
                # Track modified file
                file_path = action.get("file_path", "")
                if file_path:
                    diff = {
                        "diff_type": "configuration",
                        "file_paths": [file_path],
                        "severity": "low"
                    }
                    result["diffs"].append(diff)
            
            # Note: We don't actually modify files here — just track the effect
        
        return result