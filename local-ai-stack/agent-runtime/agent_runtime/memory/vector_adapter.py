"""
VectorAdapter — ChromaDB / Qdrant / in-memory abstraction layer.

Supports backend swap without changing caller semantics.
Backend is selected via environment variable AGENT_VECTOR_BACKEND.
Fallback order: chromadb → qdrant → in_memory (always available).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ——— Backend implementations ———


def get_backend() -> VectorAdapter:
    """Factory: return VectorAdapter instance based on AGENT_VECTOR_BACKEND env."""
    backend = os.getenv("AGENT_VECTOR_BACKEND", "chromadb").lower()
    if backend == "qdrant":
        return QdrantAdapter()
    if backend == "inmemory":
        return InMemoryAdapter()
    # default: chromadb
    return ChromaAdapter()


@dataclass
class VectorEntry:
    id: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorAdapter(ABC):
    """Abstract interface all backends must implement."""

    @abstractmethod
    def upsert(self, entry: VectorEntry) -> None:
        """Insert or update a vector entry."""
        ...

    @abstractmethod
    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        """Bulk insert or update."""
        ...

    @abstractmethod
    def query(self, vector: list[float], top_k: int = 5) -> list[VectorEntry]:
        """Return top_k nearest entries by cosine similarity."""
        ...

    @abstractmethod
    def delete(self, entry_id: str) -> None:
        """Remove entry by id."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Total number of entries."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
        ...


class InMemoryAdapter(VectorAdapter):
    """In-process fallback using numpy + cosine similarity. No external deps."""

    def __init__(self) -> None:
        self._entries: dict[str, VectorEntry] = {}
        self._dim: int | None = None

    def _ensure_dim(self, vector: list[float]) -> None:
        if self._dim is None:
            self._dim = len(vector)
        elif self._dim != len(vector):
            raise ValueError(
                f"Dimension mismatch: expected {self._dim}, got {len(vector)}"
            )

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        a_np = np.array(a, dtype=np.float32)
        b_np = np.array(b, dtype=np.float32)
        norm_a = np.linalg.norm(a_np)
        norm_b = np.linalg.norm(b_np)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_np, b_np) / (norm_a * norm_b))

    def upsert(self, entry: VectorEntry) -> None:
        self._ensure_dim(entry.vector)
        self._entries[entry.id] = entry

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        for e in entries:
            self.upsert(e)

    def query(self, vector: list[float], top_k: int = 5) -> list[VectorEntry]:
        self._ensure_dim(vector)
        scored = [(e, self._cosine(vector, e.vector)) for e in self._entries.values()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    def delete(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)

    def count(self) -> int:
        return len(self._entries)

    def close(self) -> None:
        self._entries.clear()


class ChromaAdapter(VectorAdapter):
    """ChromaDB adapter (persistent or in-memory)."""

    def __init__(
        self,
        persist_dir: str | None = None,
        collection_name: str = "agent_events",
    ) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "ChromaDB not installed. Install with: pip install chromadb"
            ) from exc

        if persist_dir:
            client = chromadb.PersistentClient(path=persist_dir)
        else:
            client = chromadb.InMemoryClient()

        self._collection = client.get_or_create_collection(name=collection_name)
        self._persist_dir = persist_dir

    def _to_ids(self, entries: list[VectorEntry]) -> list[str]:
        return [e.id for e in entries]

    def upsert(self, entry: VectorEntry) -> None:
        self._collection.upsert(
            ids=[entry.id],
            embeddings=[entry.vector],
            metadatas=[entry.metadata],
        )

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        self._collection.upsert(
            ids=self._to_ids(entries),
            embeddings=[e.vector for e in entries],
            metadatas=[e.metadata for e in entries],
        )

    def query(self, vector: list[float], top_k: int = 5) -> list[VectorEntry]:
        results = self._collection.query(
            query_embeddings=[vector],
            n_results=top_k,
        )
        entries = []
        for i, vid in enumerate(results["ids"][0]):
            entries.append(
                VectorEntry(
                    id=vid,
                    vector=results["embeddings"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )
            )
        return entries

    def delete(self, entry_id: str) -> None:
        self._collection.delete(ids=[entry_id])

    def count(self) -> int:
        return self._collection.count()

    def close(self) -> None:
        # ChromaDB client has no close method
        pass


class QdrantAdapter(VectorAdapter):
    """Qdrant adapter (requires Qdrant server running)."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "agent_events",
        vector_size: int = 384,
    ) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models
        except ImportError as exc:
            raise ImportError(
                "Qdrant client not installed. Install with: pip install qdrant-client"
            ) from exc

        self._client = QdrantClient(url=url)
        self._collection = collection
        self._vector_size = vector_size
        # ensure collection exists
        collections = [c.name for c in self._client.get_collections().collections]
        if collection not in collections:
            self._client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )

    def upsert(self, entry: VectorEntry) -> None:
        self._client.upsert(
            collection_name=self._collection,
            points=[
                {
                    "id": entry.id,
                    "vector": entry.vector,
                    "payload": entry.metadata,
                }
            ],
        )

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        self._client.upsert(
            collection_name=self._collection,
            points=[
                {"id": e.id, "vector": e.vector, "payload": e.metadata} for e in entries
            ],
        )

    def query(self, vector: list[float], top_k: int = 5) -> list[VectorEntry]:
        results = self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            limit=top_k,
        )
        return [
            VectorEntry(
                id=str(r.id),
                vector=r.vector,
                metadata=r.payload or {},
            )
            for r in results
        ]

    def delete(self, entry_id: str) -> None:
        self._client.delete(collection_name=self._collection, points=[entry_id])

    def count(self) -> int:
        info = self._client.get_collection(collection_name=self._collection)
        return info.points_count

    def close(self) -> None:
        # Qdrant client has no close method
        pass
