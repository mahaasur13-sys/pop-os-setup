"""
GovernanceGateway — unified entry point for the Execution Governance Layer.

Facade that orchestrates:
    ExecutionManifest
        → PolicyEngine.evaluate()     (semantic policy check)
        → PlanValidator.validate()     (structural DAG check)
        → ExecutionGuard.wrap()        (runtime enforcement)
        → engine.execute()             (actual execution)

Returns GovernanceDecision: EXECUTED, REJECTED, or DEGRADED.

Architecture:
    planning → gateway → governance pipeline → engine → event_store
                    ↓
            REJECTED here means never reached engine
            (pre-flight rejection, not in-flight failure)

Usage::

    gateway = GovernanceGateway()
    decision = await gateway.evaluate(manifest, context)

    if decision.status == GovernanceStatus.EXECUTED:
        await decision.execution_result  # await engine result
    elif decision.status == GovernanceStatus.REJECTED:
        log.warning(f"Rejected: {decision.reason}")
    elif decision.status == GovernanceStatus.DEGRADED:
        await decision.execution_result  # runs with reduced budget
"""

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Awaitable

from .policy_engine import PolicyEngine, PolicyContext, PolicyDecision, Verdict
from .plan_validator import PlanValidator, PlanValidationResult, ValidationStatus
from .execution_guard import ExecutionGuard, GuardConfig, GuardMetrics
from .drift_detector import DriftDetector, DriftReport


# ── Enums ─────────────────────────────────────────────────────────────────────

class GovernanceStatus(str, Enum):
    EXECUTED = "executed"       # passed all gates, executed
    REJECTED = "rejected"       # blocked by policy or validator
    DEGRADED = "degraded"       # allowed with warnings, executed with reduced budget
    VALIDATION_FAILED = "validation_failed"  # structural failure
    POLICY_DENIED = "policy_denied"  # policy engine blocked


# ── GovernanceDecision ─────────────────────────────────────────────────────────

@dataclass
class GovernanceDecision:
    status: GovernanceStatus
    reason: str
    policy_decision: Optional[PolicyDecision] = None
    validation_result: Optional[PlanValidationResult] = None
    guard_metrics: Optional[GuardMetrics] = None
    drift_report: Optional[DriftReport] = None
    execution_result: Optional[Any] = None
    latency_ms: float = 0.0
    evaluated_at: float = field(default_factory=time.monotonic)

    @property
    def is_allowed(self) -> bool:
        return self.status in (
            GovernanceStatus.EXECUTED,
            GovernanceStatus.DEGRADED,
        )

    @property
    def was_executed(self) -> bool:
        return self.execution_result is not None

    def summary(self) -> str:
        lines = [
            f"[{self.status.value.upper()}] {self.reason}",
            f"  latency_ms={self.latency_ms:.1f}",
        ]
        if self.policy_decision:
            lines.append(f"  policy_verdict={self.policy_decision.verdict.value}")
        if self.validation_result:
            lines.append(f"  validation_status={self.validation_result.status.value}")
        if self.guard_metrics:
            m = self.guard_metrics
            lines.append(
                f"  guard: {m.steps_completed}/{m.steps_total} steps, "
                f"failed={m.steps_failed}, timeouts={m.timeouts}, kills={m.kills}"
            )
        if self.drift_report:
            lines.append(f"  drift_score={self.drift_report.drift_score:.3f}")
        return "\n".join(lines)


class RejectedExecution(Exception):
    """Raised when execution is rejected by governance gate."""

    def __init__(self, decision: GovernanceDecision):
        self.decision = decision
        super().__init__(f"Governance rejection: {decision.reason}")


# ── Gateway ───────────────────────────────────────────────────────────────────

class GovernanceGateway:
    """
    Unified governance facade.

    Integrates PolicyEngine, PlanValidator, ExecutionGuard, and DriftDetector
    into a single evaluate() call.

    Configuration knobs:
      - policy_engine: PolicyEngine instance (or new with defaults)
      - plan_validator: PlanValidator instance
      - execution_guard: ExecutionGuard instance
      - drift_detector: DriftDetector instance (optional, for post-exec analysis)
      - raise_on_reject: if True, raises RejectedExecution on DENY
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        plan_validator: Optional[PlanValidator] = None,
        execution_guard: Optional[ExecutionGuard] = None,
        drift_detector: Optional[DriftDetector] = None,
        raise_on_reject: bool = False,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.plan_validator = plan_validator or PlanValidator()
        self.execution_guard = execution_guard or ExecutionGuard()
        self.drift_detector = drift_detector
        self.raise_on_reject = raise_on_reject

    async def evaluate(
        self,
        manifest,                   # ExecutionManifest
        ctx: Optional[PolicyContext] = None,
        engine_call_fn: Optional[Callable[..., Awaitable[Any]]] = None,
        planned_events: Optional[list] = None,   # for drift detection
    ) -> GovernanceDecision:
        """
        Full governance pipeline.

        Steps:
          1. PolicyEngine.evaluate() — semantic policy
          2. PlanValidator.validate() — structural validation
          3. ExecutionGuard.wrap_execute() — runtime enforcement
          4. (optional) DriftDetector.report() — post-execution analysis

        Parameters:
          manifest: ExecutionManifest from plan_executor
          ctx: PolicyContext (caller identity, environment, etc.)
          engine_call_fn: async function to execute (e.g. engine.execute_manifest)
          planned_events: list of events as predicted by planner (for drift detection)
        """
        start = time.monotonic()
        ctx = ctx or PolicyContext()

        # ── STEP 1: Policy Engine ──────────────────────────────────────────────
        policy_decision = self.policy_engine.evaluate(manifest, ctx)

        if policy_decision.verdict == Verdict.DENY:
            return self._build_rejected(
                GovernanceStatus.POLICY_DENIED,
                f"PolicyEngine DENY: {policy_decision.reason}",
                policy_decision=policy_decision,
                latency_ms=time.monotonic() - start,
            )

        # ── STEP 2: Plan Validator ─────────────────────────────────────────────
        validation_result = self.plan_validator.validate(manifest)

        if validation_result.status == ValidationStatus.FAIL:
            return self._build_rejected(
                GovernanceStatus.VALIDATION_FAILED,
                f"PlanValidator FAIL: {[i.message for i in validation_result.issues if i.is_fail()]}",
                policy_decision=policy_decision,
                validation_result=validation_result,
                latency_ms=time.monotonic() - start,
            )

        # ── STEP 3: Execution Guard + Engine ───────────────────────────────────
        guard_metrics = None
        execution_result = None
        adjusted_budget_ms = (
            policy_decision.adjusted_budget.max_latency_ms
            if policy_decision.adjusted_budget
            else 300_000.0
        )
        adjusted_budget_cost = (
            policy_decision.adjusted_budget.max_cost
            if policy_decision.adjusted_budget
            else 100.0
        )

        if engine_call_fn is not None:
            guard_metrics = await self.execution_guard.execute_manifest(
                manifest,
                adjusted_budget_ms=adjusted_budget_ms,
                adjusted_budget_cost=adjusted_budget_cost,
                call_fn=engine_call_fn,
            )
            execution_result = guard_metrics

        # ── STEP 4: Drift Detection (post-execution) ─────────────────────────────
        drift_report = None
        if self.drift_detector and planned_events:
            drift_report = await self.drift_detector.report(
                planned_events=planned_events,
                actual_events=None,   # fill from event_store after execution
                manifest=manifest,
            )

        # ── Final status ───────────────────────────────────────────────────────
        if policy_decision.verdict == Verdict.DEGRADED_ALLOW:
            status = GovernanceStatus.DEGRADED
            reason = f"DEGRADED_ALLOW: {policy_decision.reason}"
        else:
            status = GovernanceStatus.EXECUTED
            reason = f"EXECUTED: {policy_decision.reason}"

        return GovernanceDecision(
            status=status,
            reason=reason,
            policy_decision=policy_decision,
            validation_result=validation_result,
            guard_metrics=guard_metrics,
            drift_report=drift_report,
            execution_result=execution_result,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ── sync variant ─────────────────────────────────────────────────────────

    def evaluate_sync(
        self,
        manifest,
        ctx: Optional[PolicyContext] = None,
    ) -> GovernanceDecision:
        """
        Synchronous governance evaluation (policy + validation only).
        Skips execution — useful for pre-flight checks without running engine.
        """
        start = time.monotonic()
        ctx = ctx or PolicyContext()

        policy_decision = self.policy_engine.evaluate(manifest, ctx)
        if policy_decision.verdict == Verdict.DENY:
            return self._build_rejected(
                GovernanceStatus.POLICY_DENIED,
                f"PolicyEngine DENY: {policy_decision.reason}",
                policy_decision=policy_decision,
                latency_ms=(time.monotonic() - start) * 1000,
            )

        validation_result = self.plan_validator.validate(manifest)
        if validation_result.status == ValidationStatus.FAIL:
            return self._build_rejected(
                GovernanceStatus.VALIDATION_FAILED,
                f"PlanValidator FAIL: {[i.message for i in validation_result.issues if i.is_fail()]}",
                policy_decision=policy_decision,
                validation_result=validation_result,
                latency_ms=(time.monotonic() - start) * 1000,
            )

        status = GovernanceStatus.DEGRADED if policy_decision.verdict == Verdict.DEGRADED_ALLOW else GovernanceStatus.EXECUTED

        return GovernanceDecision(
            status=status,
            reason=f"[PRE-FLIGHT] {policy_decision.reason}",
            policy_decision=policy_decision,
            validation_result=validation_result,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_rejected(
        self,
        status: GovernanceStatus,
        reason: str,
        **kwargs,
    ) -> GovernanceDecision:
        decision = GovernanceDecision(status=status, reason=reason, **kwargs)
        if self.raise_on_reject:
            raise RejectedExecution(decision)
        return decision
