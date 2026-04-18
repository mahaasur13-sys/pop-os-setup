"""Gate engine — orchestrates all validation gates."""

from dataclasses import dataclass, field
from typing import Any

from phase3.exceptions import ValidationError
from phase3.validator.gates.base_gate import BaseGate, GateResult


@dataclass
class ValidationReport:
    """
    Immutable validation report from GateEngine.
    
    Attributes:
        passed: True if ALL gates passed.
        failed_gates: List of gate names that failed.
        details: Map of gate_name -> GateResult for all gates.
        risk_score: Float 0.0-1.0, computed from failed gates severity.
        timestamp: ISO timestamp of validation.
    """
    passed: bool
    failed_gates: list[str]
    details: dict[str, GateResult]
    risk_score: float = 0.0
    timestamp: str = ""
    
    def __post_init__(self):
        if self.risk_score < 0.0 or self.risk_score > 1.0:
            raise ValidationError(f"Invalid risk_score: {self.risk_score}")
    
    def raise_if_failed(self) -> None:
        """
        Raise ValidationError if validation failed.
        
        This is the HARD BLOCK mechanism — executor MUST check this.
        """
        if not self.passed:
            raise ValidationError(
                message=f"Validation failed for gates: {self.failed_gates}",
                failed_gates=self.failed_gates
            )


class GateEngine:
    """
    Orchestrates all validation gates and produces ValidationReport.
    
    Pipeline:
        validate(plan, snapshot) -> ValidationReport
            -> raise_if_failed() [if not passed]
                -> executor.execute(plan, report)
    """
    
    def __init__(self, gates: list[BaseGate] | None = None):
        self.gates: list[BaseGate] = gates or []
    
    def register_gate(self, gate: BaseGate) -> None:
        """Register a new gate (order matters for reporting)."""
        if any(g.name == gate.name for g in self.gates):
            raise ValueError(f"Gate with name '{gate.name}' already registered")
        self.gates.append(gate)
    
    def validate(self, plan: dict, snapshot: dict) -> ValidationReport:
        """
        Run all registered gates against the plan.
        
        Args:
            plan: Repair plan dict (must have 'actions' key).
            snapshot: Current system state snapshot dict.
            
        Returns:
            ValidationReport with aggregate results from all gates.
            
        Raises:
            ValidationError: If no gates registered or snapshot invalid.
        """
        if not self.gates:
            raise ValidationError("No gates registered — validation cannot proceed")
        
        if not isinstance(plan, dict) or "actions" not in plan:
            raise ValidationError("Plan must be a dict with 'actions' key")
        
        if not isinstance(snapshot, dict):
            raise ValidationError("Snapshot must be a dict")
        
        results: dict[str, GateResult] = {}
        failed_gates: list[str] = []
        total_severity_weight = 0.0
        
        for gate in self.gates:
            result = gate.check(plan, snapshot)
            results[gate.name] = result
            
            if not result.passed:
                failed_gates.append(gate.name)
                # Severity weight: high=1.0, medium=0.5, low=0.1
                weight = {"high": 1.0, "medium": 0.5, "low": 0.1}.get(result.severity, 0.1)
                total_severity_weight += weight
        
        # risk_score = normalized sum of failed gate severities
        max_possible_weight = len(self.gates) * 1.0
        risk_score = min(total_severity_weight / max_possible_weight, 1.0) if max_possible_weight > 0 else 0.0
        
        return ValidationReport(
            passed=len(failed_gates) == 0,
            failed_gates=failed_gates,
            details=results,
            risk_score=risk_score,
            timestamp=self._now()
        )
    
    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()