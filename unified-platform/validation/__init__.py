"""
Phase 4 — Execution Guarantee / Validation Layer

Modules:
- preflight_gate      → admission re-verification
- runtime_monitor     → live execution inspection
- postflight_validator → output + audit validation
- anomaly_detector    → behavioral drift detection
- enforcement_kernel  → kill-switch + rollback trigger
- validation_gate     → strict sequential pipeline orchestrator
"""

from validation.preflight_gate import PreflightGate, PreflightReport, GateResult
from validation.runtime_monitor import (
    RuntimeMonitor,
    RuntimeReport,
    ViolationEvent,
    ViolationSeverity,
)
from validation.postflight_validator import PostflightValidator, ValidationResult
from validation.anomaly_detector import AnomalyDetector, DriftEvent, DriftType
from validation.enforcement_kernel import (
    EnforcementKernel,
    EnforcementAction,
    EnforcementSeverity,
)
from validation.validation_gate import ValidationGate, PipelineReport, ExecutionProof

__all__ = [
    # Preflight
    "PreflightGate",
    "PreflightReport",
    "GateResult",
    # Runtime
    "RuntimeMonitor",
    "RuntimeReport",
    "ViolationEvent",
    "ViolationSeverity",
    # Postflight
    "PostflightValidator",
    "ValidationResult",
    # Anomaly
    "AnomalyDetector",
    "DriftEvent",
    "DriftType",
    # Enforcement
    "EnforcementKernel",
    "EnforcementAction",
    "EnforcementSeverity",
    # Pipeline
    "ValidationGate",
    "PipelineReport",
    "ExecutionProof",
]
