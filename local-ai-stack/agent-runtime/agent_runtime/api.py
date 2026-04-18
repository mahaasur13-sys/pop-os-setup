"""
Production-grade FastAPI application.
Async, health-checked, observable.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4
import time
import logging
import json
import asyncio

from agent_runtime.loop import run_task
from agent_runtime.config import settings

# === Logging setup ===
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("api")


# === Prometheus metrics (minimal, no extra dep) ===
METRICS = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_error": 0,
    "requests_by_endpoint": {},
    "task_duration_seconds": [],
}


# === App lifecycle ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("agent-runtime starting up")
    log.info(f"Ollama: {settings.OLLAMA_BASE_URL}")
    log.info(f"Redis: {settings.REDIS_URL}")
    log.info(f"Qdrant: {settings.QDRANT_URL}")
    yield
    log.info("agent-runtime shutting down")


app = FastAPI(title="agent-runtime", lifespan=lifespan)

# In-memory task store (production: Redis-backed)
TASKS: dict = {}


# === Middleware ===
@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start = time.perf_counter()
    method = request.method
    path = request.url.path

    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:
        status = 500

    duration = time.perf_counter() - start
    METRICS["requests_total"] += 1

    if status == 200:
        METRICS["requests_success"] += 1
    elif status >= 400:
        METRICS["requests_error"] += 1

    key = f"{method} {path}"
    METRICS["requests_by_endpoint"][key] = METRICS["requests_by_endpoint"].get(key, 0) + 1
    METRICS["task_duration_seconds"].append(duration)
    if len(METRICS["task_duration_seconds"]) > 1000:
        METRICS["task_duration_seconds"] = METRICS["task_duration_seconds"][-1000:]

    return response


# === Health & Observability ===

@app.get("/health")
async def health():
    """
    Liveness probe — basic health check.
    Kubernetes liveness will hit this every 20s.
    """
    return {
        "status": "ok",
        "version": "v4",
        "uptime": "N/A",  # TODO: track process start time
    }


@app.get("/health/ready")
async def health_ready():
    """
    Readiness probe — checks external dependencies.
    Kubernetes readiness will hit this before routing traffic.
    """
    checks = {}
    overall = "ok"

    # Check Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            checks["ollama"] = "ok" if resp.status_code == 200 else f"http {resp.status_code}"
    except Exception as e:
        checks["ollama"] = f"error: {e}"
        overall = "degraded"

    # Check Redis
    try:
        import redis.asyncio as redis_async
        r = redis_async.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall = "degraded"

    # Check Qdrant
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.QDRANT_URL}/health")
            checks["qdrant"] = "ok" if resp.status_code == 200 else f"http {resp.status_code}"
    except Exception as e:
        checks["qdrant"] = f"error: {e}"
        overall = "degraded"

    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={
            "status": overall,
            "checks": checks,
        }
    )


@app.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.
    Returns plain-text Prometheus format.
    """
    total = METRICS["requests_total"]
    success = METRICS["requests_success"]
    error = METRICS["requests_error"]
    durations = METRICS["task_duration_seconds"]

    avg_latency = sum(durations) / len(durations) if durations else 0

    # Format: Prometheus text exposition
    lines = [
        "# HELP agent_requests_total Total HTTP requests",
        "# TYPE agent_requests_total counter",
        f"agent_requests_total {total}",
        f"agent_requests_success {success}",
        f"agent_requests_error {error}",
        "# HELP agent_request_duration_seconds Average request duration",
        "# TYPE agent_request_duration_seconds gauge",
        f"agent_request_duration_seconds {avg_latency:.4f}",
    ]

    for endpoint, count in METRICS["requests_by_endpoint"].items():
        endpoint_label = endpoint.replace(" ", "_").replace("/", "_")
        lines.append(f'agent_requests_by_endpoint{{endpoint="{endpoint}"}} {count}')

    return JSONResponse(
        status_code=200,
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
    )


# === Task API ===

@app.post("/task")
async def create_task(payload: dict):
    """
    Submit a new task for async execution.
    Returns task_id immediately (fire-and-forget or async poll).
    """
    task_id = str(uuid4())

    TASKS[task_id] = {
        "id": task_id,
        "status": "running",
        "submitted_at": time.time(),
        "result": None,
    }

    # Run async without blocking
    asyncio.create_task(_run_task_async(task_id, payload))

    return {"task_id": task_id, "status": "running"}


async def _run_task_async(task_id: str, payload: dict):
    """Execute task in background."""
    from agent_runtime.loop import run_task

    try:
        result = await run_task(payload)
        TASKS[task_id].update({
            "status": "done",
            "result": result,
            "completed_at": time.time(),
        })
    except Exception as e:
        TASKS[task_id].update({
            "status": "error",
            "error": str(e),
            "completed_at": time.time(),
        })
        log.error(f"Task {task_id} failed: {e}")


@app.post("/task/sync")
async def create_task_sync(payload: dict):
    """
    Submit a task and wait for result (synchronous execution).
    Use for short tasks only.
    """
    task_id = str(uuid4())

    TASKS[task_id] = {
        "id": task_id,
        "status": "running",
        "submitted_at": time.time(),
    }

    try:
        result = await run_task(payload)
        TASKS[task_id].update({
            "status": "done",
            "result": result,
            "completed_at": time.time(),
        })
        return {"task_id": task_id, "status": "done", "result": result}
    except Exception as e:
        TASKS[task_id].update({
            "status": "error",
            "error": str(e),
            "completed_at": time.time(),
        })
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    """Poll task status and retrieve result."""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": task["status"],
        "result": task.get("result"),
        "error": task.get("error"),
        "submitted_at": task.get("submitted_at"),
        "completed_at": task.get("completed_at"),
    }


@app.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task."""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] == "running":
        task["status"] = "cancelled"
        # TODO: integrate cancellation via engine.cancellation
        return {"task_id": task_id, "status": "cancelled"}

    return {"task_id": task_id, "status": task["status"]}


# === System ===

@app.get("/")
async def root():
    return {
        "service": "agent-runtime",
        "version": "v4",
        "docs": "/docs",
    }
