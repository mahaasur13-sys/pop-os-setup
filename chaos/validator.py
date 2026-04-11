"""
ChaosValidator — post-chaos SBS invariant checker.

Runs after chaos harness completes and produces
Jepsen-style validation reports.

Usage
-----
    from chaos.validator import ChaosValidator

    validator = ChaosValidator(sbs_enforcer)
    validator.validate(final_state)
    report = validator.get_report()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sbs.boundary_spec import SystemBoundarySpec
from sbs.global_invariant_engine import GlobalInvariantEngine
from sbs.failure_classifier import FailureClassifier, FailureCategory, FailureSeverity


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    ok: bool
    invariants_checked: int
    violations_found: int
    failed_invariants: list[str]
    state_hash: int
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "invariants_checked": self.invariants_checked,
            "violations_found": self.violations_found,
            "failed_invariants": self.failed_invariants,
            "state_hash": self.state_hash,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ValidatorReport:
    """Aggregated report from all validation runs."""
    total_validations: int = 0
    total_violations: int = 0
    total_recovered: int = 0
    critical_failures: int = 0
    high_failures: int = 0
    medium_failures: int = 0
    low_failures: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_layer: dict[str, int] = field(default_factory=dict)
    validation_log: list[dict] = field(default_factory=list)

    def add_result(self, result: ValidationResult, layer_violations: dict[str, int] | None = None) -> None:
        self.total_validations += 1
        if not result.ok:
            self.total_violations += result.violations_found
            self.validation_log.append(result.to_dict())
            if layer_violations:
                for layer, count in layer_violations.items():
                    self.by_layer[layer] = self.by_layer.get(layer, 0) + count

    def add_recovery(self) -> None:
        self.total_recovered += 1

    def add_critical(self, category: str) -> None:
        self.critical_failures += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def add_high(self, category: str) -> None:
        self.high_failures += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def add_medium(self, category: str) -> None:
        self.medium_failures += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def add_low(self, category: str) -> None:
        self.low_failures += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_validations": self.total_validations,
            "total_violations": self.total_violations,
            "total_recovered": self.total_recovered,
            "critical_failures": self.critical_failures,
            "high_failures": self.high_failures,
            "medium_failures": self.medium_failures,
            "low_failures": self.low_failures,
            "by_category": self.by_category,
            "by_layer": self.by_layer,
            "status": "PASS" if self.total_violations == 0 else "FAIL",
        }


class ChaosValidator:
    """
    Runs SBS invariant checks against collected system state
    and classifies results using FailureClassifier.

    Produces Jepsen-style reports with per-category failure counts.
    """

    def __init__(
        self,
        sbs_enforcer,  # SBSRuntimeEnforcer
        boundary_spec: SystemBoundarySpec,
        invariant_engine: GlobalInvariantEngine,
        classifier: FailureClassifier | None = None,
    ) -> None:
        self.enforcer = sbs_enforcer
        self.spec = boundary_spec
        self.engine = invariant_engine
        self.classifier = classifier or FailureClassifier()
        self._report = ValidatorReport()
        self._violations_history: list[list[str]] = []

    def validate(self, state: dict[str, Any]) -> ValidationResult:
        """
        Run full SBS invariant validation on collected state.
        Returns ValidationResult with pass/fail and violation details.
        """
        import time
        start = time.monotonic()

        drl = state.get("drl", {})
        ccl = state.get("ccl", {})
        f2 = state.get("f2", {})
        desc = state.get("desc", {})

        violations: list[str] = []

        try:
            self.enforcer.enforce("chaos_validate", state)
            violations = list(self.enforcer.get_violations_summary().keys())
        except Exception:
            pass

        spec_ok = self.spec.validate(state)
        spec_violations = list(self.spec.get_violations())

        engine_ok = self.engine.evaluate(drl, ccl, f2, desc)
        engine_violations = self.engine.get_violations()

        all_violations = spec_violations + engine_violations

        self._violations_history.append(all_violations)

        for v in all_violations:
            self._classify_violation(v)

        # Always add result so total_validations always increments
        layer_violations = dict(self.enforcer.get_violations_summary())
        self._report.add_result(
            ValidationResult(
                ok=len(all_violations) == 0,
                invariants_checked=14,
                violations_found=len(all_violations),
                failed_invariants=all_violations,
                state_hash=hash(str(sorted(state.items()))) if state else 0,
                latency_ms=0.0,
            ),
            layer_violations=layer_violations,
        )

        latency_ms = (time.monotonic() - start) * 1000

        return ValidationResult(
            ok=len(all_violations) == 0,
            invariants_checked=14,
            violations_found=len(all_violations),
            failed_invariants=all_violations,
            state_hash=hash(str(sorted(state.items()))) if state else 0,
            latency_ms=latency_ms,
        )

    def _classify_violation(self, violation: str) -> None:
        """Classify a violation string into a FailureCategory and update report."""
        raw_type = "unknown"
        v_lower = violation.lower()

        if "split_brain" in v_lower or "partition" in v_lower:
            raw_type = "partition"
        elif "quorum" in v_lower:
            raw_type = "quorum_violation"
        elif "leader" in v_lower:
            raw_type = "leadership_split"
        elif "temporal" in v_lower or "drift" in v_lower or "skew" in v_lower:
            raw_type = "clock_skew"
        elif "duplicate" in v_lower or "byzantine" in v_lower:
            raw_type = "duplicate"
        elif "commit_index" in v_lower or "regression" in v_lower:
            raw_type = "consensus_violation"
        elif "sequence" in v_lower or "reorder" in v_lower or "gap" in v_lower:
            raw_type = "sequence_violation"

        category = self.classifier._map_type_to_category(raw_type)
        severity = self.classifier.get_severity_for(category)

        if severity == FailureSeverity.CRITICAL:
            self._report.add_critical(category.value)
        elif severity == FailureSeverity.HIGH:
            self._report.add_high(category.value)
        elif severity == FailureSeverity.MEDIUM:
            self._report.add_medium(category.value)
        elif severity == FailureSeverity.LOW:
            self._report.add_low(category.value)

    def get_report(self) -> ValidatorReport:
        return self._report

    def get_summary(self) -> dict[str, Any]:
        """Human-readable summary for terminal output."""
        report = self._report.to_dict()
        return {
            "status": report["status"],
            "validations": report["total_validations"],
            "violations": report["total_violations"],
            "recovered": report["total_recovered"],
            "critical": report["critical_failures"],
            "high": report["high_failures"],
            "medium": report["medium_failures"],
            "low": report["low_failures"],
            "by_category": report["by_category"],
            "by_layer": report["by_layer"],
        }

    def reset(self) -> None:
        """Reset validator state for a new chaos run."""
        self._report = ValidatorReport()
        self._violations_history.clear()

    def get_violations_history(self) -> list[list[str]]:
        return list(self._violations_history)