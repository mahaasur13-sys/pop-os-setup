"""
SemanticPlanner — semantic plan retrieval layer.

Retrieves past DAG skeletons from similar goal contexts and produces
reusable execution plan candidates for the engine loop.

Architecture position:
    memory/query_engine  →  semantic_planner  →  dag_rewriter  →  engine

Responsibilities:
    1. Accept a goal description (natural language)
    2. Embed the goal and query the semantic memory for similar past tasks
    3. For each similar task, retrieve its event sequence from event_store
    4. Extract the DAG skeleton (step order + tool types)
    5. Return ranked PlanCandidate objects with metadata for reuse

Separation of concerns:
    - semantic_planner: goal → plan candidates (what to reuse)
    - dag_rewriter: adapt skeleton to new task constraints (how to reuse)
    - plan_executor: convert semantic DAG → engine DAG (bridge to execution)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agent_runtime.memory.query_engine import (
    SemanticQueryEngine,
    ExecutionPlanResult,
)
from agent_runtime.event_store import EventStore


# ── data classes ──────────────────────────────────────────────────────────────


@dataclass
class StepNode:
    """Single node in a DAG skeleton — represents a step from past execution."""
    step_id: str
    step_name: str
    tool: str
    order: int
    latency_ms: float
    success: bool
    metadata: dict = field(default_factory=dict)


@dataclass
class DAGSkeleton:
    """Extracted execution graph from a past successful task."""
    source_task_id: str
    goal: str
    outcome: str | None
    similarity: float
    nodes: list[StepNode]          # ordered by execution order
    total_latency_ms: float
    epoch_count: int


@dataclass
class PlanCandidate:
    """
    A candidate execution plan retrieved from semantic memory.
    Ready for adaptation by dag_rewriter.
    """
    rank: int
    skeleton: DAGSkeleton
    adaptation_notes: list[str] = field(default_factory=list)
    confidence: float = 0.0       # 0..1, based on similarity × success rate


# ── semantic planner ──────────────────────────────────────────────────────────


class SemanticPlanner:
    """
    Retrieves and ranks past DAG skeletons by goal similarity.

    Usage::

        planner = SemanticPlanner()
        candidates = planner.plan(goal="deploy to kubernetes cluster")
        for candidate in candidates:
            print(candidate.skeleton.source_task_id, candidate.confidence)

    Design notes:
        - Fully read-only: never writes to event_store or memory
        - SemanticQueryEngine is the read-side of CQRS
        - event_store replay builds the DAG skeleton from raw events
    """

    def __init__(
        self,
        query_engine: Optional[SemanticQueryEngine] = None,
        event_store: Optional[EventStore] = None,
    ) -> None:
        self._qe = query_engine or SemanticQueryEngine()
        self._es = event_store or EventStore()
        self._qe_adapter = self._qe.adapter  # reuse adapter's dimension

    # ── public API ───────────────────────────────────────────────────────────

    def plan(
        self,
        goal: str,
        top_k: int = 5,
        min_success_rate: float = 0.5,
    ) -> list[PlanCandidate]:
        """
        Main entry point: goal → ranked plan candidates.

        Args:
            goal: Natural language description of the task to accomplish.
            top_k: How many candidate skeletons to retrieve.
            min_success_rate: Ignore skeletons with success rate below threshold.

        Returns:
            List of PlanCandidate, sorted by confidence descending.
            Empty list if no suitable candidates found.
        """
        # Step 1: semantic retrieval of similar past tasks
        plan_results = self._qe.retrieve_execution_plans(goal=goal, top_k=top_k)

        if not plan_results:
            return []

        # Step 2: build DAG skeleton for each candidate
        candidates: list[PlanCandidate] = []
        for rank, result in enumerate(plan_results, start=1):
            skeleton = self._build_skeleton(result)
            if skeleton is None:
                continue

            # Filter by success rate
            if not skeleton.nodes:
                continue
            success_count = sum(1 for n in skeleton.nodes if n.success)
            success_rate = success_count / len(skeleton.nodes)
            if success_rate < min_success_rate:
                continue

            confidence = result.similarity * success_rate

            notes = self._generate_adaptation_notes(skeleton)

            candidates.append(
                PlanCandidate(
                    rank=rank,
                    skeleton=skeleton,
                    adaptation_notes=notes,
                    confidence=round(confidence, 3),
                )
            )

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def plan_from_error(
        self,
        error_signature: str,
        top_k: int = 3,
    ) -> list[PlanCandidate]:
        """
        Retrieve skeletons that previously handled a similar error pattern.
        Useful for: retry with known-good recovery strategy.

        Args:
            error_signature: Semantic description of the failure.
            top_k: How many recovery skeletons to retrieve.

        Returns:
            Ranked PlanCandidate list sorted by confidence.
        """
        failure_results = self._qe.find_failure_patterns(
            error_signature=error_signature,
            top_k=top_k * 2,
        )

        if not failure_results:
            return []

        # Find tasks that had failures and recovered
        candidates: list[PlanCandidate] = []
        seen_tasks: set[str] = set()

        for result in failure_results:
            if result.task_id in seen_tasks:
                continue
            seen_tasks.add(result.task_id)

            # Check if this task eventually succeeded (TASK_COMPLETED present)
            events = self._get_task_events_sync(result.task_id)
            has_completion = any(
                e.event_type.value == "TASK_COMPLETED" for e in events
            )
            if not has_completion:
                continue

            # Build skeleton from the full event sequence
            skeleton = self._build_skeleton_from_events(
                source_task_id=result.task_id,
                events=events,
                goal_embedding=error_signature,
            )
            if skeleton is None:
                continue

            confidence = result.similarity * 0.8  # recovery bonus already encoded
            candidates.append(
                PlanCandidate(
                    rank=0,
                    skeleton=skeleton,
                    adaptation_notes=[
                        f"Recovered from error: {error_signature}",
                        "Review step sequence before retry",
                    ],
                    confidence=round(confidence, 3),
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:top_k]

    # ── skeleton building ────────────────────────────────────────────────────

    def _build_skeleton(
        self,
        plan_result: ExecutionPlanResult,
    ) -> DAGSkeleton | None:
        """
        Retrieve events for task_id and extract DAG skeleton.
        Sync wrapper — uses asyncio.run only at the boundary (call from sync only).
        """
        import asyncio

        events = asyncio.run(self._es.get_all_events(plan_result.task_id))
        return self._build_skeleton_from_events(
            source_task_id=plan_result.task_id,
            events=events,
            goal_embedding=plan_result.goal,
            outcome=plan_result.outcome,
            similarity=plan_result.similarity,
        )

    def _build_skeleton_from_events(
        self,
        source_task_id: str,
        events: list,          # list[TaskEvent]
        goal_embedding: str,
        outcome: str | None = None,
        similarity: float = 0.0,
    ) -> DAGSkeleton | None:
        """Extract ordered StepNode list from raw event stream."""
        from agent_runtime.event_sourcing import EventType

        nodes: list[StepNode] = []
        total_latency = 0.0
        epoch_count = 0
        seen_epochs: set[int] = set()

        for event in events:
            ev_type = event.event_type if hasattr(event, 'event_type') else event.get("event_type")
            if hasattr(ev_type, 'value'):
                ev_type_str = ev_type.value
            else:
                ev_type_str = str(ev_type)

            if ev_type_str == "STEP_EXECUTED":
                payload = event.payload if hasattr(event, 'payload') else event.get("payload", {})
                step_id = event.step_id if hasattr(event, 'step_id') else payload.get("step_id", "")
                tool = payload.get("tool", "unknown")
                step_name = payload.get("step_name", step_id or tool)
                latency = payload.get("latency_ms", 0.0)
                success = True  # STEP_EXECUTED means it ran
                metadata = payload.get("metadata", {})

                nodes.append(
                    StepNode(
                        step_id=step_id or f"step-{len(nodes)}",
                        step_name=step_name,
                        tool=tool,
                        order=len(nodes),
                        latency_ms=latency,
                        success=success,
                        metadata=metadata,
                    )
                )
                total_latency += latency

            elif ev_type_str == "EPOCH_CHANGED":
                epoch_count += 1
                if hasattr(event, 'payload'):
                    new_epoch = event.payload.get("new_epoch", 0)
                else:
                    new_epoch = event.get("payload", {}).get("new_epoch", 0)
                if new_epoch not in seen_epochs:
                    seen_epochs.add(new_epoch)

        if not nodes:
            return None

        return DAGSkeleton(
            source_task_id=source_task_id,
            goal=goal_embedding,
            outcome=outcome,
            similarity=similarity,
            nodes=nodes,
            total_latency_ms=total_latency,
            epoch_count=epoch_count or 1,
        )

    def _get_task_events_sync(self, task_id: str) -> list:
        """Sync bridge to event_store async method."""
        import asyncio
        return asyncio.run(self._es.get_all_events(task_id))

    # ── adaptation hints ─────────────────────────────────────────────────────

    def _generate_adaptation_notes(self, skeleton: DAGSkeleton) -> list[str]:
        """Generate human-readable notes for how to adapt this skeleton."""
        notes: list[str] = []

        tools = [n.tool for n in skeleton.nodes]
        unique_tools = set(tools)

        if len(skeleton.nodes) > 10:
            notes.append(f"Large DAG: {len(skeleton.nodes)} steps — consider parallelization")

        if "bash" in unique_tools or "shell" in unique_tools:
            notes.append("Uses shell commands — verify environment compatibility")

        if "http" in unique_tools or "api" in unique_tools:
            notes.append("Uses HTTP calls — check endpoint availability")

        if skeleton.total_latency_ms > 60_000:
            notes.append(
                f"High latency plan ({skeleton.total_latency_ms/1000:.0f}s) — "
                "review step dependencies"
            )

        if skeleton.epoch_count > 1:
            notes.append(f"Multi-epoch plan ({skeleton.epoch_count} epochs) — stateful task")

        notes.append(f"Tool mix: {', '.join(sorted(unique_tools))}")

        return notes
