"""
Tests for agent-runtime memory subsystem (CQRS Semantic Projection Layer).

Run with: PYTHONPATH=/home/workspace/local-ai-stack/agent-runtime \
    pytest tests/test_memory.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ["AGENT_VECTOR_BACKEND"] = "inmemory"

from agent_runtime.memory.vector_adapter import (
    VectorEntry,
    InMemoryAdapter,
    get_backend,
)
from agent_runtime.memory.semantic_projector import SemanticProjector
from agent_runtime.memory.query_engine import (
    SemanticQueryEngine,
)


# ——— Fixtures ———

@pytest.fixture
def adapter() -> InMemoryAdapter:
    return InMemoryAdapter()


@pytest.fixture
def sample_event() -> dict:
    return {
        "event_id": "evt-001",
        "task_id": "task-42",
        "event_type": "TOOL_EXECUTION",
        "epoch": 1,
        "payload": {"tool": "bash", "command": "ls -la"},
    }


@pytest.fixture
def sample_events() -> list[dict]:
    return [
        {
            "event_id": f"evt-{i:03d}",
            "task_id": f"task-{i}",
            "event_type": "TOOL_EXECUTION",
            "epoch": i,
            "payload": {"tool": "bash", "command": f"cmd-{i}"},
        }
        for i in range(5)
    ]


@pytest.fixture
def mock_embed() -> MagicMock:
    mock_model = MagicMock()
    arr = MagicMock()
    arr.tolist.return_value = [0.1] * 384
    mock_model.encode.return_value = arr
    mock_model.get_sentence_embedding_dimension.return_value = 384
    return mock_model


# ——— vector_adapter tests ———

class TestInMemoryAdapter:
    def test_upsert_and_query(self, adapter: InMemoryAdapter) -> None:
        entry = VectorEntry(id="e1", vector=[1.0, 0.0, 0.0], metadata={"task_id": "t1"})
        adapter.upsert(entry)
        results = adapter.query([1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].id == "e1"

    def test_query_returns_top_k(self, adapter: InMemoryAdapter) -> None:
        for i in range(10):
            v = [1.0 if i == j else 0.0 for j in range(3)]
            adapter.upsert(VectorEntry(id=f"e{i}", vector=v, metadata={}))
        results = adapter.query([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_delete(self, adapter: InMemoryAdapter) -> None:
        adapter.upsert(VectorEntry(id="e1", vector=[1.0, 0.0], metadata={}))
        assert adapter.count() == 1
        adapter.delete("e1")
        assert adapter.count() == 0

    def test_dimension_mismatch_raises(self, adapter: InMemoryAdapter) -> None:
        adapter.upsert(VectorEntry(id="e1", vector=[1.0, 0.0], metadata={}))
        with pytest.raises(ValueError, match="Dimension mismatch"):
            adapter.upsert(VectorEntry(id="e2", vector=[1.0, 0.0, 0.0], metadata={}))

    def test_count(self, adapter: InMemoryAdapter) -> None:
        assert adapter.count() == 0
        adapter.upsert(VectorEntry(id="e1", vector=[1.0, 0.0], metadata={}))
        adapter.upsert(VectorEntry(id="e2", vector=[0.0, 1.0], metadata={}))
        assert adapter.count() == 2

    def test_upsert_batch(self, adapter: InMemoryAdapter) -> None:
        entries = [
            VectorEntry(id=f"e{i}", vector=[float(i), 0.0], metadata={"i": i})
            for i in range(3)
        ]
        adapter.upsert_batch(entries)
        assert adapter.count() == 3


class TestGetBackend:
    def test_inmemory_backend(self) -> None:
        with patch.dict(os.environ, {"AGENT_VECTOR_BACKEND": "inmemory"}):
            adapter = get_backend()
        assert isinstance(adapter, InMemoryAdapter)


# ——— semantic_projector tests ———

class TestSemanticProjector:
    def test_event_to_text_from_dict(self, adapter: InMemoryAdapter, sample_event: dict) -> None:
        projector = SemanticProjector(vector_adapter=adapter)
        text = projector._event_to_text(sample_event)
        assert "TOOL_EXECUTION" in text
        assert "task-42" in text

    def test_project_event_returns_entry_id(
        self, adapter: InMemoryAdapter, sample_event: dict, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            entry_id = projector.project_event(sample_event)
            assert isinstance(entry_id, str)
            assert len(entry_id) == 16

    def test_project_audit_trail(
        self, adapter: InMemoryAdapter, sample_events: list[dict], mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            entry_ids = projector.project_audit_trail("task-batch", sample_events)
            assert len(entry_ids) == 5

    def test_project_task_summary(
        self, adapter: InMemoryAdapter, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            entry_id = projector.project_task_summary(
                task_id="task-99",
                goal="deploy kubernetes cluster",
                final_state={"status": "success"},
                event_types=["TOOL_EXECUTION", "FINAL_STATE"],
            )
            assert isinstance(entry_id, str)
            assert adapter.count() == 1


# ——— query_engine tests ———

class TestSemanticQueryEngine:
    def test_search_events_returns_results(
        self, adapter: InMemoryAdapter, sample_event: dict, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            projector.project_event(sample_event)

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            engine = SemanticQueryEngine(vector_adapter=adapter)
            results = engine.search_events("tool execution bash", top_k=5)
            assert isinstance(results, list)

    def test_find_failure_patterns_filters_error_events(
        self, adapter: InMemoryAdapter, mock_embed: MagicMock
    ) -> None:
        error_event = {
            "event_id": "err-001",
            "task_id": "task-err",
            "event_type": "TOOL_ERROR",
            "epoch": 1,
            "payload": {"error": "timeout"},
        }
        normal_event = {
            "event_id": "evt-001",
            "task_id": "task-ok",
            "event_type": "TOOL_EXECUTION",
            "epoch": 1,
            "payload": {},
        }

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            projector.project_event(error_event)
            projector.project_event(normal_event)

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            engine = SemanticQueryEngine(vector_adapter=adapter)
            results = engine.find_failure_patterns("tool failure timeout", top_k=5)
            assert all(r.event_type == "TOOL_ERROR" for r in results)

    def test_retrieve_execution_plans_filters_task_summary(
        self, adapter: InMemoryAdapter, sample_event: dict, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            projector.project_task_summary(
                task_id="task-plan-1",
                goal="build docker image",
            )
            projector.project_event(sample_event)

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ), patch(
            "agent_runtime.memory.query_engine._load_embedding_model",
            return_value=mock_embed,
        ):
            engine = SemanticQueryEngine(vector_adapter=adapter)
            plans = engine.retrieve_execution_plans("build docker", top_k=5)
            assert len(plans) == 1
            assert plans[0].task_id == "task-plan-1"
            assert "docker" in plans[0].goal.lower()

    def test_cluster_task_histories_returns_dict(
        self, adapter: InMemoryAdapter, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            for i in range(3):
                projector.project_event({
                    "event_id": f"evt-{i}",
                    "task_id": f"task-similar-{i}",
                    "event_type": "TOOL_EXECUTION",
                    "epoch": 1,
                    "payload": {},
                })

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            engine = SemanticQueryEngine(vector_adapter=adapter)
            clusters = engine.cluster_task_histories(min_similarity=0.5, max_clusters=10)
            assert isinstance(clusters, dict)

    def test_get_task_vector_returns_list_or_none(
        self, adapter: InMemoryAdapter, sample_event: dict, mock_embed: MagicMock
    ) -> None:
        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            projector = SemanticProjector(vector_adapter=adapter)
            projector.project_event(sample_event)

        with patch(
            "agent_runtime.memory.semantic_projector._load_embedding_model",
            return_value=mock_embed,
        ):
            engine = SemanticQueryEngine(vector_adapter=adapter)
            vec = engine.get_task_vector("task-42")
            assert vec is not None
            assert len(vec) == 384

            vec_none = engine.get_task_vector("nonexistent-task")
            assert vec_none is None
