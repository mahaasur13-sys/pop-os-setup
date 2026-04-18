"""Hard exceptions for Phase 3 strict execution system."""


class Phase3Error(Exception):
    """Base exception for all Phase 3 operations."""
    pass


class ValidationError(Phase3Error):
    """
    Raised when a repair plan fails validation gates.
    This is a HARD BLOCK — executor MUST NOT run.
    """
    def __init__(self, message: str, failed_gates: list[str] | None = None):
        super().__init__(message)
        self.failed_gates = failed_gates or []


class ExecutionBlockedError(Phase3Error):
    """
    Raised when executor is called without valid validation report.
    This is a CRITICAL failure — indicates contract violation.
    """
    pass


class RollbackError(Phase3Error):
    """
    Raised when rollback fails.
    System must crash explicitly — no silent recovery.
    """
    pass


class SnapshotError(Phase3Error):
    """
    Raised when snapshot cannot be computed or verified.
    This is a CRITICAL failure.
    """
    pass


class GateError(Phase3Error):
    """Raised when a specific gate check fails."""
    def __init__(self, gate_name: str, message: str, severity: str = "high"):
        super().__init__(f"[{gate_name}] {message}")
        self.gate_name = gate_name
        self.severity = severity


class DeterminismError(Phase3Error):
    """Raised when same input produces different output."""
    pass