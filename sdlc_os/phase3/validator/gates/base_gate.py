"""Base gate contract for Phase 3 validation system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateResult:
    """
    Immutable result of a single gate check.
    
    Attributes:
        passed: True if gate passed, False if failed.
        reason: Human-readable explanation of the check result.
        severity: "low", "medium", or "high" — only meaningful when passed=False.
        details: Optional additional data about the gate check.
    """
    passed: bool
    reason: str
    severity: str = "low"
    details: dict = field(default_factory=dict)
    
    def __post_init__(self):
        if self.severity not in ("low", "medium", "high"):
            raise ValueError(f"Invalid severity: {self.severity}")


class BaseGate(ABC):
    """
    Abstract base class for all validation gates.
    
    IMPORTANT: Gates MUST NOT have side effects.
    Each gate is a pure function of (plan, snapshot) -> GateResult.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this gate."""
        pass
    
    @abstractmethod
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Perform the gate check.
        
        Args:
            plan: The repair plan to validate.
            snapshot: Current system state snapshot.
            
        Returns:
            GateResult with passed=True if check passed, False otherwise.
            
        Raises:
            No exceptions — all errors must be captured in GateResult.
        """
        pass
    
    def _fail(self, reason: str, severity: str = "high", details: dict = None) -> GateResult:
        """Helper to create a failing GateResult."""
        return GateResult(
            passed=False,
            reason=reason,
            severity=severity,
            details=details or {}
        )
    
    def _pass(self, reason: str = "ok", details: dict = None) -> GateResult:
        """Helper to create a passing GateResult."""
        return GateResult(
            passed=True,
            reason=reason,
            severity="low",
            details=details or {}
        )