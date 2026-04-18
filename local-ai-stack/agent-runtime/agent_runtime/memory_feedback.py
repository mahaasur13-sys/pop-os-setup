"""
Memory Feedback Loop v4 — Intelligence Layer.

Execution → Memory learning:
- DAG traces → embeddings → vector store
- Failure patterns → compressed memory
- Execution history → pattern reuse
- Cross-task optimization via cached subgraphs

Components:
1. TraceExtractor: DAG → structured memory fragments
2. EmbeddingStore: store/retrieve via embeddings (simple TF-IDF or local model)
3. PatternCache: reusable execution subgraphs
4. FeedbackLoop: close the loop — trace results → memory → future planning
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ── simple embedding (TF-IDF fallback, no external deps) ────────────────────

def _tokenize(text: str) -> set[str]:
    """Simple whitespace tokenizer + lowercase."""
    return set(text.lower().split())


def _tfidf_vector(texts: list[str]) -> list[dict]:
    """
    Minimal TF-IDF: each text → {term: tf-idf weight}.
    Returns list of sparse vectors.
    """
    # document frequency
    docs = [_tokenize(t) for t in texts]
    N = len(docs)
    df = defaultdict(int)
    for tokens in docs:
        for t in tokens:
            df[t] += 1

    vectors = []
    for tokens in docs:
        tf = defaultdict(float)
        for t in tokens:
            tf[t] += 1
        # normalize + idf
        norm = max(1, sum(tf.values()))
        for t in tf:
            tf[t] = (tf[t] / norm) * (N / max(1, df[t]))
        vectors.append(dict(tf))
    return vectors


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = sum(a[k] ** 2 for k in a) ** 0.5
    norm_b = sum(b[k] ** 2 for k in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── trace extractor ───────────────────────────────────────────────────────────

@dataclass
class MemoryFragment:
    """A reusable memory chunk extracted from execution."""
    fragment_id: str
    fragment_type: str  # "success_pattern", "failure_pattern", "plan_template", "tool_sequence"
    task_hash: str  # hash of the original task
    content: str  # natural language description
    embedding: Optional[dict[str, float]] = None
    tool_sequence: list[str] = field(default_factory=list)
    success_rate: float = 1.0
    usage_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)
    avg_latency_ms: float = 0.0


class TraceExtractor:
    """
    Extract reusable memory fragments from DAG execution traces.
    
    Input: full DAG dict (from DAGRecorder.get_observability_report())
    Output: list of MemoryFragment
    """

    @staticmethod
    def extract(dag_trace: dict) -> list[MemoryFragment]:
        fragments = []
        task_id = dag_trace.get("task_id", "unknown")
        task_hash = hashlib.md5(task_id.encode()).hexdigest()[:12]

        # 1. Success pattern: if all steps succeeded
        failures = dag_trace.get("failures", [])
        successes = [s for s in dag_trace.get("step_count", []) if s not in failures]

        if not failures:
            # Full success → extract plan template
            frag = MemoryFragment(
                fragment_id=f"tmpl_{task_hash}",
                fragment_type="success_pattern",
                task_hash=task_hash,
                content=f"Task pattern for: {task_id[:80]}",
                tool_sequence=TraceExtractor._extract_tool_sequence(dag_trace),
                success_rate=1.0,
                avg_latency_ms=dag_trace.get("total_latency_ms", 0),
            )
            frag.embedding = None  # computed later
            fragments.append(frag)

        # 2. Failure pattern: cluster failures by step/tool
        tool_failures: dict[str, int] = defaultdict(int)
        for fail in failures:
            tool = fail.get("tool", "unknown")
            tool_failures[tool] += 1

        for tool, count in tool_failures.items():
            frag = MemoryFragment(
                fragment_id=f"fail_{tool}_{task_hash[:6]}",
                fragment_type="failure_pattern",
                task_hash=task_hash,
                content=f"Failure in {tool} (x{count}): {fail.get('error', 'unknown')}",
                tool_sequence=[tool],
                success_rate=0.0,
            )
            fragments.append(frag)

        # 3. Tool sequences: extract ordered tool chains
        tool_seq = TraceExtractor._extract_tool_sequence(dag_trace)
        if len(tool_seq) >= 2:
            seq_id = hashlib.md5("".join(tool_seq).encode()).hexdigest()[:8]
            frag = MemoryFragment(
                fragment_id=f"seq_{seq_id}",
                fragment_type="tool_sequence",
                task_hash=task_hash,
                content=f"Tool chain: {' → '.join(tool_seq)}",
                tool_sequence=tool_seq,
                success_rate=1.0 if not failures else 0.5,
                avg_latency_ms=dag_trace.get("total_latency_ms", 0),
            )
            fragments.append(frag)

        return fragments

    @staticmethod
    def _extract_tool_sequence(dag_trace: dict) -> list[str]:
        """Extract ordered list of tool names from DAG."""
        # In real impl, DAG has step_order. Here we reconstruct from top_latencies.
        top = dag_trace.get("top_latencies", [])
        return [s.get("tool", "unknown") for s in top]


# ── embedding store ───────────────────────────────────────────────────────────

class EmbeddingStore:
    """
    Simple in-memory vector store with TF-IDF embeddings.
    - store(fragment)
    - search(query, top_k) → list[MemoryFragment]
    - cosine similarity search
    """

    def __init__(self, max_fragments: int = 1000):
        self._fragments: list[MemoryFragment] = []
        self._corpus: list[str] = []
        self._vectors: list[dict[str, float]] = []
        self._max_fragments = max_fragments
        self._initialized = False

    def _reindex(self):
        """Recompute TF-IDF vectors for all fragments."""
        if not self._fragments:
            return
        self._vectors = _tfidf_vector([f.content for f in self._fragments])
        self._initialized = True

    def store(self, fragment: MemoryFragment):
        """Add fragment to store, re-index."""
        # update usage
        existing = next((f for f in self._fragments if f.fragment_id == fragment.fragment_id), None)
        if existing:
            existing.usage_count += 1
            existing.last_accessed = time.monotonic()
            return

        if len(self._fragments) >= self._max_fragments:
            # evict least-used
            self._fragments.sort(key=lambda f: (f.last_accessed, f.usage_count))
            self._fragments = self._fragments[: self._max_fragments // 2]
            self._initialized = False

        self._fragments.append(fragment)
        self._initialized = False  # need reindex

    def search(self, query: str, top_k: int = 5) -> list[tuple[MemoryFragment, float]]:
        """
        Semantic search: embed query, cosine similarity against all fragments.
        Returns top-k fragments with scores.
        """
        if not self._fragments:
            return []

        if not self._initialized:
            self._reindex()

        # embed query
        query_tokens = _tokenize(query)
        # simple TF for query (no IDF since it's just 1 doc)
        tf = defaultdict(float)
        for t in query_tokens:
            tf[t] += 1
        norm = max(1, sum(tf.values()))
        for t in tf:
            tf[t] /= norm
        query_vec = dict(tf)

        # score against all
        scored: list[tuple[MemoryFragment, float]] = []
        for frag, vec in zip(self._fragments, self._vectors):
            sim = cosine_similarity(query_vec, vec)
            if sim > 0.01:  # threshold
                scored.append((frag, sim))

        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def store_and_search(self, fragment: MemoryFragment, query: str, top_k: int = 5) -> list[tuple[MemoryFragment, float]]:
        """Store fragment then search for similar ones."""
        self.store(fragment)
        return self.search(query, top_k)

    def get_stats(self) -> dict:
        """Return store statistics."""
        type_counts = defaultdict(int)
        for f in self._fragments:
            type_counts[f.fragment_type] += 1
        return {
            "total_fragments": len(self._fragments),
            "by_type": dict(type_counts),
            "max_capacity": self._max_fragments,
        }


# ── pattern cache ─────────────────────────────────────────────────────────────

class PatternCache:
    """
    Cache reusable execution subgraphs (tool sequences) for cross-task optimization.
    Key insight: if a tool sequence worked for task type X, reuse it for similar tasks.
    
    - learn(fragment) → store pattern
    - lookup(task_type) → cached tool sequence or None
    """

    def __init__(self):
        self._patterns: dict[str, list[tuple[list[str], float, int]]] = defaultdict(list)
        # key: task_type_hash → list of (tool_sequence, success_rate, usage_count)

    def _task_type(self, task: str) -> str:
        """Infer task type from task string."""
        t = task.lower()
        if "search" in t or "find" in t:
            return "search"
        if "write" in t or "code" in t or "generate" in t:
            return "code_generation"
        if "plan" in t or "analyze" in t or "reason" in t:
            return "reasoning"
        if "read" in t or "extract" in t:
            return "read"
        if "classify" in t or "categorize" in t:
            return "classification"
        return "general"

    def learn(self, tool_sequence: list[str], task: str, success_rate: float):
        """Learn a tool sequence pattern for a task type."""
        task_type = self._task_type(task)
        entry = (tool_sequence, success_rate, 1)

        existing = self._patterns[task_type]
        # deduplicate
        for i, (seq, sr, count) in enumerate(existing):
            if seq == tool_sequence:
                existing[i] = (seq, (sr * count + success_rate) / (count + 1), count + 1)
                return
        existing.append(entry)

    def lookup(self, task: str) -> Optional[list[str]]:
        """Get best tool sequence for task type."""
        task_type = self._task_type(task)
        patterns = self._patterns.get(task_type, [])

        if not patterns:
            return None

        # return best (highest success_rate, then most used)
        patterns.sort(key=lambda x: (-x[1], -x[2]))
        return patterns[0][0] if patterns else None

    def get_all_patterns(self) -> dict:
        """Return all learned patterns."""
        return dict(self._patterns)


# ── main feedback loop ────────────────────────────────────────────────────────

class MemoryFeedbackLoop:
    """
    Orchestrates: TraceExtractor → EmbeddingStore + PatternCache → future planning.

    Usage:
        loop = MemoryFeedbackLoop()
        await loop.ingest(dag_trace)           # learn from execution
        cached_seq = loop.get_cached_plan(task)  # reuse in future
    """

    def __init__(self):
        self.store = EmbeddingStore(max_fragments=1000)
        self.pattern_cache = PatternCache()

    async def ingest(self, dag_trace: dict):
        """
        Ingest a completed DAG trace:
        1. Extract fragments (patterns, failures, sequences)
        2. Store embeddings
        3. Update pattern cache
        """
        fragments = TraceExtractor.extract(dag_trace)
        for frag in fragments:
            self.store.store(frag)
            if frag.tool_sequence and frag.fragment_type in ("success_pattern", "tool_sequence"):
                self.pattern_cache.learn(
                    tool_sequence=frag.tool_sequence,
                    task=dag_trace.get("task_id", ""),
                    success_rate=frag.success_rate,
                )

    def get_cached_plan(self, task: str) -> Optional[list[str]]:
        """Get a cached tool sequence for this task type."""
        return self.pattern_cache.lookup(task)

    def get_similar_past(self, query: str, top_k: int = 3) -> list[tuple[MemoryFragment, float]]:
        """Search past fragments for similar tasks."""
        return self.store.search(query, top_k)

    def get_stats(self) -> dict:
        return {
            "embedding_store": self.store.get_stats(),
            "pattern_cache": {k: len(v) for k, v in self.pattern_cache.get_all_patterns().items()},
        }


# ── integration with engine ───────────────────────────────────────────────────

async def learn_from_dag(dag_trace: dict, feedback_loop: MemoryFeedbackLoop):
    """Integrate DAG learning into engine (called after dag.finalize())."""
    await feedback_loop.ingest(dag_trace)


def get_cached_tool_sequence(task: str, feedback_loop: MemoryFeedbackLoop) -> Optional[list[str]]:
    """Pre-populate step planning with cached sequence."""
    cached = feedback_loop.get_cached_plan(task)
    if cached:
        return cached
    # Also check semantic similarity
    similar = feedback_loop.get_similar_past(task, top_k=1)
    if similar:
        best_frag, score = similar[0]
        if score > 0.3 and best_frag.tool_sequence:
            return best_frag.tool_sequence
    return None


# ── test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def test():
        loop = MemoryFeedbackLoop()

        # Simulate DAG traces
        traces = [
            {
                "task_id": "search_and_write_code",
                "step_count": 4,
                "top_latencies": [
                    {"tool": "shell", "latency_ms": 30, "name": "grep"},
                    {"tool": "llm", "latency_ms": 200, "name": "generate"},
                    {"tool": "shell", "latency_ms": 10, "name": "write"},
                ],
                "failures": [],
                "total_latency_ms": 240,
            },
            {
                "task_id": "reasoning_task",
                "step_count": 2,
                "top_latencies": [
                    {"tool": "llm", "latency_ms": 800, "name": "think"},
                    {"tool": "llm", "latency_ms": 150, "name": "respond"},
                ],
                "failures": [],
                "total_latency_ms": 950,
            },
        ]

        for t in traces:
            await loop.ingest(t)

        print("=== Stats ===")
        stats = loop.get_stats()
        print(json.dumps(stats, indent=2))

        print("\n=== Cached plan for 'find and write code' ===")
        cached = loop.get_cached_plan("find and write code")
        print(f"Tool sequence: {cached}")

        print("\n=== Similar past for 'search logs and fix bug' ===")
        similar = loop.get_similar_past("search logs and fix bug", top_k=3)
        for frag, score in similar:
            print(f"  score={score:.3f} type={frag.fragment_type} content={frag.content[:60]} tools={frag.tool_sequence}")

    asyncio.run(test())
