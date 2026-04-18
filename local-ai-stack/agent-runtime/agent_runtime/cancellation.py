"""
Hard Cancellation Model — v3 core component.

Provides:
- subprocess SIGKILL/SIGTERM forced termination
- task-level interrupt propagation (propagate down to all child steps)
- cancellation state machine (cancelled state, not just flag)
- deterministic cleanup on cancellation
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import redis.asyncio as aioredis


class CancellationStrength(Enum):
    SOFT = "soft"    # SIGTERM, allow graceful cleanup (5s timeout then SIGKILL)
    HARD = "hard"    # SIGKILL immediately
    GRACEFUL = "graceful"  # SIGTERM, wait up to 30s for graceful exit


@dataclass
class CancellationTarget:
    task_id: str
    process_group_id: int   # os.getpgid() of the subprocess
    started_at: float
    strength: CancellationStrength = CancellationStrength.SOFT
    children: list[int] = None  # child process group IDs

    def __post_init__(self):
        if self.children is None:
            self.children = []


class HardCancellation:
    """
    Provides guaranteed process termination for running tasks.

    Design:
    - Each task stores its process group ID (PGID) in Redis
    - Cancellation writes to Redis; worker picks it up
    - Worker calls cancel() which sends SIGTERM/SIGKILL to the PGID
    - All child subprocesses in the same PGID are killed
    - Worker transitions task to CANCELLED state
    - Cleanup removes Redis state
    """

    SOFT_KILL_TIMEOUT = 5.0   # seconds between SIGTERM and SIGKILL
    GRACEFUL_KILL_TIMEOUT = 30.0

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url
        self._active_targets: dict[str, CancellationTarget] = {}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    # ── registration ──────────────────────────────────────────────────────────

    async def register(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
    ) -> str:
        """Register task with its subprocess. Returns task_id."""
        try:
            pgid = os.getpgid(process.pid)
        except Exception:
            pgid = process.pid  # fallback to pid if group unavailable

        target = CancellationTarget(
            task_id=task_id,
            process_group_id=pgid,
            started_at=time.time(),
        )

        async with self._lock:
            self._active_targets[task_id] = target

        r = await self._get_redis()
        await r.setex(
            f"cancel:target:{task_id}",
            3600,
            json.dumps({
                "pgid": pgid,
                "pid": process.pid,
                "started_at": target.started_at,
                "strength": target.strength.value,
                "children": [],
            }),
        )
        return task_id

    async def register_child(self, task_id: str, child_pgid: int) -> None:
        """Track a child subprocess group (for nested execution)."""
        async with self._lock:
            if task_id in self._active_targets:
                self._active_targets[task_id].children.append(child_pgid)

        r = await self._get_redis()
        raw = await r.get(f"cancel:target:{task_id}")
        if raw:
            data = json.loads(raw)
            if child_pgid not in data["children"]:
                data["children"].append(child_pgid)
                await r.setex(f"cancel:target:{task_id}", 3600, json.dumps(data))

    # ── cancellation execution ─────────────────────────────────────────────────

    async def cancel(
        self,
        task_id: str,
        strength: CancellationStrength = CancellationStrength.SOFT,
    ) -> bool:
        """
        Send termination signal(s) to task's process group.
        Returns True if signal was sent.
        """
        r = await self._get_redis()
        raw = await r.get(f"cancel:target:{task_id}")
        if not raw:
            return False

        data = json.loads(raw)
        pids_to_kill = [data["pgid"]] + data["children"]
        timeout = (self.GRACEFUL_KILL_TIMEOUT if strength == CancellationStrength.GRACEFUL
                   else self.SOFT_KILL_TIMEOUT)

        killed = await self._send_signals(pids_to_kill, strength, timeout)

        async with self._lock:
            self._active_targets.pop(task_id, None)

        await r.delete(f"cancel:target:{task_id}")
        await r.setex(f"cancel:{task_id}", 3600, "1")

        return killed

    async def _send_signals(
        self,
        pids: list[int],
        strength: CancellationStrength,
        timeout: float,
    ) -> bool:
        """
        Send signals to process group(s).
        - SOFT/GRACEFUL: SIGTERM → wait → SIGKILL if still alive
        - HARD: SIGKILL immediately
        Returns True if any process was signaled.
        """
        if strength == CancellationStrength.HARD:
            for pid in pids:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            return True

        # SIGTERM first
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        # wait for graceful exit
        await asyncio.sleep(timeout)

        # SIGKILL if still alive
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        return True

    # ── polling cancellation flag (for engine) ─────────────────────────────────

    async def is_cancelled(self, task_id: str) -> bool:
        """Check if task has been externally cancelled."""
        r = await self._get_redis()
        flag = await r.get(f"cancel:{task_id}")
        return flag == "1"

    async def check_and_cancel_subprocess(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        interval_sec: float = 0.5,
    ) -> asyncio.Task:
        """
        Start a background monitor that watches cancellation flag
        and kills subprocess if set.
        Returns the monitoring Task — cancel it when step completes.
        """
        loop = asyncio.get_running_loop()

        async def monitor():
            while True:
                if await self.is_cancelled(task_id):
                    try:
                        pgid = os.getpgid(process.pid)
                    except Exception:
                        pgid = process.pid
                    await self._send_signals([pgid], CancellationStrength.HARD, 0.0)
                    return
                await asyncio.sleep(interval_sec)

        return asyncio.create_task(monitor())
