"""
v4 INTELLIGENCE SYSTEM ORCHESTRATOR
═════════════════════════════════════

Layer Stack (complete):
─────────────────────────────────────────────────────────────
Layer 5: Application          (API, endpoints, user interface)
Layer 4: Intelligence        ◄ NEW: model_router + tool_policy + memory_feedback
Layer 3: Execution Control  (async_engine + DAGRecorder + HardCancellation)
Layer 2: Scheduling          (AdaptiveScheduler — Redis ZSET priority queue)
Layer 1: Runtime             (Ollama LLM + aiohttp + asyncio subprocess)
─────────────────────────────────────────────────────────────

Intelligence Layer Components:
─────────────────────────────────────────────────────────────
model_router.py
  ├── route()              — routing decision based on complexity/latency/cost
  ├── call_with_fallback() — sequential fallback chain across model tiers
  ├── classify_task_complexity() — simple / moderate / complex
  └── estimate_tokens()    — 4-char-per-token estimation

tool_policy.py
  ├── select_best_tools()  — dynamic tool selection with health filtering
  ├── record_tool_call()   — rolling success/latency scoring
  ├── compute_tool_score() — composite: success_rate + latency + cost + recency
  └── get_tool_policy_summary() — health dashboard

memory_feedback.py
  ├── TraceExtractor        — DAG → MemoryFragment (patterns, failures, sequences)
  ├── EmbeddingStore        — TF-IDF vector store (cosine similarity search)
  ├── PatternCache          — learn/lookup tool sequences by task type
  └── MemoryFeedbackLoop    — orchestrates full learning loop

intelligence_layer.py (orchestrator)
  ├── plan_with_intelligence() — model + tools + memory enriched planning
  ├── intelligent_run()        — full v4 pipeline with all intelligence
  └── get_intelligence_status() — observability dashboard
─────────────────────────────────────────────────────────────
"""

from .model_router import (
    route, RoutingContext, RoutingDecision,
    call_with_fallback, classify_task_complexity, estimate_tokens,
    ModelTier, ModelConfig, get_available_models, is_model_available,
)
from .tool_policy import (
    select_best_tools, record_tool_call, get_tool_policy_summary,
    ToolCategory, ToolConfig, TOOL_REGISTRY, compute_tool_score, ToolScore,
)
from .memory_feedback import (
    MemoryFeedbackLoop, learn_from_dag, get_cached_tool_sequence,
    TraceExtractor, MemoryFragment, EmbeddingStore, PatternCache,
)
from .intelligence_layer import (
    intelligent_run, plan_with_intelligence, get_feedback_loop,
    get_intelligence_status,
)

__all__ = [
    # model router
    "route", "RoutingContext", "RoutingDecision",
    "call_with_fallback", "classify_task_complexity", "estimate_tokens",
    "ModelTier", "ModelConfig", "get_available_models", "is_model_available",
    # tool policy
    "select_best_tools", "record_tool_call", "get_tool_policy_summary",
    "ToolCategory", "ToolConfig", "TOOL_REGISTRY", "compute_tool_score", "ToolScore",
    # memory feedback
    "MemoryFeedbackLoop", "learn_from_dag", "get_cached_tool_sequence",
    "TraceExtractor", "MemoryFragment", "EmbeddingStore", "PatternCache",
    # orchestrator
    "intelligent_run", "plan_with_intelligence", "get_feedback_loop",
    "get_intelligence_status",
]
