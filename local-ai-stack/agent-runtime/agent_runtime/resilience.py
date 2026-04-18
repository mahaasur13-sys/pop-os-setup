"""
Resilience Layer — Retry Engine + Circuit Breaker.

Components:
1. RetryPolicyEngine   — exponential backoff, jitter, per-task budgets,
                          failure classification (transient/permanent/fatal)
2. CircuitBreaker      — per-dependency state machine (CLOSED→OPEN→HALF-OPEN)
                          protects Redis, Ollama, Qdrant
3. FailureClassifier   — categorizes errors for retry decisions
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

import redis.asyncio as aioredis


# ── Failure Classification ────────────────────────────────────────────────────

class FailureKind(Enum):
    TRANSIENT   = "transient"    # network glitch, timeout → retry ok
    PERMANENT   = "permanent"    # bad input, validation → retry after fix
    FATAL       = "fatal"        # out of budget, circuit open → do not retry
    UNKNOWN     = "unknown"      # default


@dataclass
class RetryBudget:
    """Per-task retry budget and backoff parameters."""
    task_id: str
    max_attempts: int = 3
    base_delay: float = 1.0       # seconds
    max_delay: float = 60.0      # cap
    exponential_base: float = 2.0
    jitter: float = 0.3           # ±30% randomization
    retryable_kinds: tuple[FailureKind, ...] = (FailureKind.TRANSIENT, FailureKind.UNKNOWN)
    attempt: int = 0

    def compute_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self.base_delay * (self.exponential_base ** attempt), self.max_delay)
        jitter_range = delay * self.jitter
        return delay + random.uniform(-jitter_range, jitter_range)

    def can_retry(self, attempt: int, kind: FailureKind) -> bool:
        if attempt >= self.max_attempts:
            return False
        return kind in self.retryable_kinds


# ── Failure Classifier ────────────────────────────────────────────────────────

class FailureClassifier:
    """
    Classifies exceptions to decide retry strategy.
    Extendable via pattern → kind mapping.
    """

    TRANSIENT_PATTERNS = (
        "timeout",
        "ConnectionRefused",
        "ConnectionReset",
        "ConnectionError",
        "TemporaryFailure",
        "503",
        "502",
        "429",
        "TooManyRequests",
        "Host unreachable",
        "Network is unreachable",
    )
    PERMANENT_PATTERNS = (
        "validation error",
        "invalid input",
        "unauthorized",
        "403",
        "404",
        "400",
        "not found",
        "invalid syntax",
        "json decode error",
    )
    FATAL_PATTERNS = (
        "out of budget",
        "circuit open",
        "budget exhausted",
        "quota exceeded",
    )

    @classmethod
    def classify(cls, error: str) -> FailureKind:
        error_lower = error.lower()
        if any(p.lower() in error_lower for p in cls.FATAL_PATTERNS):
            return FailureKind.FATAL
        if any(p.lower() in error_lower for p in cls.PERMANENT_PATTERNS):
            return FailureKind.PERMANENT
        if any(p.lower() in error_lower for p in cls.TRANSIENT_PATTERNS):
            return FailureKind.TRANSIENT
        return FailureKind.UNKNOWN


# ── Retry Policy Engine ───────────────────────────────────────────────────────

class RetryPolicyEngine:
    """
    Manages retry budgets in Redis + computes backoff delays.

    Keys:
      retry_budget:<task_id>   — Hash: {attempt, max_attempts, base_delay, max_delay,
                                        exponential_base, jitter, created_at}
    """

    BUDGET_PREFIX = "retry_budget:"
    RESULT_TTL    = 3600

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def init_budget(self, task_id: str, budget: RetryBudget) -> None:
        """Store or update retry budget for a task."""
        r = await self._get_redis()
        key = f"{self.BUDGET_PREFIX}{task_id}"
        await r.hset(key, mapping={
            "attempt":          "0",
            "max_attempts":     str(budget.max_attempts),
            "base_delay":       str(budget.base_delay),
            "max_delay":        str(budget.max_delay),
            "exponential_base": str(budget.exponential_base),
            "jitter":           str(budget.jitter),
            "created_at":       str(time.time()),
        })
        await r.expire(key, self.RESULT_TTL)

    async def get_budget(self, task_id: str) -> Optional[RetryBudget]:
        r = await self._get_redis()
        raw = await r.hgetall(f"{self.BUDGET_PREFIX}{task_id}")
        if not raw:
            return None
        return RetryBudget(
            task_id=task_id,
            attempt=int(raw.get("attempt", "0")),
            max_attempts=int(raw.get("max_attempts", "3")),
            base_delay=float(raw.get("base_delay", "1.0")),
            max_delay=float(raw.get("max_delay", "60.0")),
            exponential_base=float(raw.get("exponential_base", "2.0")),
            jitter=float(raw.get("jitter", "0.3")),
        )

    async def record_failure(self, task_id: str) -> tuple[int, float]:
        """
        Increment attempt counter. Returns (new_attempt, delay_seconds).
        Delay is pre-computed for caller to schedule.
        """
        r = await self._get_redis()
        key = f"{self.BUDGET_PREFIX}{task_id}"

        attempt = await r.hincrby(key, "attempt", 1)
        raw = await r.hgetall(key)

        budget = RetryBudget(
            task_id=task_id,
            attempt=attempt,
            max_attempts=int(raw.get("max_attempts", "3")),
            base_delay=float(raw.get("base_delay", "1.0")),
            max_delay=float(raw.get("max_delay", "60.0")),
            exponential_base=float(raw.get("exponential_base", "2.0")),
            jitter=float(raw.get("jitter", "0.3")),
        )
        delay = budget.compute_delay(attempt)
        return attempt, delay

    async def should_retry(self, task_id: str, error: str) -> tuple[bool, FailureKind, RetryBudget | None]:
        """
        Full retry decision: classify + budget check.
        Returns (should_retry, failure_kind, current_budget).
        """
        budget = await self.get_budget(task_id)
        if budget is None:
            budget = RetryBudget(task_id=task_id)
            await self.init_budget(task_id, budget)

        kind = FailureClassifier.classify(error)

        if kind == FailureKind.FATAL:
            return False, kind, budget

        can = budget.can_retry(budget.attempt, kind)
        return can, kind, budget

    async def record_success(self, task_id: str) -> None:
        """Clear budget on success."""
        r = await self._get_redis()
        await r.delete(f"{self.BUDGET_PREFIX}{task_id}")


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED   = "closed"    # normal operation
    OPEN     = "open"      # failing → reject calls
    HALF_OPEN = "half_open" # testing recovery


@dataclass
class CircuitConfig:
    failure_threshold: int = 5       # failures before OPEN
    success_threshold: int = 2       # successes in HALF-OPEN to CLOSE
    open_timeout: float = 30.0       # seconds before HALF-OPEN
    half_open_max_calls: int = 3     # calls allowed in HALF_OPEN


class CircuitBreaker:
    """
    Per-dependency circuit breaker with Redis-backed state.

    Keys:
      cb:<name>:state         — String: CLOSED | OPEN | HALF_OPEN
      cb:<name>:failures      — Counter
      cb:<name>:last_change   — Timestamp of last state change
      cb:<name>:half_open_calls — Counter for half-open test calls
    """

    CB_PREFIX = "cb:"

    def __init__(
        self,
        name: str,
        redis_url: str = "redis://localhost:6379",
        config: Optional[CircuitConfig] = None,
    ):
        self.name = name
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url
        self.config = config or CircuitConfig()

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def _key(self, suffix: str) -> str:
        return f"{self.CB_PREFIX}{self.name}:{suffix}"

    async def get_state(self) -> CircuitState:
        r = await self._get_redis()
        raw = await r.get(await self._key("state"))
        if raw is None:
            return CircuitState.CLOSED
        return CircuitState(raw)

    async def _set_state(self, state: CircuitState) -> None:
        r = await self._get_redis()
        await r.set(await self._key("state"), state.value)
        await r.set(await self._key("last_change"), str(time.time()))

    async def _get_failures(self) -> int:
        r = await self._get_redis()
        val = await r.get(await self._key("failures"))
        return int(val or 0)

    async def _increment_failures(self) -> int:
        r = await self._get_redis()
        return await r.incr(await self._key("failures"))

    async def _reset_failures(self) -> None:
        r = await self._get_redis()
        await r.set(await self._key("failures"), "0")
        await r.delete(await self._key("half_open_calls"))
        await r.delete(f"{self.CB_PREFIX}{self.name}:half_open_successes")

    async def _get_last_change(self) -> float:
        r = await self._get_redis()
        val = await r.get(await self._key("last_change"))
        return float(val) if val else 0.0

    async def _inc_half_open_calls(self) -> int:
        r = await self._get_redis()
        return await r.incr(await self._key("half_open_calls"))

    async def _get_half_open_calls(self) -> int:
        r = await self._get_redis()
        val = await r.get(await self._key("half_open_calls"))
        return int(val or 0)

    async def can_execute(self) -> tuple[bool, CircuitState]:
        """
        Check if execution is allowed.
        Returns (allowed, current_state).
        If OPEN → checks timeout for transition to HALF_OPEN.
        If HALF_OPEN → limits concurrent test calls.
        """
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True, state

        if state == CircuitState.OPEN:
            last_change = await self._get_last_change()
            if time.time() - last_change >= self.config.open_timeout:
                await self._set_state(CircuitState.HALF_OPEN)
                return True, CircuitState.HALF_OPEN
            return False, state

        if state == CircuitState.HALF_OPEN:
            calls = await self._get_half_open_calls()
            if calls >= self.config.half_open_max_calls:
                return False, state
            await self._inc_half_open_calls()
            return True, state

        return False, state

    async def record_success(self) -> None:
        """Call on successful execution."""
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            r = await self._get_redis()
            key = f"{self.CB_PREFIX}{self.name}:half_open_successes"
            successes = await r.incr(key)
            await r.expire(key, 60)
            if successes >= self.config.success_threshold:
                await self._reset_failures()
                await self._set_state(CircuitState.CLOSED)
        elif state == CircuitState.CLOSED:
            await self._reset_failures()

    async def record_failure(self) -> None:
        """Call on failed execution."""
        state = await self.get_state()
        await self._increment_failures()

        if state == CircuitState.HALF_OPEN:
            await self._set_state(CircuitState.OPEN)
        elif state == CircuitState.CLOSED:
            failures = await self._get_failures()
            if failures >= self.config.failure_threshold:
                await self._set_state(CircuitState.OPEN)

    async def get_status(self) -> dict:
        """Full status for /metrics or debugging."""
        state = await self.get_state()
        return {
            "circuit": self.name,
            "state": state.value,
            "failures": await self._get_failures(),
            "last_change": await self._get_last_change(),
            "half_open_calls": await self._get_half_open_calls(),
            "config_failure_threshold": self.config.failure_threshold,
            "config_open_timeout": self.config.open_timeout,
        }


# ── Circuit Breaker Registry ─────────────────────────────────────────────────

class CircuitBreakerRegistry:
    """
    Central registry for all circuit breakers.
    Pre-built instances for known dependencies.
    """

    DEFAULTS = {
        "ollama": CircuitConfig(failure_threshold=3, open_timeout=30.0),
        "redis":  CircuitConfig(failure_threshold=5, open_timeout=10.0),
        "qdrant": CircuitConfig(failure_threshold=3, open_timeout=45.0),
    }

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._cache: dict[str, CircuitBreaker] = {}

    def get(self, name: str, config: Optional[CircuitConfig] = None) -> CircuitBreaker:
        if name not in self._cache:
            cfg = config or self.DEFAULTS.get(name)
            self._cache[name] = CircuitBreaker(name, self._redis_url, cfg)
        return self._cache[name]

    def get_all_statuses(self) -> list[dict]:
        return [cb.get_status() for cb in self._cache.values()]


# ── Guarded Call ─────────────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when circuit breaker is OPEN."""
    def __init__(self, circuit: str, retry_after: float):
        self.circuit = circuit
        self.retry_after = retry_after
        super().__init__(f"Circuit '{circuit}' is OPEN. Retry after {retry_after:.1f}s")


async def guarded(
    cb: CircuitBreaker,
    coro: Callable,
    *args, **kwargs,
) -> any:
    """
    Execute `coro(*args, **kwargs)` through circuit breaker.
    Raises CircuitOpenError if blocked.
    """
    allowed, state = await cb.can_execute()
    if not allowed:
        raise CircuitOpenError(cb.name, cb.config.open_timeout)

    try:
        result = await coro(*args, **kwargs)
        await cb.record_success()
        return result
    except Exception as e:
        await cb.record_failure()
        raise
