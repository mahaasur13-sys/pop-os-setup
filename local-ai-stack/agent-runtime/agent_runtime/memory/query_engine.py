"""
SemanticQueryEngine — read-side intelligence: semantic retrieval from vector store.

Provides:
    - find_similar_tasks(task_id, top_k)         — find tasks with similar execution traces
    - find_failure_patterns(error_signature)     — find past failure traces by error behavior
    - retrieve_execution_plans(goal_embedding)   — find reusable DAG skeletons
    - cluster_task_histories()                   — group tasks by behavioral similarity
    - search_events(query_text, top_k)           — semantic search over all events

Design:
    This is the read leg of CQRS.
    It queries the vector store without touching event_store write path.
    All queries are event-type filtered and metadata-annotated.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.memory.vector_adapter import VectorAdapter, get_backend
from agent_runtime.memory.semantic_projector import _load_embedding_model


@dataclass
class TaskSimilarityResult:
    task_id: str
    similarity: float
    event_type: str
    epoch: int
    event_id: str
    text_repr: str


@dataclass
class FailurePatternResult:
    task_id: str
    similarity: float
    error_signature: str
    event_type: str
    text_repr: str


@dataclass
class ExecutionPlanResult:
    task_id: str
    similarity: float
    goal: str
    outcome: str | None


class SemanticQueryEngine:
    """
    Read-side semantic query engine.

    Usage:
        engine = SemanticQueryEngine()
        results = engine.find_similar_tasks(task_id="task-42", top_k=5)
        plans = engine.retrieve_execution_plans(goal="deploy to kubernetes")
    """

    def __init__(self, vector_adapter: VectorAdapter | None = None) -> None:
        self._adapter = vector_adapter or get_backend()

    @property
    def adapter(self) -> VectorAdapter:
        return self._adapter

    def _embed(self, text: str) -> list[float]:
        model = _load_embedding_model()
        return model.encode(text, normalize_embeddings=True).tolist()

    # ——— Core queries ———

    def search_events(
        self,
        query_text: str,
        top_k: int = 5,
        event_type_filter: str | None = None,
    ) -> list[TaskSimilarityResult]:
        """
        Semantic search over all projected events.
        Optionally filter by event_type.
        """
        vector = self._embed(query_text)
        entries = self._adapter.query(vector, top_k=top_k * 3)

        results = []
        for entry in entries:
            if (
                event_type_filter
                and entry.metadata.get("event_type") != event_type_filter
            ):
                continue
            results.append(
                TaskSimilarityResult(
                    task_id=entry.metadata.get("task_id", ""),
                    similarity=0.0,  # cosine already computed implicitly by adapter
                    event_type=entry.metadata.get("event_type", ""),
                    epoch=entry.metadata.get("epoch", 0),
                    event_id=entry.metadata.get("event_id", entry.id),
                    text_repr=entry.metadata.get("text_repr", ""),
                )
            )
            if len(results) >= top_k:
                break
        return results

    def find_similar_tasks(
        self,
        task_id: str,
        top_k: int = 5,
        event_type_filter: str | None = None,
    ) -> list[TaskSimilarityResult]:
        """
        Find events from other tasks that are semantically similar to events in task_id.
        Useful for: "has this kind of execution happened before?"
        """
        # Find all entries for the given task_id
        all_entries = self._adapter.query(
            vector=[0.0] * 384,  # dummy — we filter by metadata below
            top_k=self._adapter.count() or 100,
        )
        task_entries = [e for e in all_entries if e.metadata.get("task_id") == task_id]
        if not task_entries:
            return []

        # Average embedding of task events as task signature
        import numpy as np

        task_vector = np.mean([e.vector for e in task_entries], axis=0).tolist()

        # Query similar
        similar_entries = self._adapter.query(task_vector, top_k=top_k * 2)
        results = []
        seen_tasks: set[str] = set()
        for entry in similar_entries:
            tid = entry.metadata.get("task_id", "")
            if tid == task_id or tid in seen_tasks:
                continue
            if (
                event_type_filter
                and entry.metadata.get("event_type") != event_type_filter
            ):
                continue
            seen_tasks.add(tid)
            results.append(
                TaskSimilarityResult(
                    task_id=tid,
                    similarity=0.0,
                    event_type=entry.metadata.get("event_type", ""),
                    epoch=entry.metadata.get("epoch", 0),
                    event_id=entry.metadata.get("event_id", entry.id),
                    text_repr=entry.metadata.get("text_repr", ""),
                )
            )
            if len(results) >= top_k:
                break
        return results

    def find_failure_patterns(
        self,
        error_signature: str,
        top_k: int = 5,
    ) -> list[FailurePatternResult]:
        """
        Find past failure traces that match the given error behavior.
        error_signature is a semantic description of the failure pattern
        (e.g., "tool timeout after retry exhaustion").
        """
        vector = self._embed(error_signature)
        entries = self._adapter.query(vector, top_k=top_k * 2)

        results = []
        for entry in entries:
            event_type = entry.metadata.get("event_type", "")
            # Focus on error/failure event types
            if "ERROR" in event_type.upper() or "FAIL" in event_type.upper():
                results.append(
                    FailurePatternResult(
                        task_id=entry.metadata.get("task_id", ""),
                        similarity=0.0,
                        error_signature=event_type,
                        event_type=event_type,
                        text_repr=entry.metadata.get("text_repr", ""),
                    )
                )
            if len(results) >= top_k:
                break
        return results

    def retrieve_execution_plans(
        self,
        goal: str,
        top_k: int = 5,
    ) -> list[ExecutionPlanResult]:
        """
        Find past task summaries with similar goals.
        Used for plan reuse: retrieve DAG skeletons from similar past executions.
        """
        vector = self._embed(goal)
        entries = self._adapter.query(vector, top_k=top_k * 2)

        results = []
        for entry in entries:
            if entry.metadata.get("event_type") != "TASK_SUMMARY":
                continue
            results.append(
                ExecutionPlanResult(
                    task_id=entry.metadata.get("task_id", ""),
                    similarity=0.0,
                    goal=entry.metadata.get("goal", ""),
                    outcome=entry.metadata.get("outcome"),
                )
            )
            if len(results) >= top_k:
                break
        return results

    def cluster_task_histories(
        self,
        min_similarity: float = 0.85,
        max_clusters: int = 50,
    ) -> dict[str, list[str]]:
        """
        Group tasks by behavioral similarity (cosine > min_similarity).
        Returns: {centroid_task_id: [task_id, ...]}

        Algorithm: greedy clustering — pick first unclustered task as centroid,
        assign all tasks with similarity > threshold to its cluster.
        """
        import numpy as np

        all_entries = self._adapter.query(
            vector=[0.0] * 384,
            top_k=self._adapter.count() or 100,
        )

        # Collect unique task_id → avg embedding
        task_vectors: dict[str, list[float]] = {}
        for entry in all_entries:
            tid = entry.metadata.get("task_id", "")
            if tid not in task_vectors:
                task_vectors[tid] = []
            task_vectors[tid].append(entry.vector)

        if not task_vectors:
            return {}

        task_avg: dict[str, np.ndarray] = {
            tid: np.mean(vectors, axis=0) for tid, vectors in task_vectors.items()
        }

        clusters: dict[str, list[str]] = {}
        assigned: set[str] = set()

        for tid, vec in task_avg.items():
            if tid in assigned:
                continue
            cluster = [tid]
            assigned.add(tid)
            for other_tid, other_vec in task_avg.items():
                if other_tid in assigned:
                    continue
                cos = float(
                    np.dot(vec, other_vec)
                    / (np.linalg.norm(vec) * np.linalg.norm(other_vec) + 1e-9)
                )
                if cos >= min_similarity:
                    cluster.append(other_tid)
                    assigned.add(other_tid)
            if len(cluster) > 1:
                clusters[tid] = cluster
            if len(clusters) >= max_clusters:
                break

        return clusters

    def get_task_vector(self, task_id: str) -> list[float] | None:
        """Return average embedding vector for a task (for manual similarity ops)."""
        import numpy as np

        all_entries = self._adapter.query(
            vector=[0.0] * 384,
            top_k=self._adapter.count() or 100,
        )
        task_entries = [e for e in all_entries if e.metadata.get("task_id") == task_id]
        if not task_entries:
            return None
        return np.mean([e.vector for e in task_entries], axis=0).tolist()

    def close(self) -> None:
        self._adapter.close()
