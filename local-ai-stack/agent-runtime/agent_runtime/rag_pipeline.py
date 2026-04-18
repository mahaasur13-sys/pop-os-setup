"""
RAG pipeline: embed → store → retrieve → build_context
Used by engine.py and can be called directly.
"""

from .memory import embed_text, store_memory, retrieve_memories


def add_memory(text: str, metadata: dict | None = None) -> str:
    """Convenience wrapper: embed + store in one call."""
    return store_memory(text=text, metadata=metadata)


def build_context(query: str, top_k: int = 5, min_score: float = 0.5) -> str:
    """
    Retrieve relevant memories and format as a context block string.
    Returns empty string if nothing relevant found.
    """
    memories = retrieve_memories(query=query, top_k=top_k, min_score=min_score)

    if not memories:
        return ""

    lines = []
    for m in memories:
        score_pct = int(m["score"] * 100)
        lines.append(f"[relevance {score_pct}%] {m['text']}")

    header = f"=== {len(memories)} relevant memory/ies ===\n"
    return header + "\n".join(lines) + "\n=============================="


__all__ = ["add_memory", "build_context", "embed_text", "retrieve_memories"]
