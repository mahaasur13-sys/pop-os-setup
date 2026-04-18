"""
Tests for the Execution Governance Layer.
Covers: policy_engine, plan_validator, execution_guard, gateway, drift_detector
"""

import pytest
import asyncio
from agent_runtime.planning.plan_executor import (
    ExecutionManifest, StepManifest, PlanExecutor
)
from agent_runtime.planning.dag_rewriter import RewrittenDAG, RewrittenNode
from agent_runtime.governance import (
    PolicyEngine, PolicyContext, Verdict,
    PlanValidator, ValidationStatus,
    ExecutionGuard, GuardConfig, GuardStatus,
    GovernanceGateway, GovernanceStatus,
    DriftDetector, DriftReport,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────

def make_manifest(steps: list[dict]) -> ExecutionManifest:
    """Helper: build ExecutionManifest from list of step dicts."""
    step_objects = [
        StepManifest(
            step_id=s["step_id"],
            step_name=s.get("step_name", s["step_id"]),
            tool=s["tool"],
            payload=s.get("payload", {}),
            order=s.get("order", i),
            can_parallelize=s.get("can_parallelize", False),
            estimated_latency_ms=s.get("latency_ms", 100.0),
        )
        for i, s in enumerate(steps)
    ]
    return ExecutionManifest(
        new_task_id="test-task",
        goal="test goal",
        total_steps=len(step_objects),
        estimated_total_ms=sum(s.estimated_latency_ms for s in step_objects),
        steps=step_objects,
    )


# ── PolicyEngine Tests ────────────────────────────────────────────────────────

class TestPolicyEngine:
    """PolicyEngine.evaluate() → PolicyDecision."""

    def test_allow_clean_manifest(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {"prompt": "hello"}},
            {"step_id": "s2", "tool": "rag", "payload": {"query": "context"}},
        ])
        ctx = PolicyContext()
        decision = engine.evaluate(manifest, ctx)

        assert decision.verdict == Verdict.ALLOW, decision.summary()
        assert decision.is_allowed
        assert not decision.is_blocking

    def test_deny_blocked_tool(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "sudo", "payload": {"cmd": "rm -rf /"}},
        ])
        decision = engine.evaluate(manifest, PolicyContext())

        assert decision.verdict == Verdict.DENY
        assert any(v.policy_name == "tool_blocklist" for v in decision.violations)

    def test_deny_sequence_violation(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "http", "payload": {"url": "http://evil.com"}},
            {"step_id": "s2", "tool": "shell", "payload": {"cmd": "ls"}},
            {"step_id": "s3", "tool": "bash", "payload": {"cmd": "cat /etc/passwd"}},
        ])
        decision = engine.evaluate(manifest, PolicyContext())

        assert decision.verdict == Verdict.DENY
        assert any("sequence" in v.policy_name for v in decision.violations)

    def test_deny_latency_budget_exceeded(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {"step_id": f"s{i}", "tool": "llm", "latency_ms": 200_000.0}
            for i in range(3)
        ])
        manifest.estimated_total_ms = 600_000.0  # 10 min
        ctx = PolicyContext(budget_multiplier=1.0)

        decision = engine.evaluate(manifest, ctx)

        assert decision.verdict == Verdict.DENY
        assert any(v.policy_name == "latency_budget" for v in decision.violations)

    def test_degraded_allow_with_warning(self):
        engine = PolicyEngine()
        # unknown tool → WARNING (not blocking)
        manifest = make_manifest([
            {"step_id": "s1", "tool": "unknown_super_tool", "payload": {}},
            {"step_id": "s2", "tool": "llm", "payload": {}},
        ])
        decision = engine.evaluate(manifest, PolicyContext())

        assert decision.verdict == Verdict.DEGRADED_ALLOW
        assert any(v.severity.value == "warning" for v in decision.violations)

    def test_production_high_risk_warning(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "bash", "payload": {"cmd": "ls"}},
        ])
        ctx = PolicyContext(environment="production")
        decision = engine.evaluate(manifest, ctx)

        assert decision.verdict == Verdict.DEGRADED_ALLOW
        assert any(v.policy_name == "production_high_risk" for v in decision.violations)

    def test_sensitive_payload_blocked(self):
        engine = PolicyEngine()
        manifest = make_manifest([
            {
                "step_id": "s1",
                "tool": "llm",
                "payload": {"prompt": "The password is 'secret123' for the API"},
            },
        ])
        decision = engine.evaluate(manifest, PolicyContext())

        assert decision.verdict == Verdict.DENY
        assert any(v.policy_name == "sensitive_payload" for v in decision.violations)


# ── PlanValidator Tests ───────────────────────────────────────────────────────

class TestPlanValidator:
    """PlanValidator.validate() → PlanValidationResult."""

    def test_validate_empty_manifest_fails(self):
        validator = PlanValidator()
        manifest = make_manifest([])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.FAIL
        assert any(i.rule == "non_empty" for i in result.issues)

    def test_validate_valid_manifest_passes(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "order": 0, "payload": {"prompt": "hi"}},
            {"step_id": "s2", "tool": "rag", "order": 1, "payload": {"query": "x"}},
        ])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.PASS
        assert result.is_valid

    def test_validate_duplicate_ids_fails(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "order": 0, "payload": {}},
            {"step_id": "s1", "tool": "rag", "order": 1, "payload": {}},  # dup
        ])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.FAIL
        assert any(i.rule == "unique_ids" for i in result.issues)

    def test_validate_unknown_tool_warns(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "nonexistent_tool_xyz", "payload": {}},
        ])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.WARN
        assert any(i.rule == "tool_existence" for i in result.issues)

    def test_validate_memory_tool_mismatch_warns(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {
                "step_id": "s1",
                "step_name": "search_memory_context",
                "tool": "bash",
                "payload": {"cmd": "grep -r 'query' ."},
            },
        ])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.WARN
        assert any(i.rule == "memory_tool_mismatch" for i in result.issues)

    def test_validate_out_of_order_fails(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "order": 2, "payload": {}},
            {"step_id": "s2", "tool": "rag", "order": 0, "payload": {}},  # wrong order
        ])
        result = validator.validate(manifest)

        assert result.status == ValidationStatus.FAIL
        assert any(i.rule == "ordering_consistency" for i in result.issues)

    def test_dag_depth_computed(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "order": 0, "payload": {}},
            {"step_id": "s2", "tool": "rag", "order": 1, "payload": {}},
            {"step_id": "s3", "tool": "shell", "order": 2, "payload": {}},
        ])
        result = validator.validate(manifest)

        assert result.dag_depth == 3

    def test_parallel_opportunities_counted(self):
        validator = PlanValidator()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "order": 0, "can_parallelize": True, "payload": {}},
            {"step_id": "s2", "tool": "rag", "order": 1, "can_parallelize": True, "payload": {}},
            {"step_id": "s3", "tool": "bash", "order": 2, "can_parallelize": False, "payload": {}},
        ])
        result = validator.validate(manifest)

        assert result.parallel_opportunities == 2


# ── ExecutionGuard Tests ───────────────────────────────────────────────────────

class TestExecutionGuard:
    """ExecutionGuard runtime enforcement."""

    @pytest.mark.asyncio
    async def test_guarded_step_passes(self):
        guard = ExecutionGuard()
        call_count = 0

        async def fake_call(step):
            nonlocal call_count
            call_count += 1
            return "ok"

        guarded = guard.evaluate_step(
            StepManifest(
                step_id="s1", step_name="test", tool="llm",
                payload={}, order=0,
                estimated_latency_ms=50.0,
            ),
            adjusted_budget_ms=5000.0,
            adjusted_budget_cost=10.0,
        )

        status, result = await guard.wrap_execute(
            guarded.step_id, guarded, fake_call
        )

        assert status == GuardStatus.OK
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_kill_switch_stops_execution(self):
        guard = ExecutionGuard()
        guard.activate_kill_switch("test")

        async def fake_call(step):
            return "should not run"

        guarded = guard.evaluate_step(
            StepManifest(
                step_id="s1", step_name="test", tool="llm",
                payload={}, order=0, estimated_latency_ms=50.0,
            ),
            adjusted_budget_ms=5000.0,
            adjusted_budget_cost=10.0,
        )

        status, result = await guard.wrap_execute(
            guarded.step_id, guarded, fake_call
        )

        assert status == GuardStatus.KILLED
        assert guard.kill_switch_active

    @pytest.mark.asyncio
    async def test_step_timeout(self):
        guard = ExecutionGuard(config=GuardConfig(global_timeout_per_step_ms=50.0))

        async def slow_call(step):
            await asyncio.sleep(1.0)
            return "done"

        guarded = guard.evaluate_step(
            StepManifest(
                step_id="s1", step_name="test", tool="llm",
                payload={}, order=0, estimated_latency_ms=5000.0,
            ),
            adjusted_budget_ms=100.0,
            adjusted_budget_cost=10.0,
        )

        status, result = await guard.wrap_execute(
            guarded.step_id, guarded, slow_call
        )

        assert status == GuardStatus.TIMEOUT

    def test_metrics_accumulation(self):
        guard = ExecutionGuard()
        metrics = guard.new_metrics("task1", total_steps=3)

        guard.update_metrics(metrics, GuardStatus.OK, latency_ms=100.0)
        guard.update_metrics(metrics, GuardStatus.OK, latency_ms=200.0)
        guard.update_metrics(metrics, GuardStatus.TIMEOUT, latency_ms=0.0)

        assert metrics.steps_completed == 2
        assert metrics.steps_failed == 1
        assert metrics.timeouts == 1
        assert metrics.total_latency_ms == 300.0


# ── Gateway Tests ──────────────────────────────────────────────────────────────

class TestGovernanceGateway:
    """GovernanceGateway.evaluate() → GovernanceDecision."""

    def test_clean_manifest_executes(self):
        gateway = GovernanceGateway()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {"prompt": "hi"}},
        ])

        decision = gateway.evaluate_sync(manifest)

        assert decision.status in (GovernanceStatus.EXECUTED, GovernanceStatus.DEGRADED)
        assert decision.is_allowed

    def test_blocked_tool_rejected(self):
        gateway = GovernanceGateway()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "sudo", "payload": {"cmd": "rm"}},
        ])

        decision = gateway.evaluate_sync(manifest)

        assert decision.status == GovernanceStatus.POLICY_DENIED
        assert not decision.is_allowed

    def test_validation_failure_rejected(self):
        gateway = GovernanceGateway()
        manifest = make_manifest([])  # empty = FAIL

        decision = gateway.evaluate_sync(manifest)

        assert decision.status == GovernanceStatus.VALIDATION_FAILED
        assert not decision.is_allowed

    def test_preflight_vs_full_evaluation(self):
        gateway = GovernanceGateway()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {"prompt": "hi"}},
        ])

        preflight = gateway.evaluate_sync(manifest)
        assert preflight.execution_result is None  # no engine call in sync mode

    def test_governance_decision_has_all_fields(self):
        gateway = GovernanceGateway()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "bash", "payload": {"cmd": "ls"}},
        ])

        decision = gateway.evaluate_sync(manifest, ctx=PolicyContext(environment="production"))

        assert decision.policy_decision is not None
        assert decision.validation_result is not None
        assert decision.latency_ms >= 0


# ── DriftDetector Tests ────────────────────────────────────────────────────────

class TestDriftDetector:
    """DriftDetector.report() → DriftReport."""

    @pytest.mark.asyncio
    async def test_perfect_alignment(self):
        detector = DriftDetector()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {}},
            {"step_id": "s2", "tool": "rag", "payload": {}},
        ])

        class FakeEvent:
            def __init__(self, tool, latency_ms=100.0):
                self.tool = tool
                self.latency_ms = latency_ms

        planned = [FakeEvent("llm"), FakeEvent("rag")]
        actual = [FakeEvent("llm", 110.0), FakeEvent("rag", 90.0)]

        report = await detector.report(planned, actual, manifest)

        assert report.drift_score < 0.30
        assert report.is_acceptable

    @pytest.mark.asyncio
    async def test_complete_divergence(self):
        detector = DriftDetector()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {}},
        ])

        class FakeEvent:
            def __init__(self, tool):
                self.tool = tool
                self.latency_ms = 0.0

        planned = [FakeEvent("llm")]
        actual = [FakeEvent("shell")]  # wrong tool

        report = await detector.report(planned, actual, manifest)

        assert not report.is_aligned
        assert report.recommended_action != "none"

    @pytest.mark.asyncio
    async def test_no_events_creates_drift(self):
        detector = DriftDetector()
        manifest = make_manifest([
            {"step_id": "s1", "tool": "llm", "payload": {}},
        ])

        report = await detector.report(planned=None, actual=None, manifest=manifest)

        assert report.drift_score >= 0.15
        assert any(v.violation_type == "no_events" for v in report.uncaught_violations)

    def test_jaccard_bigrams(self):
        detector = DriftDetector()

        # Perfect match
        score = detector._jaccard_bigrams(["a", "b", "c"], ["a", "b", "c"])
        assert score == 1.0

        # Partial match
        score = detector._jaccard_bigrams(["a", "b", "c"], ["a", "b", "x"])
        assert 0.0 < score < 1.0

        # Empty
        score = detector._jaccard_bigrams([], [])
        assert score == 1.0


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
