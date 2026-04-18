"""
Model Router v4 — Intelligence Layer.

Routing decisions based on:
- task complexity (token estimation)
- latency constraints
- cost constraints
- model availability
- fallback chains

Models:
- fast: llama3.2:latest (low latency, low cost)
- reasoner: deepseek-r1:7b (high reasoning, high latency)
- frontier: ollama directly (if available)
- fallback: sequential fallback chain
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiohttp

OLLAMA_URL = "http://localhost:11434"


class ModelTier(Enum):
    FAST = "fast"
    REASONER = "reasoner"
    FRONTIER = "frontier"


@dataclass
class ModelConfig:
    name: str
    tier: ModelTier
    latency_p50_ms: float
    cost_per_1k_tokens: float  # relative cost (fast=1.0)
    max_tokens: int = 8192
    supports_vision: bool = False
    supports_json: bool = True


# ── model registry ────────────────────────────────────────────────────────────

MODEL_REGISTRY: dict[str, ModelConfig] = {
    "llama3.2:latest": ModelConfig(
        name="llama3.2:latest",
        tier=ModelTier.FAST,
        latency_p50_ms=120,
        cost_per_1k_tokens=1.0,
    ),
    "llama3.2:3b": ModelConfig(
        name="llama3.2:3b",
        tier=ModelTier.FAST,
        latency_p50_ms=60,
        cost_per_1k_tokens=0.5,
    ),
    "deepseek-r1:7b": ModelConfig(
        name="deepseek-r1:7b",
        tier=ModelTier.REASONER,
        latency_p50_ms=800,
        cost_per_1k_tokens=2.5,
    ),
    "qwen2.5:14b": ModelConfig(
        name="qwen2.5:14b",
        tier=ModelTier.REASONER,
        latency_p50_ms=600,
        cost_per_1k_tokens=2.0,
    ),
    "mixtral:8x7b": ModelConfig(
        name="mixtral:8x7b",
        tier=ModelTier.FRONTIER,
        latency_p50_ms=1500,
        cost_per_1k_tokens=4.0,
    ),
}


@dataclass
class RoutingContext:
    task: str
    estimated_tokens: int = 0
    max_latency_ms: float = 0.0
    max_cost: float = 0.0
    prefer_fast: bool = False
    force_model: Optional[str] = None
    fallback_chain: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    selected_model: str
    tier: ModelTier
    estimated_latency_ms: float
    estimated_cost: float
    fallback_models: list[str]
    routing_reason: str


# ── availability check ─────────────────────────────────────────────────────────

_health_cache: dict[str, tuple[bool, float]] = {}
_HEALTH_CACHE_TTL = 30.0


async def is_model_available(model: str) -> bool:
    """Check if model is available with caching."""
    now = time.monotonic()
    if model in _health_cache:
        available, cached_at = _health_cache[model]
        if now - cached_at < _HEALTH_CACHE_TTL:
            return available

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OLLAMA_URL}/api/show", json={"name": model}, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                available = resp.status == 200
    except Exception:
        available = False

    _health_cache[model] = (available, now)
    return available


async def get_available_models() -> list[str]:
    """Return list of available model names."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OLLAMA_URL}/api/tags", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


# ── token estimation ──────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token average)."""
    return max(1, len(text) // 4)


# ── routing heuristics ────────────────────────────────────────────────────────

def classify_task_complexity(task: str) -> str:
    """
    Classify task into complexity buckets:
    - simple: factual Q&A, extraction, classification
    - moderate: summarization, rewriting, transformation
    - complex: reasoning, planning, code generation, multi-step
    """
    task_lower = task.lower()

    simple_indicators = [
        "what is", "who is", "when did", "where is",
        "define", "find", "look up", "get", "list",
        "extract", "classify as", "count",
    ]
    complex_indicators = [
        "why", "how would", "analyze", "design", "plan",
        "implement", "develop", "optimize", "compare and contrast",
        "reason", "think through", "step by step",
        "write code", "generate", "architect",
    ]

    simple_score = sum(1 for ind in simple_indicators if ind in task_lower)
    complex_score = sum(1 for ind in complex_indicators if ind in task_lower)

    if complex_score > simple_score:
        return "complex"
    if simple_score > 0:
        return "simple"
    return "moderate"


# ── core routing ───────────────────────────────────────────────────────────────

async def route(context: RoutingContext) -> RoutingDecision:
    """
    Route task to optimal model based on constraints.

    Logic:
    1. If force_model → use it (no routing)
    2. If max_latency constraint → filter by latency
    3. If max_cost constraint → filter by cost
    4. If prefer_fast → bias to fast tier
    5. Complexity classification → select tier
    6. Build fallback chain from available models
    """
    # 1. force model
    if context.force_model:
        cfg = MODEL_REGISTRY.get(context.force_model)
        if cfg is None:
            cfg = ModelConfig(context.force_model, ModelTier.FAST, 200, 1.0)
        return RoutingDecision(
            selected_model=context.force_model,
            tier=cfg.tier,
            estimated_latency_ms=cfg.latency_p50_ms,
            estimated_cost=cfg.cost_per_1k_tokens * context.estimated_tokens / 1000,
            fallback_models=[m for m in MODEL_REGISTRY if m != context.force_model],
            routing_reason=f"forced: {context.force_model}",
        )

    # 2. build candidate list (filter by availability + constraints)
    estimated_tokens = context.estimated_tokens or estimate_tokens(context.task)
    complexity = classify_task_complexity(context.task)

    candidates: list[tuple[ModelConfig, float]] = []
    for name, cfg in MODEL_REGISTRY.items():
        if not await is_model_available(name):
            continue

        # latency filter
        if context.max_latency_ms > 0:
            if cfg.latency_p50_ms > context.max_latency_ms:
                continue

        # cost filter
        if context.max_cost > 0:
            est_cost = cfg.cost_per_1k_tokens * estimated_tokens / 1000
            if est_cost > context.max_cost:
                continue

        # complexity-based tier bias
        if complexity == "complex":
            tier_score = 1.0 if cfg.tier != ModelTier.FAST else 0.2
        elif complexity == "simple":
            tier_score = 1.0 if cfg.tier == ModelTier.FAST else 0.3
        else:
            tier_score = 1.0

        # prefer_fast bias
        if context.prefer_fast and cfg.tier == ModelTier.FAST:
            tier_score *= 2.0

        candidates.append((cfg, tier_score))

    if not candidates:
        # fallback: any available model
        available = await get_available_models()
        if available:
            chosen = available[0]
            cfg = MODEL_REGISTRY.get(chosen, ModelConfig(chosen, ModelTier.FAST, 200, 1.0))
            return RoutingDecision(
                selected_model=chosen,
                tier=cfg.tier,
                estimated_latency_ms=cfg.latency_p50_ms,
                estimated_cost=cfg.cost_per_1k_tokens * estimated_tokens / 1000,
                fallback_models=available[1:],
                routing_reason="fallback: no candidates matched constraints",
            )
        # last resort: llama3.2:latest
        return RoutingDecision(
            selected_model="llama3.2:latest",
            tier=ModelTier.FAST,
            estimated_latency_ms=200,
            estimated_cost=1.0 * estimated_tokens / 1000,
            fallback_models=[],
            routing_reason="last resort: no models available",
        )

    # sort by tier_score descending, then by cost ascending
    candidates.sort(key=lambda x: (-x[1], x[0].cost_per_1k_tokens))
    best_cfg, best_score = candidates[0]

    # build fallback chain: same tier, then next tier, then any
    fallback: list[str] = []
    for cfg, _ in candidates[1:]:
        fallback.append(cfg.name)

    routing_reason = (
        f"complexity={complexity} "
        f"prefer_fast={context.prefer_fast} "
        f"max_latency={context.max_latency_ms}ms "
        f"max_cost=${context.max_cost:.2f}"
    )

    est_cost = best_cfg.cost_per_1k_tokens * estimated_tokens / 1000
    est_latency = best_cfg.latency_p50_ms * (estimated_tokens / 1000)

    return RoutingDecision(
        selected_model=best_cfg.name,
        tier=best_cfg.tier,
        estimated_latency_ms=est_latency,
        estimated_cost=est_cost,
        fallback_models=fallback,
        routing_reason=routing_reason,
    )


# ── execution with fallback ───────────────────────────────────────────────────

async def call_with_fallback(
    task: str,
    routing: RoutingDecision,
    prompt_template: Optional[str] = None,
    **kwargs,
) -> dict:
    """
    Execute LLM call with automatic fallback on failure.
    Falls through routing.fallback_models if primary fails.
    """
    payload = {
        "prompt": prompt_template.format(task=task) if prompt_template else task,
        "stream": False,
    }
    payload.update(kwargs)

    tried: list[str] = []
    last_error: Optional[str] = None

    for model_name in [routing.selected_model] + routing.fallback_models:
        tried.append(model_name)
        payload["model"] = model_name

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OLLAMA_URL}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return {
                            "response": result.get("response", ""),
                            "model": model_name,
                            "tried_models": tried,
                            "success": True,
                        }
                    else:
                        last_error = f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            last_error = "timeout"
        except Exception as exc:
            last_error = str(exc)

    return {
        "error": f"all models failed. last error: {last_error}",
        "model": tried[-1] if tried else "none",
        "tried_models": tried,
        "success": False,
    }


# ── batch routing ──────────────────────────────────────────────────────────────

async def route_batch(contexts: list[RoutingContext]) -> list[RoutingDecision]:
    """Route multiple tasks concurrently."""
    return await asyncio.gather(*[route(c) for c in contexts])


# ── refresh health cache ─────────────────────────────────────────────────────

async def refresh_health_cache():
    """Force refresh of model availability cache."""
    _health_cache.clear()
    available = await get_available_models()
    for model in available:
        _health_cache[model] = (True, time.monotonic())


if __name__ == "__main__":
    async def test():
        await refresh_health_cache()
        available = await get_available_models()
        print(f"Available models: {available}")

        test_tasks = [
            "What is the capital of France?",
            "Analyze the trade-offs between microservices and monolith architectures for a startup with 5 engineers",
            "Write a Python function to calculate fibonacci numbers",
        ]

        for task in test_tasks:
            complexity = classify_task_complexity(task)
            tokens = estimate_tokens(task)
            ctx = RoutingContext(task=task, estimated_tokens=tokens, prefer_fast=False)
            decision = await route(ctx)
            print(f"\nTask: {task[:60]}...")
            print(f"  Complexity: {complexity}, Est tokens: {tokens}")
            print(f"  Selected: {decision.selected_model} ({decision.tier.value})")
            print(f"  Est latency: {decision.estimated_latency_ms:.0f}ms, cost: ${decision.estimated_cost:.4f}")
            print(f"  Reason: {decision.routing_reason}")
            print(f"  Fallback: {decision.fallback_models[:2]}")

    asyncio.run(test())
