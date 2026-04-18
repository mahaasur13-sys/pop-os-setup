"""
Tests for agent-runtime planning subsystem (Semantic Planning Layer).

Run with: PYTHONPATH=/home/workspace/local-ai-stack/agent-runtime \
    pytest tests/test_planning.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ["AGENT_VECTOR_BACKEND"] = "inmemory"

from agent_runtime.memory.vector_adapter import InMemoryAdapter
from agent_runtime.memory.query_engine import SemanticQueryEngine
from agent_runtime.planning.semantic_planner import (
    SemanticPlanner,
    StepNode,
    DAGSkeleton,
    PlanCandidate,
)
from agent_runtime.planning.dag_rewriter import (
    DAGRewriter,
    RewriteContext,
    RewrittenDAG,
    RewrittenNode,
)
from agent_runtime.planning.plan_executor import (
    PlanExecutor,
    StepManifest,
    ExecutionManifest,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_event_store():
    """Mock event store that returns synthetic event sequences."""
    store = MagicMock()

    def make_step_event(step_id, step_name, tool, latency_ms=100.0):
        ev = MagicMock()
        ev.event_type = MagicMock()
        ev.event_type.value = "STEP_EXECUTED"
        ev.step_id = step_id
        ev.payload = {
            "step_name": step_name,
            "tool": tool,
            "latency_ms": latency_ms,
            "metadata": {},
        }
        return ev

    def get_events(task_id):
        if task_id == "task-deploy-01":
            return [
                make_step_event("s1", "clone-repo", "bash", 200.0),
                make_step_event("s2", "build-image", "bash", 5000.0),
                make_step_event("s3", "push-registry", "http", 300.0),
                make_step_event("s4", "apply-k8s", "bash", 1000.0),
            ]
        elif task_id == "task-deploy-02":
            return [
                make_step_event("s1", "checkout", "bash", 150.0),
                make_step_event("s2", "docker-build", "bash", 8000.0),
                make_step_event("s3", "kubectl-apply", "bash", 800.0),
            ]
        elif task_id == "task-fail-01":
            return [
                make_step_event("s1", "fetch-deps", "bash", 200.0),
                MagicMock(
                    event_type=MagicMock(value="TASK_COMPLETED"),
                    payload={"result": "ok"},
                ),
            ]
        return []

    async def get_events_async(task_id):
        return get_events(task_id)

    store.get_all_events = MagicMock(side_effect=get_events_async)
    return store


@pytest.fixture
def mock_query_engine():
    """Mock query engine that returns synthetic plan results."""
    from agent_runtime.memory.query_engine import ExecutionPlanResult

    engine = MagicMock(spec=SemanticQueryEngine)
    engine.retrieve_execution_plans = MagicMock(return_value=[
        ExecutionPlanResult(
            task_id="task-deploy-01",
            similarity=0.87,
            goal="deploy service to kubernetes",
            outcome="success",
        ),
        ExecutionPlanResult(
            task_id="task-deploy-02",
            similarity=0.72,
            goal="deploy docker image to k8s",
            outcome="success",
        ),
    ])
    engine.find_failure_patterns = MagicMock(return_value=[])
    return engine


@pytest.fixture
def sample_plan_candidate() -> PlanCandidate:
    """A pre-built PlanCandidate for rewriter/executor tests."""
    skeleton = DAGSkeleton(
        source_task_id="task-deploy-01",
        goal="deploy service to kubernetes",
        outcome="success",
        similarity=0.87,
        nodes=[
            StepNode("s1", "clone-repo", "bash", order=0, latency_ms=200.0, success=True),
            StepNode("s2", "build-image", "bash", order=1, latency_ms=5000.0, success=True),
            StepNode("s3", "push-registry", "http", order=2, latency_ms=300.0, success=True),
            StepNode("s4", "apply-k8s", "bash", order=3, latency_ms=1000.0, success=True),
        ],
        total_latency_ms=6500.0,
        epoch_count=1,
    )
    return PlanCandidate(rank=1, skeleton=skeleton, confidence=0.87)


# ─── SemanticPlanner tests ─────────────────────────────────────────────────────

class TestSemanticPlanner:
    def test_plan_returns_candidates(self, mock_query_engine, mock_event_store):
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="deploy service to kubernetes", top_k=5)

        assert len(candidates) >= 1
        assert all(isinstance(c, PlanCandidate) for c in candidates)
        assert all(c.confidence > 0 for c in candidates)

    def test_plan_sorted_by_confidence(self, mock_query_engine, mock_event_store):
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="deploy", top_k=5)

        if len(candidates) >= 2:
            assert candidates[0].confidence >= candidates[1].confidence

    def test_plan_empty_when_no_results(self, mock_query_engine, mock_event_store):
        mock_query_engine.retrieve_execution_plans = MagicMock(return_value=[])
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="nonexistent task xyz", top_k=5)
        assert candidates == []

    def test_plan_filters_by_min_success_rate(self, mock_query_engine, mock_event_store):
        async def empty_events(task_id):
            return []
        mock_event_store.get_all_events = MagicMock(side_effect=empty_events)
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="deploy", top_k=5, min_success_rate=1.0)
        assert all(
            len(c.skeleton.nodes) > 0 for c in candidates
        ) if candidates else True

    def test_build_skeleton_from_events(self, mock_event_store):
        from agent_runtime.planning.semantic_planner import SemanticPlanner
        from agent_runtime.memory.query_engine import ExecutionPlanResult

        mock_qe = MagicMock(spec=SemanticQueryEngine)
        planner = SemanticPlanner(query_engine=mock_qe, event_store=mock_event_store)

        result = ExecutionPlanResult(
            task_id="task-deploy-01",
            similarity=0.87,
            goal="deploy",
            outcome="success",
        )
        skeleton = planner._build_skeleton(result)

        assert skeleton is not None
        assert skeleton.source_task_id == "task-deploy-01"
        assert len(skeleton.nodes) == 4
        assert skeleton.total_latency_ms == 6500.0

    def test_generate_adaptation_notes(self, mock_event_store):
        from agent_runtime.planning.semantic_planner import SemanticPlanner

        planner = SemanticPlanner(
            query_engine=MagicMock(),
            event_store=mock_event_store,
        )
        notes = planner._generate_adaptation_notes(
            DAGSkeleton(
                source_task_id="task-1",
                goal="deploy",
                outcome="ok",
                similarity=0.9,
                nodes=[
                    StepNode("s1", "step1", "bash", order=0, latency_ms=100.0, success=True),
                    StepNode("s2", "step2", "ollama", order=1, latency_ms=500.0, success=True),
                ],
                total_latency_ms=600.0,
                epoch_count=1,
            )
        )
        assert isinstance(notes, list)
        assert len(notes) > 0


# ─── DAGRewriter tests ────────────────────────────────────────────────────────

class TestDAGRewriter:
    def test_rewrite_preserves_nodes(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(task_id="new-task-99", goal="deploy new service")
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        assert dag.original_task_id == sample_plan_candidate.skeleton.source_task_id
        assert dag.new_task_id == "new-task-99"
        assert len(dag.nodes) == len(sample_plan_candidate.skeleton.nodes)

    def test_rewrite_prunes_steps(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="new-task-99",
            goal="deploy",
            prune_step_names=["build-image"],  # skip build in pre-built scenario
        )
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        step_names = {n.step_name for n in dag.nodes}
        assert "build-image" not in step_names
        assert len(dag.nodes) == 3

    def test_rewrite_injects_steps(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="new-task-99",
            goal="deploy",
            injected_steps=[
                {
                    "tool": "bash",
                    "step_name": "health-check",
                    "payload": {"command": "curl localhost:8080/ready"},
                    "estimated_latency_ms": 500.0,
                }
            ],
        )
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        step_names = [n.step_name for n in dag.nodes]
        assert "health-check" in step_names
        # Injected node should be marked
        injected = next(n for n in dag.nodes if n.step_name == "health-check")
        assert injected.is_injected is True
        assert injected.order == len(dag.nodes) - 1  # appended at end

    def test_rewrite_applies_tool_variant_map(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="new-task-99",
            goal="deploy",
            tool_variant_map={"bash": "shell", "http": "aiohttp"},
        )
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        tools = {n.tool for n in dag.nodes}
        assert "shell" in tools
        assert "aiohttp" in tools

    def test_rewrite_reindexes_orders(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="new-task-99",
            goal="deploy",
            prune_step_names=["build-image"],
        )
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        orders = [n.order for n in dag.nodes]
        assert orders == list(range(len(dag.nodes)))

    def test_rewrite_logs_adaptation_actions(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="new-task-99",
            goal="deploy",
            prune_step_names=["push-registry"],
            injected_steps=[{"tool": "bash", "step_name": "notify", "payload": {}}],
        )
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        assert any("PRUNED" in log for log in dag.adaptation_log)
        assert any("INJECTED" in log for log in dag.adaptation_log)


# ─── PlanExecutor tests ───────────────────────────────────────────────────────

class TestPlanExecutor:
    def test_prepare_produces_valid_manifest(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(task_id="new-task-99", goal="deploy")
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        executor = PlanExecutor()
        manifest = executor.prepare(dag)

        assert manifest.is_valid
        assert manifest.total_steps == len(dag.nodes)
        assert len(manifest.validation_errors) == 0

    def test_prepare_detects_missing_nodes(self):
        executor = PlanExecutor()
        dag = RewrittenDAG(
            original_task_id="t1",
            new_task_id="t2",
            goal="test",
            nodes=[],
            total_latency_ms=0.0,
            adaptation_log=[],
            confidence=0.5,
        )
        manifest = executor.prepare(dag)
        assert not manifest.is_valid
        assert any("no nodes" in e.lower() for e in manifest.validation_errors)

    def test_prepare_flags_unknown_tool(self):
        executor = PlanExecutor()
        dag = RewrittenDAG(
            original_task_id="t1",
            new_task_id="t2",
            goal="test",
            nodes=[
                RewrittenNode(
                    step_id="s1",
                    step_name="unknown-step",
                    tool="unknown",
                    order=0,
                    latency_ms=100.0,
                )
            ],
            total_latency_ms=100.0,
            adaptation_log=[],
            confidence=0.5,
        )
        manifest = executor.prepare(dag)
        assert not manifest.is_valid
        assert any("unknown" in e.lower() for e in manifest.validation_errors)

    def test_prepare_computes_total_latency(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(task_id="new-task-99", goal="deploy")
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        executor = PlanExecutor()
        manifest = executor.prepare(dag)

        expected = sum(n.latency_ms for n in dag.nodes)
        assert manifest.estimated_total_ms == expected

    def test_prepare_sets_parallelization_flags(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(task_id="new-task-99", goal="deploy")
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        executor = PlanExecutor()
        manifest = executor.prepare(dag)

        for step in manifest.steps:
            assert isinstance(step.can_parallelize, bool)

    def test_prepare_with_fallback_uses_fallback_when_invalid(self):
        executor = PlanExecutor()
        invalid_dag = RewrittenDAG(
            original_task_id="t1",
            new_task_id="t2",
            goal="test",
            nodes=[],  # invalid
            total_latency_ms=0.0,
            adaptation_log=[],
            confidence=0.5,
        )
        valid_fallback = RewrittenDAG(
            original_task_id="t1",
            new_task_id="t2",
            goal="test",
            nodes=[
                RewrittenNode(
                    step_id="fallback-step",
                    step_name="fallback",
                    tool="bash",
                    order=0,
                    latency_ms=100.0,
                )
            ],
            total_latency_ms=100.0,
            adaptation_log=["fallback log"],
            confidence=0.3,
        )
        manifest = executor.prepare_with_fallback(invalid_dag, fallback_dag=valid_fallback)
        assert manifest.is_valid
        assert manifest.total_steps == 1

    def test_prepare_with_fallback_uses_minimal_when_both_invalid(self):
        executor = PlanExecutor()
        invalid_dag = RewrittenDAG(
            original_task_id="t1",
            new_task_id="t2",
            goal="test",
            nodes=[],
            total_latency_ms=0.0,
            adaptation_log=[],
            confidence=0.0,
        )
        manifest = executor.prepare_with_fallback(invalid_dag)
        assert manifest.is_valid  # minimal fallback is always valid
        assert manifest.total_steps == 1
        assert "fallback" in manifest.steps[0].step_name

    def test_to_dict_serialization(self, sample_plan_candidate):
        rewriter = DAGRewriter()
        ctx = RewriteContext(task_id="new-task-99", goal="deploy")
        dag = rewriter.rewrite(sample_plan_candidate, ctx)

        executor = PlanExecutor()
        manifest = executor.prepare(dag)
        d = executor.to_dict(manifest)

        assert d["task_id"] == "new-task-99"
        assert d["total_steps"] == manifest.total_steps
        assert d["is_valid"] is True
        assert len(d["steps"]) == manifest.total_steps
        assert "step_id" in d["steps"][0]
        assert "tool" in d["steps"][0]


# ─── Integration: full pipeline ───────────────────────────────────────────────

class TestFullPlanningPipeline:
    def test_plan_to_execution_manifest_pipeline(
        self, mock_query_engine, mock_event_store
    ):
        # 1. SemanticPlanner → PlanCandidates
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="deploy to kubernetes", top_k=5)
        assert len(candidates) > 0

        # 2. DAGRewriter → RewrittenDAG
        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="task-pipeline-test",
            goal="deploy to kubernetes",
            injected_steps=[
                {
                    "tool": "bash",
                    "step_name": "notify-deployment",
                    "payload": {"command": "echo 'done'"},
                    "estimated_latency_ms": 50.0,
                }
            ],
        )
        primary = candidates[0]
        dag = rewriter.rewrite(primary, ctx)

        # 3. PlanExecutor → ExecutionManifest
        executor = PlanExecutor()
        manifest = executor.prepare(dag)

        assert manifest.is_valid, manifest.validation_errors
        assert manifest.total_steps > 0
        assert manifest.confidence > 0

        # 4. Serialization round-trip
        d = executor.to_dict(manifest)
        assert d["goal"] == "deploy to kubernetes"
        assert all("step_id" in s for s in d["steps"])

    def test_full_pipeline_with_pruning(
        self, mock_query_engine, mock_event_store
    ):
        planner = SemanticPlanner(
            query_engine=mock_query_engine,
            event_store=mock_event_store,
        )
        candidates = planner.plan(goal="deploy", top_k=5)

        rewriter = DAGRewriter()
        ctx = RewriteContext(
            task_id="task-pruned",
            goal="deploy lightweight",
            prune_step_names=["build-image"],
        )
        dag = rewriter.rewrite(candidates[0], ctx)

        executor = PlanExecutor()
        manifest = executor.prepare(dag)

        assert manifest.is_valid
        step_names = {s.step_name for s in manifest.steps}
        assert "build-image" not in step_names
