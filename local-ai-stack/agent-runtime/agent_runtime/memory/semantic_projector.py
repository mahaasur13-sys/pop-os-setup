"""
SemanticProjector — write-side projection: Event → Embedding → VectorDB.

Design:
    This is the ingestion leg of the CQRS pattern.
    It consumes events from event_store and projects them into the vector store.
    engine.py is NOT modified — projection is triggered externally (e.g., by a background worker).

Event contract:
    Each TaskEvent has: event_id, task_id, event_type, epoch, payload, lamport_ts
    These are converted to a semantic representation before embedding.

Embedding strategy:
    - event_type + event_type hierarchy → topic vector
    - payload (dict) → flattened string representation
    - Combined: "[EVENT_TYPE] | task_id={task_id} epoch={epoch} | {payload_str}"

Environment:
    AGENT_EMBEDDING_MODEL  — sentence-transformers model name (default: all-MiniLM-L6-v2)
    AGENT_EMBEDDING_DIM   — embedding dimension (default: 384)
    AGENT_VECTOR_BACKEND  — chromadb | qdrant | inmemory (default: chromadb)
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from agent_runtime.memory.vector_adapter import VectorAdapter, VectorEntry, get_backend

# ——— Embedding model singleton ———

_embedding_model: Any | None = None
_embedding_dim: int = 384


def _load_embedding_model() -> Any:
    """Lazily load sentence-transformers model. Cached on first call."""
    global _embedding_model, _embedding_dim
    if _embedding_model is not None:
        return _embedding_model

    model_name = os.getenv("AGENT_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers not installed. Install with: pip install sentence-transformers"
        ) from exc

    _embedding_model = SentenceTransformer(model_name)
    _embedding_dim = _embedding_model.get_sentence_embedding_dimension()
    return _embedding_model


def _payload_str(payload: dict[str, Any] | None) -> str:
    """Flatten event payload to a deterministic string."""
    if not payload:
        return ""
    # sort_keys for determinism
    return json.dumps(payload, sort_keys=True, default=str)


def _make_entry_id(event_id: str, task_id: str, epoch: int) -> str:
    """Stable deterministic ID for vector entry."""
    raw = f"{event_id}:{task_id}:{epoch}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SemanticProjector:
    """
    Projects TaskEvents into a vector store.

    Usage:
        projector = SemanticProjector()
        projector.project_event(task_event)           # single
        projector.project_audit_trail(task_id, events) # batch from audit trail
    """

    def __init__(
        self,
        vector_adapter: VectorAdapter | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._adapter = vector_adapter or get_backend()
        if embedding_model:
            os.environ["AGENT_EMBEDDING_MODEL"] = embedding_model

    @property
    def adapter(self) -> VectorAdapter:
        return self._adapter

    def _event_to_text(self, event: Any) -> str:
        """
        Convert a TaskEvent (or dict) into a semantic string for embedding.
        Supports both event objects and raw dicts from event_store.
        """
        if hasattr(event, "__dict__"):
            # dataclass / object
            event_type = getattr(event, "event_type", type(event).__name__)
            task_id = str(getattr(event, "task_id", ""))
            epoch = getattr(event, "epoch", 0)
            payload = getattr(event, "payload", None)
        else:
            # dict
            event_type = event.get("event_type", str(event.get("type", "")))
            task_id = str(event.get("task_id", ""))
            epoch = event.get("epoch", 0)
            payload = event.get("payload")

        payload_str = _payload_str(payload)
        return (
            f"[{event_type}] | task_id={task_id} epoch={epoch} | {payload_str}"
        ).strip()

    def _embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        model = _load_embedding_model()
        return model.encode(text, normalize_embeddings=True).tolist()

    def project_event(self, event: Any) -> str:
        """
        Project a single event into the vector store.
        Returns the vector entry id.
        """
        event_id = getattr(event, "event_id", None) or event.get("event_id", "unknown")
        task_id = getattr(event, "task_id", None) or str(event.get("task_id", ""))
        epoch = getattr(event, "epoch", None) or event.get("epoch", 0)
        event_type = (
            getattr(event, "event_type", None) or event.get("event_type") or "UNKNOWN"
        )

        text = self._event_to_text(event)
        vector = self._embed(text)

        entry_id = _make_entry_id(event_id, task_id, epoch)
        entry = VectorEntry(
            id=entry_id,
            vector=vector,
            metadata={
                "event_id": event_id,
                "task_id": task_id,
                "epoch": epoch,
                "event_type": event_type,
                "text_repr": text[:512],  # truncate for storage efficiency
            },
        )
        self._adapter.upsert(entry)
        return entry_id

    def project_audit_trail(self, task_id: str, events: list[Any]) -> list[str]:
        """
        Project all events from an audit trail (task history) into the vector store.
        Returns list of vector entry ids.
        """
        entry_ids = []
        for event in events:
            eid = self.project_event(event)
            entry_ids.append(eid)
        return entry_ids

    def project_task_summary(
        self,
        task_id: str,
        goal: str,
        final_state: dict[str, Any] | None = None,
        event_types: list[str] | None = None,
    ) -> str:
        """
        Project a task-level summary (not individual events).
        Useful for plan reuse: store the goal + outcome as a single vector.

        Args:
            task_id: unique task identifier
            goal: original task goal/description
            final_state: optional final execution state
            event_types: list of event type names that occurred

        Returns:
            vector entry id
        """
        summary_parts = [f"[TASK_SUMMARY] goal={goal}"]
        if event_types:
            summary_parts.append(f"event_types={','.join(event_types)}")
        if final_state:
            summary_parts.append(f"outcome={_payload_str(final_state)}")
        text = " ".join(summary_parts)

        vector = self._embed(text)
        entry_id = _make_entry_id(f"summary_{task_id}", task_id, 0)

        entry = VectorEntry(
            id=entry_id,
            vector=vector,
            metadata={
                "task_id": task_id,
                "event_type": "TASK_SUMMARY",
                "goal": goal[:512],
                "text_repr": text[:512],
            },
        )
        self._adapter.upsert(entry)
        return entry_id

    def close(self) -> None:
        self._adapter.close()
