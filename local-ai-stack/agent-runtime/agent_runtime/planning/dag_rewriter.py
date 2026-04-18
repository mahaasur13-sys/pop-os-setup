"""
DAGRewriter — adapts retrieved DAG skeletons to new task constraints.

Takes a PlanCandidate (skeleton from past execution) and rewrites it
for the current task's context: different inputs, env vars, resource
bounds, or tool variants.

Architecture position:
    semantic_planner  →  dag_rewriter  →  plan_executor  →  engine

Responsibilities:
    1. Node injection: add new steps required by current task
    2. Node pruning: remove steps irrelevant to current goal
    3. Parameter substitution: adapt tool args from old → new context
    4. Dependency rewrite: update step ordering for new constraints
    5. Tool variant mapping: map old tool names to current tool API
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .semantic_planner import PlanCandidate, StepNode, DAGSkeleton


@dataclass
class RewriteContext:
    """Input parameters for adapting a skeleton to a new task."""
    task_id: str
    goal: str
    worker_id: str = "planner-rewriter"
    injected_steps: list[dict] = field(default_factory=list)
    prune_step_names: list[str] = field(default_factory=list)
    tool_variant_map: dict[str, str] = field(default_factory=dict)
    env_overrides: dict[str, str] = field(default_factory=dict)
    max_total_latency_ms: float = 0.0


@dataclass
class RewrittenNode:
    """A single step after adaptation — ready for plan_executor."""
    step_id: str
    step_name: str
    tool: str
    order: int
    latency_ms: float
    is_injected: bool = False
    payload: dict = field(default_factory=dict)


@dataclass
class RewrittenDAG:
    """A complete adapted execution graph."""
    original_task_id: str
    new_task_id: str
    goal: str
    nodes: list[RewrittenNode]
    total_latency_ms: float
    adaptation_log: list[str] = field(default_factory=list)
    confidence: float = 0.0


class DAGRewriter:
    """
    Rewrites DAG skeletons from semantic memory into task-specific execution graphs.

    Usage::

        rewriter = DAGRewriter()
        context = RewriteContext(
            task_id="new-task-99",
            goal="deploy my service",
            injected_steps=[{"tool": "bash", "step_name": "health-check", "payload": {"command": "curl localhost:8080/ready"}}],
        )
        adapted = rewriter.rewrite(candidate, context)
    """

    def rewrite(
        self,
        candidate: PlanCandidate,
        ctx: RewriteContext,
    ) -> RewrittenDAG:
        """
        Apply all rewrite rules to a candidate skeleton.

        Steps in order:
            1. Clone nodes from skeleton
            2. Apply tool variant map
            3. Prune excluded steps
            4. Inject new steps
            5. Re-index execution order
            6. Annotate latency and constraints

        Returns:
            RewrittenDAG ready for plan_executor.
        """
        skeleton = candidate.skeleton
        log: list[str] = []
        nodes: list[RewrittenNode] = []

        # Clone + transform existing nodes
        for old_node in skeleton.nodes:
            # Skip pruned nodes
            if old_node.step_name in ctx.prune_step_names:
                log.append(f"PRUNED: {old_node.step_name} (explicit exclusion)")
                continue

            # Apply tool variant mapping
            tool = ctx.tool_variant_map.get(old_node.tool, old_node.tool)

            # Create rewritten node
            new_node = RewrittenNode(
                step_id=f"{ctx.task_id}-step-{len(nodes)}",
                step_name=old_node.step_name,
                tool=tool,
                order=len(nodes),
                latency_ms=old_node.latency_ms,
                is_injected=False,
                payload=self._adapt_payload(old_node, ctx),
            )
            nodes.append(new_node)

        # Inject new steps
        for inj in ctx.injected_steps:
            inj_node = RewrittenNode(
                step_id=f"{ctx.task_id}-step-{len(nodes)}",
                step_name=inj.get("step_name", "injected"),
                tool=inj.get("tool", "bash"),
                order=len(nodes),
                latency_ms=inj.get("estimated_latency_ms", 0.0),
                is_injected=True,
                payload=inj.get("payload", {}),
            )
            nodes.append(inj_node)
            log.append(f"INJECTED: {inj_node.step_name} @ order {inj_node.order}")

        # Re-index orders
        for i, node in enumerate(nodes):
            node.order = i

        total_latency = sum(n.latency_ms for n in nodes)

        # Latency constraint check
        if ctx.max_total_latency_ms > 0 and total_latency > ctx.max_total_latency_ms:
            log.append(
                f"WARN: total latency {total_latency:.0f}ms exceeds "
                f"budget {ctx.max_total_latency_ms:.0f}ms"
            )

        return RewrittenDAG(
            original_task_id=skeleton.source_task_id,
            new_task_id=ctx.task_id,
            goal=ctx.goal,
            nodes=nodes,
            total_latency_ms=total_latency,
            adaptation_log=log,
            confidence=candidate.confidence,
        )

    # ── payload adaptation ──────────────────────────────────────────────────

    def _adapt_payload(self, node: StepNode, ctx: RewriteContext) -> dict:
        """
        Adapt a step's payload from the old context to the new one.
        Applies env_overrides and any tool-specific transformations.
        """
        payload = dict(node.metadata)

        # Apply env overrides (e.g. old env var → new value)
        for key, value in ctx.env_overrides.items():
            if key in payload:
                payload[key] = value

        # Tool-specific adaptations
        if node.tool == "bash" or node.tool == "shell":
            # Shell commands may need path adjustments
            pass  # raw command preserved, user injects overrides if needed

        elif node.tool == "http" or node.tool == "aiohttp":
            # URL base might change
            pass  # override via env_overrides if needed

        elif node.tool == "ollama" or node.tool == "llm":
            # Model name may differ
            pass

        return payload


# ── tool variant registry ─────────────────────────────────────────────────────


TOOL_VARIANTS: dict[str, dict[str, str]] = {
    "bash": {
        "legacy": "shell",
        "modern": "bash",
    },
    "ollama": {
        "llama3.2": "llama3.2:latest",
        "llama3": "llama3:latest",
        "qwen2.5": "qwen2.5:latest",
    },
}


def resolve_tool_variant(old_tool: str, target_model: str | None = None) -> str:
    """
    Map old tool reference to current runtime tool.
    If target_model is specified, use it; otherwise return canonical tool name.
    """
    if target_model and old_tool in ("ollama", "llm"):
        return target_model
    return old_tool
