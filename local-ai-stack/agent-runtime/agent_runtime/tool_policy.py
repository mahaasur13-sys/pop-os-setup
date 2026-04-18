"""
Tool Policy Engine v4 — Intelligence Layer.

Responsibilities:
- Tool scoring based on success history
- Dynamic tool selection policy
- Tool failure learning
- Cost-latency scoring per tool
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = "http://localhost:6379"
TOOL_STATS_KEY = "tool:stats"
TOOL_POLICY_KEY = "tool:policy"


class ToolCategory(Enum):
    LLM = "llm"
    SHELL = "shell"
    FILESYSTEM = "filesystem"
    MEMORY = "memory"
    HTTP = "http"
    EXTERNAL = "external"


@dataclass
class ToolConfig:
    name: str
    category: ToolCategory
    max_retries: int = 3
    timeout_ms: int = 30000
    cost_score: float = 0.0  # relative cost (0=free)
    latency_score: float = 1.0  # relative latency multiplier


TOOL_REGISTRY: dict[str, ToolConfig] = {
    "llm": ToolConfig(name="llm", category=ToolCategory.LLM, max_retries=3, timeout_ms=60000, cost_score=1.0, latency_score=1.0),
    "shell": ToolConfig(name="shell", category=ToolCategory.SHELL, max_retries=2, timeout_ms=30000, cost_score=0.0, latency_score=0.5),
    "memory": ToolConfig(name="memory", category=ToolCategory.MEMORY, max_retries=1, timeout_ms=5000, cost_score=0.0, latency_score=0.1),
    "http": ToolConfig(name="http", category=ToolCategory.HTTP, max_retries=3, timeout_ms=15000, cost_score=0.1, latency_score=0.8),
    "rag": ToolConfig(name="rag", category=ToolCategory.MEMORY, max_retries=2, timeout_ms=10000, cost_score=0.2, latency_score=0.6),
    "code": ToolConfig(name="code", category=ToolCategory.EXTERNAL, max_retries=1, timeout_ms=5000, cost_score=0.0, latency_score=0.3),
}


@dataclass
class ToolScore:
    tool: str
    success_rate: float  # 0.0 - 1.0
    avg_latency_ms: float
    total_calls: int
    recent_failures: int
    score: float  # composite: success_rate / (1 + latency_factor + cost_factor)
    last_used_ts: float
    is_healthy: bool


# ── in-memory rolling stats (no Redis yet) ────────────────────────────────────

_stats: dict[str, dict] = defaultdict(lambda: {
    "total": 0,
    "success": 0,
    "failure": 0,
    "total_latency_ms": 0.0,
    "recent_failures": 0,  # rolling window (last 10 calls)
    "last_used": 0.0,
    "failure_timestamps": [],  # for rolling window
})


async def record_tool_call(tool: str, success: bool, latency_ms: float):
    """Record a tool call result for scoring."""
    now = time.monotonic()
    s = _stats[tool]
    s["total"] += 1
    s["total_latency_ms"] += latency_ms
    s["last_used"] = now

    if success:
        s["success"] += 1
    else:
        s["failure"] += 1
        s["recent_failures"] += 1
        s["failure_timestamps"].append(now)

    # rolling window: keep only failures in last 60 seconds
    cutoff = now - 60.0
    s["failure_timestamps"] = [ts for ts in s["failure_timestamps"] if ts > cutoff]
    s["recent_failures"] = len(s["failure_timestamps"])

    # persist to Redis if available
    try:
        r = await aioredis.from_url(REDIS_URL)
        key = f"{TOOL_STATS_KEY}:{tool}"
        import json
        await r.hset(key, mapping={
            "total": str(s["total"]),
            "success": str(s["success"]),
            "failure": str(s["failure"]),
            "total_latency_ms": str(s["total_latency_ms"]),
            "recent_failures": str(s["recent_failures"]),
            "last_used": str(s["last_used"]),
        })
        await r.expire(key, 86400)
        await r.aclose()
    except Exception:
        pass


def compute_tool_score(tool: str) -> ToolScore:
    """Compute composite tool score from rolling stats."""
    s = _stats.get(tool, _stats[tool])
    cfg = TOOL_REGISTRY.get(tool, ToolConfig(name=tool, category=ToolCategory.EXTERNAL))

    total = max(1, s["total"])
    success_rate = s["success"] / total
    avg_latency_ms = s["total_latency_ms"] / total if total > 0 else cfg.timeout_ms

    # composite score: success_rate weighted by recency + latency + cost
    latency_factor = avg_latency_ms / cfg.timeout_ms
    cost_factor = cfg.cost_score

    # Penalize recent failures heavily
    recent_failure_penalty = min(1.0, s["recent_failures"] / 5.0)

    score = (success_rate * 0.6) + (0.3 * (1 - latency_factor)) + (0.1 * (1 - cost_factor))
    score *= (1.0 - recent_failure_penalty * 0.5)  # up to -50% for failures

    # health check: tool is unhealthy if >50% failures in rolling window
    is_healthy = s["recent_failures"] < 5 or (s["recent_failures"] / max(1, total)) < 0.5

    return ToolScore(
        tool=tool,
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        total_calls=total,
        recent_failures=s["recent_failures"],
        score=max(0.0, score),
        last_used_ts=s["last_used"],
        is_healthy=is_healthy,
    )


async def select_best_tools(task: str, required_categories: list[ToolCategory] = None) -> list[str]:
    """
    Select best tools for a task based on:
    1. Required tool categories
    2. Tool health (exclude unhealthy)
    3. Composite score
    4. Category diversity
    """
    task_lower = task.lower()

    # Infer required categories from task
    if required_categories is None:
        required_categories = []
        if any(k in task_lower for k in ["write", "edit", "code", "python", "script"]):
            required_categories.append(ToolCategory.SHELL)
        if any(k in task_lower for k in ["search", "find", "lookup", "query", "rag"]):
            required_categories.append(ToolCategory.MEMORY)
        if any(k in task_lower for k in ["http", "fetch", "api", "request", "url"]):
            required_categories.append(ToolCategory.HTTP)
        if any(k in task_lower for k in ["reason", "plan", "analyze", "think", "decide"]):
            required_categories.append(ToolCategory.LLM)

    # If no categories inferred, default to LLM
    if not required_categories:
        required_categories = [ToolCategory.LLM]

    # Score all registered tools
    candidates = []
    for name, cfg in TOOL_REGISTRY.items():
        if required_categories and cfg.category not in required_categories:
            continue
        score = compute_tool_score(name)
        if not score.is_healthy and score.recent_failures >= 3:
            continue  # skip unhealthy tools
        candidates.append((name, score.score))

    # Sort by score descending
    candidates.sort(key=lambda x: -x[1])

    # Return top tools, ensuring category diversity
    selected: list[str] = []
    seen_categories: set[ToolCategory] = set()

    for name, _ in candidates:
        cfg = TOOL_REGISTRY[name]
        if cfg.category not in seen_categories or cfg.category == ToolCategory.LLM:
            selected.append(name)
            seen_categories.add(cfg.category)
            if len(selected) >= 4:  # max 4 tools
                break

    # Ensure LLM is always present
    if "llm" not in selected:
        selected.insert(0, "llm")

    return selected


async def get_tool_policy_summary() -> dict:
    """Return current tool scores and health status."""
    summary = {}
    for tool in TOOL_REGISTRY:
        score = compute_tool_score(tool)
        summary[tool] = {
            "success_rate": round(score.success_rate, 3),
            "avg_latency_ms": round(score.avg_latency_ms, 1),
            "total_calls": score.total_calls,
            "recent_failures": score.recent_failures,
            "score": round(score.score, 3),
            "is_healthy": score.is_healthy,
            "last_used": score.last_used_ts,
        }
    return summary


async def reset_tool_stats(tool: Optional[str] = None):
    """Reset stats for a specific tool or all tools."""
    if tool:
        _stats[tool] = _stats[tool] = defaultdict(lambda: {
            "total": 0, "success": 0, "failure": 0,
            "total_latency_ms": 0.0, "recent_failures": 0,
            "last_used": 0.0, "failure_timestamps": [],
        })
    else:
        _stats.clear()


if __name__ == "__main__":
    import asyncio

    async def test():
        # Simulate some calls
        for i in range(20):
            await record_tool_call("llm", success=(i % 10 != 0), latency_ms=120 + (i % 5) * 10)
            await record_tool_call("shell", success=(i % 8 != 0), latency_ms=30 + i % 10)
            await record_tool_call("rag", success=(i % 3 != 0), latency_ms=50 + i % 5)

        print("=== Tool Policy Summary ===")
        summary = await get_tool_policy_summary()
        for tool, stats in summary.items():
            health = "✅" if stats["is_healthy"] else "❌"
            print(f"{health} {tool}: sr={stats['success_rate']} lat={stats['avg_latency_ms']:.0f}ms "
                  f"calls={stats['total_calls']} score={stats['score']}")

        print("\n=== Best tools for task ===")
        print("'search in files and write code':", await select_best_tools("search in files and write code"))
        print("'reason about strategy':", await select_best_tools("reason about strategy"))
        print("'fetch data from URL':", await select_best_tools("fetch data from URL"))

    asyncio.run(test())
