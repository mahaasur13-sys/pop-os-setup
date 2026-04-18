"""
Configuration system — env-driven settings.
Loads from environment variables with validation.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import os


class Settings(BaseSettings):
    # === Runtime ===
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    OLLAMA_MODEL: str = "llama3.2:latest"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text:latest"
    OLLAMA_TIMEOUT: int = 120

    # === Redis ===
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = 0
    REDIS_STREAM_KEY: str = "agent:tasks"
    REDIS_RESULT_TTL: int = 3600  # seconds
    REDIS_CONSUMER_GROUP: str = "agent-workers"
    REDIS_CONSUMER_NAME: str = "worker-1"

    # === Qdrant ===
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "agent_memory"
    QDRANT_VECTOR_SIZE: int = 768
    QDRANT_SCORE_THRESHOLD: float = 0.7

    # === API Server ===
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8050
    API_WORKERS: int = 4
    API_WORKER_CONCURRENCY: int = 10
    API_MAX_REQUEST_SIZE: int = 10 * 1024 * 1024  # 10MB

    # === Intelligence Layer ===
    MODEL_ROUTING_ENABLED: bool = True
    TOOL_POLICY_ENABLED: bool = True
    MEMORY_FEEDBACK_ENABLED: bool = True
    EMBEDDING_CACHE_SIZE: int = 1000
    PATTERN_CACHE_SIZE: int = 100

    # === Cost Control ===
    MAX_TOKENS_PER_TASK: int = 8192
    COST_BUDGET_PER_DAY: float = 10.0  # USD
    LATENCY_BUDGET_MS: int = 30000

    # === Observability ===
    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")
    LOG_FORMAT: str = "json"  # json | text
    METRICS_ENABLED: bool = True
    METRICS_PORT: int = 9090
    SENTRY_DSN: Optional[str] = None
    JAEGER_HOST: str = "localhost"
    JAEGER_PORT: int = 6831

    # === Health ===
    HEALTH_CHECK_INTERVAL: int = 30
    HEALTH_CHECK_TIMEOUT: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
