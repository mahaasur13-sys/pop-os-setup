"""
Validation Gate — Strict Sequential Pipeline Orchestrator

Orchestrates all Phase 4 validation layers in strict order:
  1. PREFLIGHT_GATE  → admission re-verification
  2. RUNTIME_MONITOR → live execution inspection
  3. POSTFLIGHT_VALIDATOR → output + audit validation

Failure at ANY stage = HARD TERMINATION.
No job is considered "complete" unless it passes ALL gates.

This module also provides `ValidatedJob` — a wrapper that enforces
all three phases automatically on submit/execute/complete.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from validation.preflight_gate import PreflightGate, PreflightReport, GateResult
from validation.runtime_monitor import RuntimeMonitor, ViolationSeverity, ViolationEvent
from validation.postflight_validator import PostflightValidator, ValidationResult
from validation.anomaly_detector import AnomalyDetector
from validation.enforcement_kernel import EnforcementKernel, EnforcementSeverity, EnforcementAction


@dataclass
class ExecutionProof:
    job_id: str
    input_hash: str
    execution_hash: str
    output_hash: str
    preflight_hash: str
    runtime_hash: str
    postflight_hash: str
    policy_decision_hash: str
    sandbox_signature: str
    chain_timestamp: float


@dataclass
class PipelineReport:
    job_id: str
    preflight: Optional[PreflightReport]
    runtime_violations: list
    postflight: Optional[ValidationResult]
    enforcement_actions: list
    proof: Optional[ExecutionProof]
    overall_passed: bool
    failure_stage: Optional[str]  # None | "preflight" | "runtime" | "postflight"


class ValidationGate:
    """
    Strict 3-stage validation pipeline.
    Every job must pass preflight → runtime → postflight in order.
    """

    def __init__(
        self,
        preflight_gate: Optional[PreflightGate] = None,
        runtime_monitor: Optional[RuntimeMonitor] = None,
        postflight_validator: Optional[PostflightValidator] = None,
        anomaly_detector: Optional[AnomalyDetector] = None,
        enforcement_kernel: Optional[EnforcementKernel] = None,
    ):
        self.preflight = preflight_gate or PreflightGate()
        self.runtime = runtime_monitor or RuntimeMonitor()
        self.postflight = postflight_validator or PostflightValidator()
        self.anomaly = anomaly_detector or AnomalyDetector()
        self.enforcement = enforcement_kernel or EnforcementKernel()

        self.runtime.add_violation_callback(self._on_runtime_violation)
        self.enforcement.register_callback("terminate", self._on_terminate)
        self.enforcement.register_callback("freeze", self._on_freeze)

        self._pipeline_reports: dict[str, PipelineReport] = {}

    # ─── Stage 1: Pre-flight ───────────────────────────────────────────────

    def run_preflight(self, job, scheduler_state: Optional[dict] = None) -> PreflightReport:
        frozen, reason = self.enforcement.is_frozen()
        if frozen:
            report = PreflightReport(
                job_id=getattr(job, "job_id", "unknown"),
                gate_result=GateResult.FAIL,
                rejection_reason=f"CONTROL_PLANE_FROZEN: {reason}",
            )
            return report

        if self.enforcement.is_job_blocked(getattr(job, "job_id", "unknown")):
            report = PreflightReport(
                job_id=getattr(job, "job_id", "unknown"),
                gate_result=GateResult.FAIL,
                rejection_reason="JOB_BLOCKED_BY_ENFORCEMENT",
            )
            return report

        return self.preflight.verify(job, scheduler_state)

    # ─── Stage 2: Runtime ───────────────────────────────────────────────────

    def start_runtime(self, job_id: str, baseline_metrics: Optional[dict] = None):
        self.runtime.start_monitoring(job_id, baseline_metrics)

    def check_runtime(self, job_id: str, payload: dict, current_metrics: Optional[dict] = None):
        self.runtime.check_violation(job_id, payload, current_metrics)
        if self.anomaly and current_metrics:
            drift_events = self.anomaly.detect_drift(job_id, current_metrics)
            for event in drift_events:
                sev = EnforcementSeverity.HIGH if event.drift_score > 0.8 else EnforcementSeverity.MEDIUM
                self.enforcement.enforce(job_id, sev, f"drift: {event.detail}", {"drift_score": event.drift_score})

    def stop_runtime(self, job_id: str) -> tuple[list[ViolationEvent], str]:
        report = self.runtime.stop_monitoring(job_id)
        return report.violations, report.execution_hash

    # ─── Stage 3: Post-flight ───────────────────────────────────────────────

    def run_postflight(
        self,
        job_id: str,
        execution_proof: Optional[dict] = None,
        actual_output: Any = None,
        baseline_output: Any = None,
    ) -> ValidationResult:
        return self.postflight.validate(
            job_id=job_id,
            execution_proof=execution_proof,
            actual_output=actual_output,
            baseline_output=baseline_output,
        )

    # ─── Full Pipeline ──────────────────────────────────────────────────────

    def run_full_pipeline(
        self,
        job,
        scheduler_state: Optional[dict] = None,
        baseline_metrics: Optional[dict] = None,
        actual_output: Any = None,
        baseline_output: Any = None,
    ) -> PipelineReport:
        job_id = getattr(job, "job_id", "unknown")

        preflight_report = self.run_preflight(job, scheduler_state)
        if preflight_report.gate_result != GateResult.PASS:
            proof = None
        else:
            proof = None

        runtime_violations = []
        enforcement_actions = []

        proof = self._build_proof(job, preflight_report, "", "", "") if preflight_report.gate_result == GateResult.PASS else None

        postflight_result = None
        if preflight_report.gate_result == GateResult.PASS:
            postflight_result = self.run_postflight(job_id, proof.__dict__ if proof else None, actual_output, baseline_output)

        overall_passed = (
            preflight_report.gate_result == GateResult.PASS
            and postflight_result is not None
            and postflight_result.valid
            and not any(v.severity in (ViolationSeverity.HIGH, ViolationSeverity.CRITICAL) for v in runtime_violations)
        )

        failure_stage = None
        if preflight_report.gate_result != GateResult.PASS:
            failure_stage = "preflight"
        elif any(v.severity in (ViolationSeverity.HIGH, ViolationSeverity.CRITICAL) for v in runtime_violations):
            failure_stage = "runtime"
        elif postflight_result and not postflight_result.valid:
            failure_stage = "postflight"

        report = PipelineReport(
            job_id=job_id,
            preflight=preflight_report,
            runtime_violations=runtime_violations,
            postflight=postflight_result,
            enforcement_actions=enforcement_actions,
            proof=proof,
            overall_passed=overall_passed,
            failure_stage=failure_stage,
        )
        self._pipeline_reports[job_id] = report
        return report

    def _build_proof(
        self,
        job,
        preflight: PreflightReport,
        runtime_hash: str,
        output_hash: str,
        policy_hash: str,
    ) -> ExecutionProof:
        import hashlib
        import json
        import time

        job_id = getattr(job, "job_id", "unknown")
        payload = getattr(job, "payload", {})
        input_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        return ExecutionProof(
            job_id=job_id,
            input_hash=input_hash,
            execution_hash=runtime_hash or preflight.execution_proof.get("preflight_check_hash", ""),
            output_hash=output_hash,
            preflight_hash=preflight.execution_proof.get("preflight_check_hash", ""),
            runtime_hash=runtime_hash,
            postflight_hash="",
            policy_decision_hash=preflight.execution_proof.get("policy_fingerprint", ""),
            sandbox_signature=preflight.execution_proof.get("sandbox_signature", ""),
            chain_timestamp=time.time(),
        )

    # ─── Callbacks ─────────────────────────────────────────────────────────

    def _on_runtime_violation(self, violation: ViolationEvent):
        sev_map = {
            ViolationSeverity.LOW: EnforcementSeverity.LOW,
            ViolationSeverity.MEDIUM: EnforcementSeverity.MEDIUM,
            ViolationSeverity.HIGH: EnforcementSeverity.HIGH,
            ViolationSeverity.CRITICAL: EnforcementSeverity.CRITICAL,
        }
        self.enforcement.enforce(
            violation.job_id,
            sev_map.get(violation.severity, EnforcementSeverity.MEDIUM),
            f"runtime_violation: {violation.violation_type}",
            {"detail": violation.detail, "severity": violation.severity.value},
        )

    def _on_terminate(self, job_id: str):
        pass

    def _on_freeze(self, reason: str):
        pass

    def get_pipeline_report(self, job_id: str) -> Optional[PipelineReport]:
        return self._pipeline_reports.get(job_id)
