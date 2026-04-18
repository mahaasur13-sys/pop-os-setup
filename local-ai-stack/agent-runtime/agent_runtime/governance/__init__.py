"""
Governance Layer — ATOMFederationOS v7.

Execution Governance Layer sits between:
    Planning Output (ExecutionManifest) → Execution Runtime

Components:
    policy_engine    — semantic policy decision (ALLOW / DENY / DEGRADED_ALLOW)
    plan_validator   — static DAG structure validation
    execution_guard  — runtime enforcement (timeouts, budgets, kill switch)
    gateway          — unified facade: manifest → governance check → execution
    drift_detector   — post-execution: planned vs actual drift analysis

Architectural invariant (v7):
    planning → governance → execution → event_store
    Governance rejection != runtime failure (pre-flight, not in-flight)
"""

from .gateway import GovernanceGateway, GovernanceDecision, RejectedExecution, GovernanceStatus
from .policy_engine import (
    PolicyEngine, PolicyDecision, PolicyViolation, PolicyContext,
    Verdict, ViolationSeverity,
)
from .plan_validator import PlanValidator, PlanValidationResult, ValidationStatus
from .execution_guard import ExecutionGuard, GuardedStep, GuardMetrics, GuardStatus, GuardConfig
from .drift_detector import DriftDetector, DriftReport

__all__ = [
    # gateway
    "GovernanceGateway",
    "GovernanceDecision",
    "RejectedExecution",
    # policy
    "PolicyEngine",
    "PolicyDecision",
    "PolicyViolation",
    "PolicyContext",
    "Verdict",
    "ViolationSeverity",
    # validator
    "PlanValidator",
    "PlanValidationResult",
    "ValidationStatus",
    # guard
    "ExecutionGuard",
    "GuardedStep",
    "GuardMetrics",
    "GuardStatus",
    "GuardConfig",
    # drift
    "DriftDetector",
    "DriftReport",
]
