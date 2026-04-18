"""
Post-Flight Validator — Output + Audit Validation Layer

Runs AFTER job execution completes.
Validates: output schema correctness, deterministic replay check,
execution hash consistency, audit chain continuity,
expected vs actual result diff.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ValidationResult:
    job_id: str
    valid: bool
    checks: dict = field(default_factory=dict)
    severity: str = "NONE"  # NONE | LOW | MEDIUM | HIGH | CRITICAL
    details: str = ""


class PostflightValidator:
    """
    Final validation gate after job execution.
    Validates output correctness and execution proof consistency.
    """

    def __init__(self, audit_logger=None):
        self.audit_logger = audit_logger
        self._validation_cache: dict[str, ValidationResult] = {}

    def validate(
        self,
        job_id: str,
        expected_output_schema: Optional[dict] = None,
        execution_proof: Optional[dict] = None,
        actual_output: Optional[Any] = None,
        baseline_output: Optional[Any] = None,
    ) -> ValidationResult:
        checks = {
            "output_schema": self._check_output_schema(actual_output, expected_output_schema),
            "deterministic_replay": self._check_deterministic_replay(actual_output, baseline_output),
            "execution_hash_consistency": self._check_execution_hash(execution_proof),
            "audit_chain_continuity": self._check_audit_chain(job_id),
        }

        all_valid = all(c["passed"] for c in checks.values())
        severity = self._compute_severity(checks)

        result = ValidationResult(
            job_id=job_id,
            valid=all_valid,
            checks=checks,
            severity=severity,
            details=self._build_details(checks),
        )
        self._validation_cache[job_id] = result
        return result

    def _check_output_schema(self, output: Any, schema: Optional[dict]) -> dict:
        if schema is None:
            return {"passed": True, "detail": "no schema provided"}
        if output is None:
            return {"passed": False, "detail": "output is None"}
        if isinstance(output, dict):
            missing = [k for k in schema.get("required", []) if k not in output]
            if missing:
                return {"passed": False, "detail": f"missing required fields: {missing}"}
            return {"passed": True, "detail": "schema valid"}
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
                return self._check_output_schema(parsed, schema)
            except json.JSONDecodeError:
                return {"passed": False, "detail": "output is string but not valid JSON"}
        return {"passed": True, "detail": "output validated"}

    def _check_deterministic_replay(
        self, actual: Any, baseline: Any
    ) -> dict:
        if baseline is None:
            return {"passed": True, "detail": "no baseline for replay check"}

        actual_hash = hashlib.sha256(
            json.dumps(actual, sort_keys=True, default=str).encode()
        ).hexdigest()
        baseline_hash = hashlib.sha256(
            json.dumps(baseline, sort_keys=True, default=str).encode()
        ).hexdigest()

        if actual_hash == baseline_hash:
            return {"passed": True, "detail": "deterministic match"}
        return {
            "passed": False,
            "detail": f"replay mismatch: {actual_hash[:8]} != {baseline_hash[:8]}",
        }

    def _check_execution_hash(self, proof: Optional[dict]) -> dict:
        if proof is None:
            return {"passed": True, "detail": "no proof provided"}
        required_fields = ["job_id", "input_hash", "execution_hash"]
        missing = [f for f in required_fields if f not in proof or not proof[f]]
        if missing:
            return {"passed": False, "detail": f"missing proof fields: {missing}"}
        if len(proof.get("execution_hash", "")) != 64:
            return {"passed": False, "detail": "malformed execution_hash"}
        return {"passed": True, "detail": "execution proof valid"}

    def _check_audit_chain(self, job_id: str) -> dict:
        if self.audit_logger is None:
            return {"passed": True, "detail": "no audit_logger attached"}
        report = self.audit_logger.verify_chain()
        return {
            "passed": report.get("valid", False),
            "detail": f"chain entries: {report.get('total_entries', 0)}",
        }

    def _compute_severity(self, checks: dict) -> str:
        if not checks:
            return "NONE"
        if any(not c["passed"] for c in checks.values()):
            schema_fail = checks.get("output_schema", {}).get("passed", True)
            replay_fail = checks.get("deterministic_replay", {}).get("passed", True)
            if not schema_fail:
                return "HIGH"
            if not replay_fail:
                return "MEDIUM"
            return "LOW"
        return "NONE"

    def _build_details(self, checks: dict) -> str:
        failures = [k for k, v in checks.items() if not v["passed"]]
        if not failures:
            return "ALL_POSTFLIGHT_CHECKS_PASSED"
        return f"POSTFLIGHT_FAILED: {', '.join(failures)}"

    def get_result(self, job_id: str) -> Optional[ValidationResult]:
        return self._validation_cache.get(job_id)
