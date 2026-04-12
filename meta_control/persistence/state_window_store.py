"""
state_window_store.py
~~~~~~~~~~~~~~~~~~~~~
Sliding-window state store for tick-based control loops.
Keeps a bounded history of system snapshots to enable:
  - temporal aggregation (avg stability over window)
  - rollback to recent tick
  - state evolution tracking across ticks

Invariant: S(t) = f(S(t-1), decision(t-1), outcome(t-1))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from collections import deque
import time


@dataclass
class TickState:
    tick: int
    source_states: dict[str, float]          # source_name -> stability_score [0,1]
    control_weights: dict[str, float]       # source_name -> effective_priority
    global_gain: float
    outcome: Optional[float] = None         # None until outcome is recorded
    timestamp: float = field(default_factory=time.time)


class StateWindowStore:
    """
    Sliding-window state store.

    Tracks the last N ticks of system state so that:
      - Temporal verification has history to compare against
      - Proof feedback can access previous decisions/outcomes
      - Gain scheduler has a window for stability aggregation
    """

    def __init__(self, window_size: int = 100) -> None:
        self._window_size = window_size
        self._deque: deque[TickState] = deque(maxlen=window_size)
        self._tick_counter = 0

    # ─── core interface ───────────────────────────────────────────────────────

    def record_tick(
        self,
        source_states: dict[str, float],
        control_weights: dict[str, float],
        global_gain: float,
        outcome: Optional[float] = None,
    ) -> int:
        """
        Append a new tick snapshot.
        Returns the assigned tick number.
        """
        self._tick_counter += 1
        tick = self._tick_counter
        self._deque.append(
            TickState(
                tick=tick,
                source_states=dict(source_states),
                control_weights=dict(control_weights),
                global_gain=global_gain,
                outcome=outcome,
            )
        )
        return tick

    def record_outcome(self, tick: int, outcome: float) -> bool:
        """
        Backfill an outcome for a past tick.
        Returns False if tick not found in window.
        """
        for ts in self._deque:
            if ts.tick == tick:
                ts.outcome = outcome
                return True
        return False

    def get_tick(self, tick: int) -> Optional[TickState]:
        for ts in self._deque:
            if ts.tick == tick:
                return ts
        return None

    def latest_tick(self) -> Optional[TickState]:
        """Most recent tick or None if window is empty."""
        return self._deque[-1] if self._deque else None

    def window(self) -> list[TickState]:
        """All ticks in window, oldest first."""
        return list(self._deque)

    # ─── derived queries ─────────────────────────────────────────────────────

    def source_stability_series(
        self, source: str, last_n: int | None = None
    ) -> list[float]:
        """Stability scores for a source over the last N ticks."""
        ticks = list(self._deque)[-(last_n or self._window_size):]
        return [t.source_states.get(source, 0.0) for t in ticks]

    def outcome_series(self, last_n: int | None = None) -> list[float]:
        """Outcome values (non-None) over the last N ticks."""
        ticks = list(self._deque)[-(last_n or self._window_size):]
        return [t.outcome for t in ticks if t.outcome is not None]

    def avg_stability(self, last_n: int | None = None) -> float:
        """Mean stability across all sources over last N ticks."""
        ticks = list(self._deque)[-(last_n or self._window_size):]
        if not ticks:
            return 1.0
        total = sum(
            sum(s for s in t.source_states.values()) / max(len(t.source_states), 1)
            for t in ticks
        )
        return total / len(ticks)

    def avg_outcome(self, last_n: int | None = None) -> float | None:
        """Mean outcome over last N ticks with recorded outcomes."""
        ticks = list(self._deque)[-(last_n or self._window_size):]
        outcomes = [t.outcome for t in ticks if t.outcome is not None]
        return sum(outcomes) / len(outcomes) if outcomes else None

    def tick_range(self, from_tick: int, to_tick: int) -> list[TickState]:
        """Ticks in a closed interval [from_tick, to_tick]."""
        return [t for t in self._deque if from_tick <= t.tick <= to_tick]

    # ─── rollback ─────────────────────────────────────────────────────────────

    def rollback_to(self, tick: int) -> list[TickState]:
        """
        Remove all ticks after `tick` and return them.
        Allows replay of a decision sequence from an earlier point.
        """
        removed = [t for t in self._deque if t.tick > tick]
        self._deque = deque(
            (t for t in self._deque if t.tick <= tick),
            maxlen=self._window_size,
        )
        return removed

    # ─── introspection ─────────────────────────────────────────────────────────

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def depth(self) -> int:
        return len(self._deque)

    @property
    def current_tick(self) -> int:
        return self._tick_counter
