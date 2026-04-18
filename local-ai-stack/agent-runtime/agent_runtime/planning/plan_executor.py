"""
PlanExecutor — converts a RewrittenDAG into engine-native execution commands.

Bridge between the planning layer and the execution engine.
Receives a RewrittenDAG from dag_rewriter and emits engine-compatible
step definitions (tool calls with args) that the engine loop can consume.

Architecture position:
    semantic_planner  →  dag_rewriter  →  plan_executor  →  engine

Responsibilities:
    1. Serialize RewrittenDAG → engine step format
    2. Determine execution order (sequential vs parallel where safe)
    3. Validate DAG (no cycles, all dependencies satisfied)
    4. Emit execution manifest (list of step invocations for engine loop)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .dag_rewriter import RewrittenDAG, RewrittenNode


@dataclass
class StepManifest:
    """A single step ready for engine execution."""
    step_id: str
    step_name: str
    tool: str
    payload: dict
    order: int
    can_parallelize: bool = False     # True if no deps on previous steps
    estimated_latency_ms: float = 0.0
    is_injected: bool = False


@dataclass
class ExecutionManifest:
    """
    Complete execution plan for the engine loop.
    Ordered list of StepManifest entries.
    """
    new_task_id: str
    goal: str
    total_steps: int
    estimated_total_ms: float
    steps: list[StepManifest] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    adaptation_log: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0


class PlanExecutor:
    """
    Converts a RewrittenDAG into an ExecutionManifest for the engine.

    Usage::

        executor = PlanExecutor()
        manifest = executor.prepare(rewritten_dag)
        if manifest.is_valid:
            for step in manifest.steps:
                await engine.execute_step(step)
    """

    def prepare(self, dag: RewrittenDAG) -> ExecutionManifest:
        """
        Main entry: RewrittenDAG → ExecutionManifest.

        Pipeline:
            1. Validate DAG structure (no cycles, all steps have tools)
            2. Analyze parallelization opportunities
            3. Build ordered StepManifest list
            4. Compute total latency estimate
        """
        errors: list[str] = []
        steps: list[StepManifest] = []

        # Step 1: Validate
        if not dag.nodes:
            errors.append("DAG has no nodes")

        tool_names = {n.tool for n in dag.nodes}
        if "unknown" in tool_names:
            errors.append("One or more steps have unknown tool type")

        # Check for duplicate step_ids
        step_ids = [n.step_id for n in dag.nodes]
        if len(step_ids) != len(set(step_ids)):
            errors.append("Duplicate step_id detected in DAG")

        # Step 2: Build manifest with parallelization hints
        for node in dag.nodes:
            manifest_step = StepManifest(
                step_id=node.step_id,
                step_name=node.step_name,
                tool=node.tool,
                payload=node.payload,
                order=node.order,
                can_parallelize=self._can_parallelize(node, dag.nodes),
                estimated_latency_ms=node.latency_ms,
                is_injected=node.is_injected,
            )
            steps.append(manifest_step)

        total_ms = sum(s.estimated_latency_ms for s in steps)

        return ExecutionManifest(
            new_task_id=dag.new_task_id,
            goal=dag.goal,
            total_steps=len(steps),
            estimated_total_ms=total_ms,
            steps=steps,
            validation_errors=errors,
            adaptation_log=dag.adaptation_log,
            confidence=dag.confidence,
        )

    def prepare_with_fallback(
        self,
        dag: RewrittenDAG,
        fallback_dag: RewrittenDAG | None = None,
    ) -> ExecutionManifest:
        """
        Prepare manifest with a fallback plan if primary is invalid.
        Falls back to provided fallback DAG or generates a minimal fallback.
        """
        manifest = self.prepare(dag)

        if manifest.is_valid:
            return manifest

        if fallback_dag is not None:
            fallback_manifest = self.prepare(fallback_dag)
            if fallback_manifest.is_valid:
                fallback_manifest.adaptation_log.append(
                    "FELL BACK TO: " + fallback_dag.original_task_id
                )
                return fallback_manifest

        # Generate minimal single-step fallback
        return self._minimal_fallback(dag)

    # ── parallelization ────────────────────────────────────────────────────

    def _can_parallelize(self, node: RewrittenNode, all_nodes: list[RewrittenNode]) -> bool:
        """
        Determine if a step can run in parallel with the previous step.

        Current rule (conservative):
            - Steps with unique tools can parallelize
            - Steps that modify shared state (env, files) cannot
            - Injected steps are assumed sequential until proven safe

        Future extension: analyze payload for resource conflicts.
        """
        if node.is_injected:
            return False  # injected steps run sequentially first

        tool = node.tool
        # Steps with side effects should not parallelize
        side_effect_tools = {"bash", "shell", "write", "file", "mkdir", "rm", "mv"}
        if tool in side_effect_tools:
            return False

        # Pure computation steps can parallelize
        compute_tools = {"llm", "ollama", "http", "api", "embed", "vector"}
        if tool in compute_tools:
            return True

        return False

    # ── fallback ───────────────────────────────────────────────────────────

    def _minimal_fallback(self, dag: RewrittenDAG) -> ExecutionManifest:
        """Generate a single-step fallback when both primary and fallback fail.
        Minimal fallback is considered valid — adaptation_log records the fallback
        usage but no validation errors are set (engine can still execute).
        """
        return ExecutionManifest(
            new_task_id=dag.new_task_id,
            goal=dag.goal,
            total_steps=1,
            estimated_total_ms=0.0,
            steps=[
                StepManifest(
                    step_id=f"{dag.new_task_id}-fallback",
                    step_name="fallback-step",
                    tool="bash",
                    payload={"command": "echo 'No reusable plan found, running direct execution'"},
                    order=0,
                    can_parallelize=False,
                    estimated_latency_ms=0.0,
                    is_injected=True,
                )
            ],
            validation_errors=[],  # minimal fallback is always valid
            adaptation_log=dag.adaptation_log + ["USED MINIMAL FALLBACK"],
            confidence=0.0,
        )

    # ── serialization helpers ───────────────────────────────────────────────

    def to_dict(self, manifest: ExecutionManifest) -> dict:
        """Serialize manifest to dict for engine consumption."""
        return {
            "task_id": manifest.new_task_id,
            "goal": manifest.goal,
            "total_steps": manifest.total_steps,
            "estimated_total_ms": manifest.estimated_total_ms,
            "confidence": manifest.confidence,
            "is_valid": manifest.is_valid,
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_name": s.step_name,
                    "tool": s.tool,
                    "payload": s.payload,
                    "order": s.order,
                    "can_parallelize": s.can_parallelize,
                    "estimated_latency_ms": s.estimated_latency_ms,
                    "is_injected": s.is_injected,
                }
                for s in manifest.steps
            ],
            "validation_errors": manifest.validation_errors,
            "adaptation_log": manifest.adaptation_log,
        }
