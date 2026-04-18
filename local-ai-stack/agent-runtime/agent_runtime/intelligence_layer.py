"""
v4 Intelligence Layer Orchestrator.

Ties together:
- ModelRouter (model selection + fallback chains)
- ToolPolicy (tool scoring + dynamic routing)
- MemoryFeedbackLoop (DAG → embeddings → pattern reuse)

Provides:
- intelligent_run() — full pipeline with all intelligence layers
- plan_with_intelligence() — LLM planning enriched with memory
- tool_selection_policy() — tool routing with scores
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Optional

from .model_router import (
    route, RoutingContext, RoutingDecision,
    call_with_fallback, classify_task_complexity, estimate_tokens,
    ModelTier,
)
from .tool_policy import (
    select_best_tools, record_tool_call, get_tool_policy_summary,
    ToolCategory,
)
from .memory_feedback import (
    MemoryFeedbackLoop, learn_from_dag, get_cached_tool_sequence,
)


# ── shared singleton ───────────────────────────────────────────────────────────

_feedback_loop: Optional[MemoryFeedbackLoop] = None


def get_feedback_loop() -> MemoryFeedbackLoop:
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = MemoryFeedbackLoop()
    return _feedback_loop


# ── intelligent planner ────────────────────────────────────────────────────────

async def plan_with_intelligence(task: str) -> list[dict]:
    """
    Generate execution plan with intelligence enrichment:
    1. Check memory for cached tool sequences
    2. Check similar past executions
    3. Use model router for complexity-aware planning
    4. Apply tool policy for best tool selection
    """
    feedback = get_feedback_loop()

    # 1. Try cached plan
    cached_seq = get_cached_tool_sequence(task, feedback)
    tokens = estimate_tokens(task)
    complexity = classify_task_complexity(task)

    # 2. Get routing decision
    routing_ctx = RoutingContext(
        task=task,
        estimated_tokens=tokens,
        prefer_fast=(complexity == "simple"),
    )
    routing = await route(routing_ctx)

    # 3. Select best tools
    best_tools = await select_best_tools(task)
    tool_str = ", ".join(best_tools)

    # 4. Build enriched prompt for planning
    memory_hints = ""
    similar = feedback.get_similar_past(task, top_k=2)
    if similar:
        memory_hints = "\nSimilar past successful patterns:\n"
        for frag, score in similar:
            if frag.fragment_type in ("success_pattern", "tool_sequence"):
                memory_hints += f"- [{frag.fragment_type}] {frag.content[:100]} (tools: {frag.tool_sequence})\n"

    planning_prompt = (
        f"You are a task planner. Task: {task}\n\n"
        f"Complexity: {complexity} | Est tokens: {tokens}\n"
        f"Recommended model tier: {routing.tier.value} ({routing.selected_model})\n"
        f"Best tools: {tool_str}\n"
        f"{memory_hints}"
        f"Return a JSON array of steps. Each step: {{\"id\", \"tool\", \"action\", \"params\"}}\n"
        f"Prefer tool sequence: {cached_seq if cached_seq else best_tools[:3]}\n"
        f"Respond with valid JSON only."
    )

    # 5. Call LLM with fallback
    result = await call_with_fallback(task, routing, prompt_template="{task}")

    if not result.get("success"):
        return [{"id": "step_1", "tool": "llm", "action": "respond", "params": {"prompt": task}}]

    try:
        raw = result["response"]
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
        steps = json.loads(raw)
        if isinstance(steps, dict):
            steps = steps.get("steps", [steps])

        # 6. Enrich steps with tool policy scores
        for step in steps:
            tool = step.get("tool", "llm")
            scores = await get_tool_policy_summary()
            tool_score = scores.get(tool, {}).get("score", 0.5)
            step["_tool_score"] = tool_score
            step["_routing"] = {
                "model": routing.selected_model,
                "tier": routing.tier.value,
            }

        return steps
    except Exception as exc:
        return [{"id": "step_1", "tool": "llm", "action": "respond", "params": {"prompt": task}}]


# ── intelligent execution ─────────────────────────────────────────────────────

async def intelligent_run(
    task: str,
    context: Optional[dict] = None,
) -> dict:
    """
    Full intelligent execution pipeline (v4):

    1. plan_with_intelligence() — model routing + memory + tool policy
    2. Execute steps with tool call recording
    3. Learn from DAG trace → memory feedback loop
    4. Return result + intelligence metadata
    """
    feedback = get_feedback_loop()
    task_id = context.get("task_id", "unknown") if context else "unknown"

    # ── planning ──────────────────────────────────────────────────────────────
    plan_start = time.monotonic()
    steps = await plan_with_intelligence(task)
    plan_time_ms = (time.monotonic() - plan_start) * 1000

    # ── execution ───────────────────────────────────────────────────────────
    from .async_engine import run_step_with_trace  # avoid circular

    # Get DAG ID from context or create
    dag_id = context.get("dag_id", f"intl_{task_id}") if context else f"intl_{task_id}"

    # If cached sequence exists, inject it as first step guidance
    cached_seq = get_cached_tool_sequence(task, feedback)
    if cached_seq:
        steps.insert(0, {
            "id": "step_cached",
            "tool": "memory",
            "action": "cached_plan_reuse",
            "params": {"sequence": cached_seq},
            "_is_cached": True,
        })

    results = []
    tool_call_times: dict[str, float] = {}

    for step in steps:
        step_id = step.get("id", "")
        tool = step.get("tool", "llm")

        # Tool policy: check if tool is healthy before executing
        if tool != "memory":
            scores = await get_tool_policy_summary()
            tool_stats = scores.get(tool, {})
            if not tool_stats.get("is_healthy", True) and tool_stats.get("recent_failures", 0) >= 3:
                # Fallback: try LLM instead
                step = {**step, "tool": "llm", "_fallback_from": tool}
                tool = "llm"

        exec_start = time.monotonic()

        try:
            result = await run_step_with_trace(step, dag_id, task_id)
            exec_time_ms = (time.monotonic() - exec_start) * 1000

            # Record tool performance
            success = "error" not in result
            await record_tool_call(tool, success=success, latency_ms=exec_time_ms)
            tool_call_times[tool] = tool_call_times.get(tool, 0) + exec_time_ms

            results.append({"step": step_id, "tool": tool, "result": result, "latency_ms": exec_time_ms})

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            exec_time_ms = (time.monotonic() - exec_start) * 1000
            await record_tool_call(tool, success=False, latency_ms=exec_time_ms)
            results.append({
                "step": step_id,
                "tool": tool,
                "result": {"error": str(exc)},
                "latency_ms": exec_time_ms,
            })

    # ── learning from execution ──────────────────────────────────────────────
    total_time_ms = sum(r["latency_ms"] for r in results)

    dag_trace = {
        "task_id": task_id,
        "dag_id": dag_id,
        "step_count": len(steps),
        "top_latencies": [
            {"name": r["step"], "tool": r["tool"], "latency_ms": r["latency_ms"]}
            for r in sorted(results, key=lambda x: -x["latency_ms"])
        ],
        "failures": [
            {"step": r["step"], "tool": r["tool"], "error": r["result"].get("error", "")}
            for r in results if "error" in r["result"]
        ],
        "total_latency_ms": total_time_ms,
        "plan_time_ms": plan_time_ms,
    }

    await learn_from_dag(dag_trace, feedback)

    # ── intelligence metadata ─────────────────────────────────────────────────
    routing_ctx = RoutingContext(task=task, estimated_tokens=estimate_tokens(task))
    routing = await route(routing_ctx)
    tool_summary = await get_tool_policy_summary()

    return {
        "result": results,
        "dag_id": dag_id,
        "intelligence": {
            "model_routing": {
                "selected": routing.selected_model,
                "tier": routing.tier.value,
                "fallback_models": routing.fallback_models[:3],
                "routing_reason": routing.routing_reason,
            },
            "tool_policy": {
                "selected_tools": [s["tool"] for s in steps if s.get("tool") != "memory"],
                "tool_scores": {
                    t: {"score": v["score"], "is_healthy": v["is_healthy"]}
                    for t, v in tool_summary.items()
                },
            },
            "memory_feedback": {
                "cached_plan_used": cached_seq is not None,
                "similar_past_hits": len(similar) if similar else 0,
                "pattern_cache_entries": len(feedback.pattern_cache.get_all_patterns()),
            },
            "plan_time_ms": round(plan_time_ms, 1),
            "total_execution_time_ms": round(total_time_ms, 1),
        },
    }


# ── API endpoints for intelligence ───────────────────────────────────────────

async def get_intelligence_status() -> dict:
    """Return status of all intelligence layers."""
    feedback = get_feedback_loop()
    tool_summary = await get_tool_policy_summary()
    from .model_router import get_available_models
    available = await get_available_models()

    return {
        "model_router": {
            "available_models": available,
            "total_in_registry": len(import_module("agent_runtime.model_router").MODEL_REGISTRY)
                if "MODEL_REGISTRY" in dir() else 0,
        },
        "tool_policy": {
            "tools": tool_summary,
            "total_calls_recorded": sum(v["total_calls"] for v in tool_summary.values()),
        },
        "memory_feedback": feedback.get_stats(),
        "feedback_loop_active": _feedback_loop is not None,
    }


if __name__ == "__main__":
    async def demo():
        print("=== Intelligence Status ===")
        status = await get_intelligence_status()
        print(json.dumps(status, indent=2))

        print("\n=== Intelligent Plan for 'search logs for errors and fix them' ===")
        steps = await plan_with_intelligence("search logs for errors and fix them")
        print(json.dumps(steps, indent=2, default=str))

    import asyncio
    asyncio.run(demo())
