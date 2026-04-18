"""
Adaptive Scheduler — v3 core component.

Features:
- Dynamic concurrency per queue load
- Priority-aware execution (priority queue in Redis)
- Starvation prevention (aging for low-priority tasks)
- Load-aware scaling
- Backpressure-aware enqueue
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import redis.asyncio as aioredis


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ScheduledTask:
    task_id: str
    priority: TaskPriority
    enqueued_at: float
    last_touched_at: float
    payload: dict
    attempt: int = 0
    max_attempts: int = 3


class AdaptiveScheduler:
    """
    Priority-aware, load-adaptive scheduler backed by Redis.

    Key design:
    - Tasks stored in a Redis sorted set: score = priority * TIME_BIAS + age_seconds
    - Priority wins early; age prevents starvation
    - WORKER_CONCURRENCY dynamically adjusts based on queue depth
    - queue_depth < LOW_WATERMARK → scale UP workers
    - queue_depth > HIGH_WATERMARK → scale DOWN / reject new tasks
    """

    PRIORITY_SCORE_MULT = 1_000_000.0   # priority weight over age
    TIME_BIAS = 100_000.0              # prevents overflow, keeps priority dominant
    LOW_WATERMARK = 10
    HIGH_WATERMARK = 200
    STARVATION_THRESHOLD_SEC = 300     # 5 min → boost low-priority tasks
    MAX_QUEUE_DEPTH = 1000
    DEFAULT_TTL = 86400 * 7

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url
        self._concurrency = 4
        self._target_concurrency = 4
        self._last_scale_check = 0.0
        self._scale_interval = 5.0  # seconds

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _score(self, priority: TaskPriority, enqueued_at: float) -> float:
        """
        Redis sorted-set score.
        Higher score = higher priority (pops from right in ZPOPBYLEX terms, but
        we use ZPOPMAX so highest score wins first).
        Score = priority * PRIORITY_SCORE_MULT + age_seconds / TIME_BIAS
        """
        age = time.time() - enqueued_at
        return int(priority.value) * self.PRIORITY_SCORE_MULT + age / self.TIME_BIAS

    def _starvation_boost(self, enqueued_at: float) -> float:
        """Add boost to score for starved tasks."""
        age = time.time() - enqueued_at
        if age > self.STARVATION_THRESHOLD_SEC:
            # linear boost up to 2x at 10 minutes
            boost = min(age / self.STARVATION_THRESHOLD_SEC, 2.0)
            return boost * self.PRIORITY_SCORE_MULT * 0.1
        return 0.0

    # ── enqueue ─────────────────────────────────────────────────────────────

    async def enqueue(
        self,
        task_id: str,
        payload: dict,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> bool:
        """
        Add task to priority queue.
        Returns False if queue is saturated (backpressure).
        """
        r = await self._get_redis()
        depth = await r.zcard("scheduler:queue")
        if depth >= self.MAX_QUEUE_DEPTH:
            return False  # backpressure

        now = time.time()
        task = ScheduledTask(
            task_id=task_id,
            priority=priority,
            enqueued_at=now,
            last_touched_at=now,
            payload=payload,
        )

        # store task payload
        await r.setex(
            f"scheduler:task:{task_id}",
            self.DEFAULT_TTL,
            json.dumps({
                **payload,
                "_meta": {
                    "priority": priority.value,
                    "enqueued_at": now,
                    "last_touched_at": now,
                    "attempt": 0,
                    "max_attempts": task.max_attempts,
                }
            }),
        )

        # score with starvation boost
        score = self._score(priority, now) + self._starvation_boost(now)
        await r.zadd("scheduler:queue", {task_id: score})
        return True

    async def dequeue(self, count: int = 1) -> list[dict]:
        """
        Pop up to `count` highest-priority tasks.
        Returns list of task payloads with task_id.
        """
        r = await self._get_redis()
        tasks: list[dict] = []

        for _ in range(count):
            # ZPOPMAX — pop highest score (highest priority)
            result = await r.zpopmax("scheduler:queue", count=1)
            if not result:
                break
            task_id, score = result[0] if isinstance(result[0], (list, tuple)) else (result[0], 0)

            raw = await r.get(f"scheduler:task:{task_id}")
            if not raw:
                continue

            data = json.loads(raw)
            meta = data.pop("_meta", {})
            tasks.append({
                "task_id": task_id,
                "score": score,
                "priority": meta.get("priority", 1),
                "enqueued_at": meta.get("enqueued_at", 0),
                "payload": data,
            })

        return tasks

    async def requeue(self, task_id: str, priority: TaskPriority) -> None:
        """Re-enqueue a task (e.g., after failure, without incrementing priority)."""
        r = await self._get_redis()
        raw = await r.get(f"scheduler:task:{task_id}")
        if not raw:
            return

        data = json.loads(raw)
        meta = data.pop("_meta", {})
        meta["attempt"] = meta.get("attempt", 0) + 1

        if meta["attempt"] >= meta.get("max_attempts", 3):
            # drop — max retries reached
            await r.delete(f"scheduler:task:{task_id}")
            return

        now = time.time()
        meta["last_touched_at"] = now
        data["_meta"] = meta
        await r.setex(f"scheduler:task:{task_id}", self.DEFAULT_TTL, json.dumps(data))

        score = self._score(priority, meta["enqueued_at"]) + self._starvation_boost(meta["enqueued_at"])
        await r.zadd("scheduler:queue", {task_id: score})

    # ── load-adaptive concurrency scaling ──────────────────────────────────

    async def compute_target_concurrency(self) -> int:
        """Dynamically adjust concurrency based on queue depth."""
        now = time.time()
        if now - self._last_scale_check < self._scale_interval:
            return self._target_concurrency
        self._last_scale_check = now

        r = await self._get_redis()
        depth = await r.zcard("scheduler:queue")

        if depth < self.LOW_WATERMARK:
            # scale up gradually
            self._target_concurrency = min(16, self._target_concurrency + 1)
        elif depth > self.HIGH_WATERMARK:
            # scale down aggressively
            self._target_concurrency = max(1, self._target_concurrency - 2)

        return self._target_concurrency

    @property
    def concurrency(self) -> int:
        return self._target_concurrency

    # ── observability ──────────────────────────────────────────────────────

    async def queue_stats(self) -> dict:
        """Current queue depth, priority distribution, avg wait time."""
        r = await self._get_redis()
        depth = await r.zcard("scheduler:queue")

        # priority distribution via ZCOUNT
        dist = {}
        for p in TaskPriority:
            count = await r.zcount("scheduler:queue", p.value * self.PRIORITY_SCORE_MULT,
                                    (p.value + 1) * self.PRIORITY_SCORE_MULT)
            dist[p.name] = count

        # avg age of tasks in queue
        now = time.time()
        total_age = 0.0
        ages = 0
        for p in TaskPriority:
            tasks = await r.zrange("scheduler:queue",
                                    p.value * self.PRIORITY_SCORE_MULT,
                                    (p.value + 1) * self.PRIORITY_SCORE_MULT,
                                    by_score=True)
            for task_id in tasks:
                raw = await r.get(f"scheduler:task:{task_id}")
                if raw:
                    meta = json.loads(raw).get("_meta", {})
                    age = now - meta.get("enqueued_at", now)
                    total_age += age
                    ages += 1

        return {
            "queue_depth": depth,
            "target_concurrency": self._target_concurrency,
            "priority_distribution": dist,
            "avg_wait_sec": total_age / ages if ages else 0,
            "saturated": depth >= self.MAX_QUEUE_DEPTH,
        }
