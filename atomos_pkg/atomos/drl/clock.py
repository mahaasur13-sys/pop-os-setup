"""
DRL v1 — DRLClock: Logical clock model.
Supports Lamport clocks + optional hybrid (physical + logical) mode.
"""
from __future__ import annotations
from enum import Enum
import threading
import time


class ClockType(Enum):
    LAMPORT = "lamport"
    VECTOR = "vector"          # not yet implemented
    HYBRID = "hybrid"           # physical bias + lamport merge


class DRLClock:
    """
    Monotonic logical clock for DRL layer.

    - tick()          : advance own logical time by 1
    - merge(remote)   : incorporate remote timestamp (Lamport merge rule)
    - now()           : current logical time (int)
    - reset()         : reset to 0 (for testing)

    Thread-safe.
    """

    __slots__ = ("_lock", "_local", "_type")

    def __init__(self, clock_type: ClockType = ClockType.LAMPORT):
        self._lock = threading.Lock()
        self._local: int = 0
        self._type = clock_type

    # ── Tick ─────────────────────────────────────────────────────────────────

    def tick(self) -> int:
        """Advance local logical clock by 1. Returns new value."""
        with self._lock:
            self._local += 1
            return self._local

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge(self, remote: int) -> int:
        """
        Lamport merge rule:
            max(local, remote) + 1

        Returns new local clock value after merge.
        """
        with self._lock:
            self._local = max(self._local, remote) + 1
            return self._local

    # ── Query ─────────────────────────────────────────────────────────────────

    def now(self) -> int:
        """Return current logical clock value."""
        with self._lock:
            return self._local

    def reset(self):
        """Reset to 0. For testing only."""
        with self._lock:
            self._local = 0

    # ── Hybrid mode ───────────────────────────────────────────────────────────

    def now_hybrid(self) -> tuple[int, float]:
        """
        HYBRID mode: (logical_ts, physical_ts_μs).
        Physical component uses monotonic μs clock.
        """
        with self._lock:
            physical = time.monotonic()
            return self._local, physical
