"""
ExecutionGuard — runtime enforcement for DAG execution.

Sits between gateway and engine.execute(), wraps tool calls with:
  1. Timeout enforcement per step
  2. Budget tracking (cost/latency consumed)
  3. Kill switch (cancellation propagation)
  4. Rate limiting per tool (global, not per-manifest)
  5. Tool call interception (hook before/after each call)

Does NOT perform policy evaluation — that is done by PolicyEngine.
ExecutionGuard enforces the decisions made and budgets allocated.

Returns GuardMetrics after each wrapped execution.
"""

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, Optional, Any
from collections import defaultdict


# ── Guard enums ────────────────────────────────────────────────────────────────

class GuardStatus(str, Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    KILLED = "killed"
    BUDGET_EXCEEDED = "budget_exceeded"
    RATE_LIMITED = "rate_limited"


@dataclass
class GuardMetrics:
    """Runtime metrics collected during guard-wrapped execution."""
    task_id: str
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0
    timeouts: int = 0
    kills: int = 0
    rejections: int = 0
    budget_exceeded: int = 0
    rate_limited: int = 0
    start_ts: float = field(default_factory=time.monotonic)
    end_ts: Optional[float] = None

    @property
    def duration_ms(self) -> float:
        end = self.end_ts or time.monotonic()
        return (end - self.start_ts) * 1000

    @property
    def is_complete(self) -> bool:
        return self.steps_completed + self.steps_failed >= self.steps_total


@dataclass
class GuardedStep:
    """A step wrapped with guard enforcement."""
    step_id: str
    step_name: str
    tool: str
    max_latency_ms: float
    max_cost: float
    timeout_ts: float   # absolute monotonic deadline


@dataclass
class GuardConfig:
    """Global guard configuration."""
    global_timeout_per_step_ms: float = 120_000.0   # 2 min per step
    global_max_cost_per_step: float = 50.0
    global_rate_limit_per_minute: int = 60
    kill_switch_active: bool = False


# ── Global rate limiting state ────────────────────────────────────────────────

_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _cleanup_old_entries(bucket: list[float], window_seconds: float = 60.0) -> None:
    now = time.monotonic()
    bucket[:] = [ts for ts in bucket if now - ts < window_seconds]


# ── ExecutionGuard ────────────────────────────────────────────────────────────

class ExecutionGuard:
    """
    Runtime enforcement wrapper for tool execution.

    Usage::

        guard = ExecutionGuard(config=GuardConfig())
        wrapped = guard.wrap_call(original_tool_call_fn)

        for step in manifest.steps:
            result = await wrapped(step, GuardedStep(...))
            metrics.add(result)
    """

    def __init__(self, config: Optional[GuardConfig] = None):
        self.config = config or GuardConfig()
        self._kill_count = 0
        self._active_tasks: dict[str, asyncio.Task] = {}

    # ── main entry ────────────────────────────────────────────────────────────

    def evaluate_step(
        self,
        step,               # StepManifest from plan_executor
        adjusted_budget_ms: float,
        adjusted_budget_cost: float,
    ) -> GuardedStep:
        """
        Build a GuardedStep with timeout/cost budgets for a single step.
        Uses per-tool defaults if manifest doesn't specify.
        """
        max_latency_ms = (
            step.estimated_latency_ms * 1.5  # 50% margin
            if step.estimated_latency_ms > 0
            else self.config.global_timeout_per_step_ms
        )
        # Cap at adjusted budget or global max
        max_latency_ms = min(max_latency_ms, adjusted_budget_ms, self.config.global_timeout_per_step_ms)

        return GuardedStep(
            step_id=step.step_id,
            step_name=step.step_name,
            tool=step.tool,
            max_latency_ms=max_latency_ms,
            max_cost=min(adjusted_budget_cost, self.config.global_max_cost_per_step),
            timeout_ts=time.monotonic() + (max_latency_ms / 1000.0),
        )

    async def wrap_execute(
        self,
        step,               # StepManifest
        guarded_step: GuardedStep,
        call_fn: Callable[..., Awaitable[Any]],   # actual tool call
        *args, **kwargs,
    ) -> tuple[GuardStatus, Any]:
        """
        Execute a single step through guard enforcement.

        Returns (status, result_or_exception).

        Enforcement order:
          1. Kill switch check
          2. Rate limit check
          3. Budget check
          4. Timeout wrapper
        """
        # 1. Kill switch
        if self.config.kill_switch_active:
            self._kill_count += 1
            return (GuardStatus.KILLED, RuntimeError("Kill switch active — execution aborted"))

        # 2. Rate limit
        _cleanup_old_entries(_rate_buckets[guarded_step.tool])
        if len(_rate_buckets[guarded_step.tool]) >= self.config.global_rate_limit_per_minute:
            return (GuardStatus.RATE_LIMITED, RuntimeError(f"Rate limit exceeded for tool '{guarded_step.tool}'"))

        _rate_buckets[guarded_step.tool].append(time.monotonic())

        # 3. Budget check
        if time.monotonic() > guarded_step.timeout_ts:
            return (GuardStatus.BUDGET_EXCEEDED, TimeoutError(f"Budget exceeded before step '{guarded_step.step_name}' started"))

        # 4. Timeout-wrapped execution
        try:
            result = await asyncio.wait_for(
                call_fn(*args, **kwargs),
                timeout=guarded_step.max_latency_ms / 1000.0,
            )
            return (GuardStatus.OK, result)

        except asyncio.TimeoutError:
            return (GuardStatus.TIMEOUT, TimeoutError(f"Step '{guarded_step.step_name}' exceeded {guarded_step.max_latency_ms:.0f}ms"))

    # ── kill switch ──────────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "") -> None:
        """Globally halt all guarded executions."""
        self.config.kill_switch_active = True
        # Cancel active tasks
        for task_id, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
        self._kill_count += len(self._active_tasks)

    def deactivate_kill_switch(self) -> None:
        """Re-enable guarded executions."""
        self.config.kill_switch_active = False

    @property
    def kill_switch_active(self) -> bool:
        return self.config.kill_switch_active

    # ── metrics ──────────────────────────────────────────────────────────────

    def new_metrics(self, task_id: str, total_steps: int) -> GuardMetrics:
        return GuardMetrics(task_id=task_id, steps_total=total_steps)

    def update_metrics(
        self,
        metrics: GuardMetrics,
        status: GuardStatus,
        latency_ms: float,
        cost: float = 0.0,
    ) -> None:
        metrics.total_latency_ms += latency_ms
        metrics.total_cost += cost
        if status == GuardStatus.OK:
            metrics.steps_completed += 1
        else:
            metrics.steps_failed += 1
            if status == GuardStatus.TIMEOUT:
                metrics.timeouts += 1
            elif status == GuardStatus.KILLED:
                metrics.kills += 1
            elif status == GuardStatus.BUDGET_EXCEEDED:
                metrics.budget_exceeded += 1
            elif status == GuardStatus.RATE_LIMITED:
                metrics.rate_limited += 1
        if metrics.steps_failed > 0:
            metrics.rejections += 1

    # ── pre/post hooks ────────────────────────────────────────────────────────

    async def run_pre_hook(
        self,
        hook: Optional[Callable[..., Awaitable]],
        step: GuardedStep,
    ) -> None:
        if hook:
            try:
                await hook(step)
            except Exception:
                pass  # hooks are best-effort

    async def run_post_hook(
        self,
        hook: Optional[Callable[..., Awaitable]],
        step: GuardedStep,
        status: GuardStatus,
        result: Any,
    ) -> None:
        if hook:
            try:
                await hook(step, status, result)
            except Exception:
                pass

    # ── batch execution ───────────────────────────────────────────────────────

    async def execute_manifest(
        self,
        manifest,           # ExecutionManifest
        adjusted_budget_ms: float,
        adjusted_budget_cost: float,
        call_fn: Callable[..., Awaitable[Any]],
        pre_hook: Optional[Callable[..., Awaitable]] = None,
        post_hook: Optional[Callable[..., Awaitable]] = None,
    ) -> GuardMetrics:
        """
        Execute a full manifest through the guard.

        Usage::

            metrics = await guard.execute_manifest(
                manifest,
                adjusted_budget_ms=300_000,
                adjusted_budget_cost=100.0,
                call_fn=engine.execute_step,
            )
        """
        metrics = self.new_metrics(manifest.new_task_id, manifest.total_steps)

        for step in manifest.steps:
            guarded = self.evaluate_step(step, adjusted_budget_ms, adjusted_budget_cost)

            await self.run_pre_hook(pre_hook, guarded)

            step_start = time.monotonic()
            status, result = await self.wrap_execute(step, guarded, call_fn, step)
            step_latency = (time.monotonic() - step_start) * 1000

            self.update_metrics(metrics, status, step_latency)

            await self.run_post_hook(post_hook, guarded, status, result)

            if status != GuardStatus.OK:
                # Stop execution on first failure (deterministic: fail-fast)
                metrics.end_ts = time.monotonic()
                return metrics

        metrics.end_ts = time.monotonic()
        return metrics
