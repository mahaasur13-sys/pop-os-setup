"""
agent-runtime memory subsystem — CQRS Semantic Projection Layer

Architecture:
    event_store (truth) → semantic_projector → vector_adapter → query_engine

Principles:
    - event_store is the source of truth (immutable)
    - memory/ is read-side projection only (no execution influence)
    - CQRS: write path = Event→Embedding→VectorDB, read path = semantic queries
    - engine.py knows nothing about embeddings or vectors

Modules:
    vector_adapter    — ChromaDB / Qdrant / in-memory abstraction
    semantic_projector — Event → embedding pipeline (write-side projection)
    query_engine      — semantic retrieval API (read-side intelligence)
"""

from agent_runtime.memory.vector_adapter import VectorAdapter, get_backend
from agent_runtime.memory.semantic_projector import SemanticProjector
from agent_runtime.memory.query_engine import SemanticQueryEngine

__all__ = [
    "VectorAdapter",
    "get_backend",
    "SemanticProjector",
    "SemanticQueryEngine",
]
