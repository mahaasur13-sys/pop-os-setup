import os
import json
import time
import hashlib
from typing import Optional

import redis
import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "semantic_memory")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "llama3")

# ── clients ──────────────────────────────────────────────────────────────────

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
qdrant = QdrantClient(url=QDRANT_URL)


# ── init ─────────────────────────────────────────────────────────────────────

def init_memory(override: bool = False):
    """Create Qdrant collection if it doesn't exist."""
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=4096, distance=Distance.COSINE),
        )
    elif override:
        qdrant.delete_collection(COLLECTION)
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=4096, distance=Distance.COSINE),
        )


# ── embedding ─────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Generate embedding via Ollama /api/embeddings endpoint."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ── store ─────────────────────────────────────────────────────────────────────

def store_memory(
    text: str,
    metadata: Optional[dict] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """
    Store a memory entry in both Qdrant (vector) and Redis (structured).
    Returns the memory ID.
    """
    memory_id = hashlib.sha256(f"{time.time()}:{text}".encode()).hexdigest()[:16]
    vector = embed_text(text)

    # Qdrant — vector + payload
    qdrant.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=memory_id,
                vector=vector,
                payload={
                    "text": text,
                    "metadata": metadata or {},
                    "stored_at": time.time(),
                },
            )
        ],
    )

    # Redis — structured key-value (with optional TTL)
    redis_key = f"mem:{memory_id}"
    redis_payload = {
        "id": memory_id,
        "text": text,
        "metadata": metadata or {},
        "stored_at": time.time(),
    }
    if ttl_seconds:
        r.setex(redis_key, ttl_seconds, json.dumps(redis_payload))
    else:
        r.set(redis_key, json.dumps(redis_payload))

    return memory_id


# ── retrieve ─────────────────────────────────────────────────────────────────

def retrieve_memories(query: str, top_k: int = 5, min_score: float = 0.5) -> list[dict]:
    """
    Semantic search: embed query → Qdrant ANN → return enriched results.
    Falls back to Redis scan if Qdrant is unavailable.
    """
    try:
        query_vector = embed_text(query)
        results = qdrant.search(
            collection_name=COLLECTION,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=min_score,
        )
        return [
            {
                "id": hit.id,
                "text": hit.payload["text"],
                "metadata": hit.payload.get("metadata", {}),
                "score": hit.score,
                "stored_at": hit.payload.get("stored_at"),
            }
            for hit in results
        ]
    except Exception:
        # fallback: plain Redis scan (no semantic search)
        keys = list(r.scan_iter("mem:*"))
        scored = []
        query_lower = query.lower()
        for k in keys[:top_k * 2]:
            raw = r.get(k)
            if not raw:
                continue
            entry = json.loads(raw)
            # crude keyword overlap score
            overlap = sum(1 for w in query_lower.split() if w in entry["text"].lower())
            if overlap > 0:
                scored.append({**entry, "score": overlap / len(query_lower.split())})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


# ── state helpers (Redis-only, no vectors) ────────────────────────────────────

def store_result(data: dict) -> str:
    key = f"task:{hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}"
    r.set(key, json.dumps(data))
    return key


def get_result(key: str) -> Optional[dict]:
    raw = r.get(f"task:{key}")
    return json.loads(raw) if raw else None
