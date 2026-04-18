"""
DriftDetector — post-execution analysis: planned vs actual event comparison.

Compares:
  - Planned DAG structure / tool sequence (from ExecutionManifest)
  - Actual emitted events (from event_store after execution)

Computes:
  - execution_drift_score: 0.0 (perfect match) → 1.0 (complete divergence)
  - policy_violations_not_caught: structural violations that slipped through
  - tool_sequence_drift: if expected tool sequence matches actual
  - latency_drift: expected vs actual execution time
  - step_completion_drift: expected vs actual steps completed

Architecture position:
  gateway (post-exec) → drift_detector → event_store write
  Used for: audit logs, adaptive policy learning, plan reuse scoring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import Counter


@dataclass
class DriftMetrics:
    """Individual drift measurements."""
    tool_sequence_match: float = 1.0   # 0.0–1.0 Jaccard similarity
    latency_drift_ratio: float = 1.0   # actual/expected (1.0 = perfect)
    step_completion_rate: float = 1.0  # actual_steps / expected_steps
    payload_drift: float = 0.0         # 0.0–1.0 normalized edit distance
    event_count_match: float = 1.0     # actual_events / expected_events


@dataclass
class UncaughtViolation:
    """A policy/logical violation that governance did not catch."""
    violation_type: str
    description: str
    severity: str  # "high", "medium", "low"
    detail: Optional[str] = None


@dataclass
class DriftReport:
    """
    Post-execution analysis report.

    drift_score: weighted composite 0.0–1.0
      0.0 = perfect alignment (plan == execution)
      1.0 = complete divergence
    """
    task_id: str
    goal: str
    drift_score: float
    metrics: DriftMetrics
    uncaught_violations: list[UncaughtViolation] = field(default_factory=list)
    policy_violations_missed: list[str] = field(default_factory=list)
    recommended_action: str = "none"  # "retrain", "block", "warn", "none"
    evaluated_at: float = field(default_factory=time.monotonic)
    manifest_confidence: float = 0.0
    actual_latency_ms: float = 0.0
    expected_latency_ms: float = 0.0
    actual_steps: int = 0
    expected_steps: int = 0

    @property
    def is_aligned(self) -> bool:
        """True if drift_score is below threshold (0.15)."""
        return self.drift_score < 0.15

    @property
    def is_acceptable(self) -> bool:
        """True if drift_score is below warning threshold (0.30)."""
        return self.drift_score < 0.30

    def summary(self) -> str:
        lines = [
            f"[DRIFT] score={self.drift_score:.3f} ({'ALIGNED' if self.is_aligned else 'DIVERGED'})",
            f"  task_id={self.task_id}",
            f"  tool_seq_match={self.metrics.tool_sequence_match:.2f}",
            f"  latency_drift={self.metrics.latency_drift_ratio:.2f}x",
            f"  step_completion={self.metrics.step_completion_rate:.2%}",
            f"  action={self.recommended_action}",
        ]
        if self.uncaught_violations:
            lines.append(f"  uncaught_violations={len(self.uncaught_violations)}")
            for v in self.uncaught_violations:
                lines.append(f"    • [{v.severity}] {v.violation_type}: {v.description}")
        if self.policy_violations_missed:
            lines.append(f"  policy_missed={self.policy_violations_missed}")
        return "\n".join(lines)


# ── DriftDetector ─────────────────────────────────────────────────────────────

class DriftDetector:
    """
    Computes drift between planned manifest and actual execution.

    Usage (post-execution)::

        detector = DriftDetector()
        report = await detector.report(
            planned_events=emitted_events,  # from event_store
            actual_events=final_events,
            manifest=execution_manifest,
        )
        if not report.is_aligned:
            await policy_engine.adapt(report)
    """

    DRIFT_THRESHOLD = 0.15    # above this → flag for review
    WARNING_THRESHOLD = 0.30  # above this → block plan reuse

    def __init__(self, thresholds: Optional[tuple[float, float]] = None):
        self.drift_threshold = thresholds[0] if thresholds else self.DRIFT_THRESHOLD
        self.warning_threshold = thresholds[1] if thresholds else self.WARNING_THRESHOLD

    async def report(
        self,
        planned_events: Optional[list],
        actual_events: Optional[list],
        manifest,         # ExecutionManifest
    ) -> DriftReport:
        """
        Build drift report comparing planned vs actual.

        Args:
            planned_events: events as predicted by planner (from event_store)
            actual_events: events actually emitted during execution
            manifest: original ExecutionManifest
        """
        task_id = manifest.new_task_id
        goal = manifest.goal

        # ── compute metrics ───────────────────────────────────────────────────

        metrics = self._compute_metrics(manifest, planned_events, actual_events)

        # ── compute composite drift score ──────────────────────────────────────

        drift_score = self._compute_drift_score(metrics)

        # ── detect uncaught violations ─────────────────────────────────────────

        uncaught = self._detect_uncaught_violations(manifest, actual_events)

        # ── policy violations that slipped through ─────────────────────────────

        missed = self._detect_missed_policy_violations(manifest, actual_events)

        # ── recommended action ─────────────────────────────────────────────────

        action = self._recommend_action(drift_score, uncaught, missed)

        return DriftReport(
            task_id=task_id,
            goal=goal,
            drift_score=drift_score,
            metrics=metrics,
            uncaught_violations=uncaught,
            policy_violations_missed=missed,
            recommended_action=action,
            manifest_confidence=manifest.confidence,
            expected_latency_ms=manifest.estimated_total_ms,
            expected_steps=manifest.total_steps,
        )

    def _compute_metrics(
        self,
        manifest,
        planned_events: Optional[list],
        actual_events: Optional[list],
    ) -> DriftMetrics:
        """Compute individual drift components."""

        # Tool sequence match (Jaccard of bigrams)
        planned_seq = [s.tool for s in manifest.steps]
        actual_seq = self._extract_tool_sequence(actual_events or [])

        tool_seq_match = self._jaccard_bigrams(planned_seq, actual_seq)

        # Latency drift
        actual_latency = self._extract_latency(actual_events)
        expected_latency = manifest.estimated_total_ms
        latency_drift = (
            actual_latency / max(expected_latency, 1.0)
            if actual_latency > 0
            else 1.0
        )

        # Step completion rate
        actual_steps = len(actual_events) if actual_events else 0
        expected_steps = manifest.total_steps
        step_rate = actual_steps / max(expected_steps, 1)

        # Event count match
        event_match = actual_steps / max(len(planned_events) if planned_events else expected_steps, 1)

        # Payload drift (edit distance on payloads — simplified)
        payload_drift = self._compute_payload_drift(manifest, actual_events)

        return DriftMetrics(
            tool_sequence_match=tool_seq_match,
            latency_drift_ratio=latency_drift,
            step_completion_rate=step_rate,
            payload_drift=payload_drift,
            event_count_match=event_match,
        )

    def _compute_drift_score(self, m: DriftMetrics) -> float:
        """
        Weighted composite drift score.

        Weights:
          tool_sequence: 0.35  (most important — did we execute the right tools?)
          step_completion: 0.25 (did we finish?)
          latency_drift: 0.20  (how efficient?)
          payload_drift: 0.15  (did we produce the right output?)
          event_count: 0.05  (minor — event count noise)
        """
        # Latency drift: penalize both too fast (suspicious) and too slow
        # Normalize: 1.0 = perfect, 0.5 = 2x deviation
        latency_component = max(0.0, 1.0 - abs(1.0 - m.latency_drift_ratio) * 0.5)

        score = (
            m.tool_sequence_match * 0.35
            + m.step_completion_rate * 0.25
            + latency_component * 0.20
            + (1.0 - m.payload_drift) * 0.15
            + m.event_count_match * 0.05
        )

        return min(1.0, max(0.0, score))

    def _detect_uncaught_violations(
        self,
        manifest,
        actual_events: Optional[list],
    ) -> list[UncaughtViolation]:
        """
        Post-exec check for logical violations governance should have caught.

        Examples:
          - Step that should not have executed (wrong tool for the context)
          - Unexpected state changes in event payload
          - Steps that ran out of expected order
        """
        violations = []

        if not actual_events:
            violations.append(UncaughtViolation(
                violation_type="no_events",
                description="No events recorded — possible silent failure",
                severity="high",
            ))
            return violations

        # Check: was the correct tool used for the dominant operation?
        planned_tools = Counter(s.tool for s in manifest.steps)
        actual_tools = Counter(self._extract_tool_sequence(actual_events))

        # Tool substitution: if a step used a different tool than planned
        for planned_tool, count in planned_tools.items():
            actual_count = actual_tools.get(planned_tool, 0)
            if actual_count < count * 0.5:  # Less than half used as planned
                violations.append(UncaughtViolation(
                    violation_type="tool_substitution",
                    description=f"Tool '{planned_tool}' used {actual_count}/{count} times expected",
                    severity="medium",
                    detail=f"planned={count}, actual={actual_count}",
                ))

        # Check: unexpected tools in actual execution
        unexpected = set(actual_tools.keys()) - set(planned_tools.keys())
        if unexpected:
            violations.append(UncaughtViolation(
                violation_type="unexpected_tools",
                description=f"Unexpected tools in execution: {sorted(unexpected)}",
                severity="low",
            ))

        return violations

    def _detect_missed_policy_violations(
        self,
        manifest,
        actual_events: Optional[list],
    ) -> list[str]:
        """
        Policy violations that were not caught pre-execution.

        This is an introspection pass — compare what governance checked
        vs what actually happened.
        """
        missed = []

        # Example: governance allowed the manifest but actual execution
        # produced sensitive data in output that wasn't flagged in payload scan
        # This would require reading actual event payloads — placeholder for now

        return missed

    def _recommend_action(
        self,
        drift_score: float,
        uncaught: list[UncaughtViolation],
        missed_policy: list[str],
    ) -> str:
        """Determine recommended follow-up action based on drift analysis."""
        if drift_score >= self.warning_threshold:
            return "block"  # don't reuse this plan

        if drift_score >= self.drift_threshold:
            if any(v.severity == "high" for v in uncaught):
                return "retrain"  # planner needs adjustment
            return "warn"  # log and alert

        return "none"

    # ── helper functions ─────────────────────────────────────────────────────

    def _extract_tool_sequence(self, events: list) -> list[str]:
        """Extract tool names from event stream."""
        tools = []
        for event in events:
            if hasattr(event, "tool"):
                tools.append(event.tool)
            elif isinstance(event, dict):
                tools.append(event.get("tool", "unknown"))
        return tools

    def _extract_latency(self, events: Optional[list]) -> float:
        """Sum latency_ms from event stream."""
        if not events:
            return 0.0
        total = 0.0
        for event in events:
            if hasattr(event, "latency_ms"):
                total += event.latency_ms
            elif isinstance(event, dict):
                total += event.get("latency_ms", 0.0)
        return total

    def _jaccard_bigrams(self, a: list[str], b: list[str]) -> float:
        """Jaccard similarity of tool bigrams."""
        def bigrams(seq):
            if len(seq) < 2:
                return set()
            return set(tuple(seq[i:i+2]) for i in range(len(seq) - 1))

        bg_a = bigrams(a)
        bg_b = bigrams(b)
        if not bg_a and not bg_b:
            return 1.0
        if not bg_a or not bg_b:
            return 0.0
        return len(bg_a & bg_b) / len(bg_a | bg_b)

    def _compute_payload_drift(self, manifest, actual_events: Optional[list]) -> float:
        """
        Placeholder: compute how much actual outputs differ from expected.

        Full implementation would compare step payloads against
        actual event payloads (e.g., file content, API responses).
        Currently returns 0.0 (perfect) as a safe default.
        """
        if not actual_events:
            return 1.0  # no output = max drift
        return 0.0  # safe default until we have payload comparison
