"""
DRL v1 — FailureEngine: Probabilistic failure injection.
Applies: crash, packet loss, corruption, delay to DRLMessage envelope.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Set
from enum import Enum
import threading
import random


class FaultKind(Enum):
    """Categories of failures that FailureEngine can inject."""
    DROP      = "drop"       # probabilistic message loss
    DUPLICATE = "duplicate"  # message duplication
    DELAY     = "delay"      # artificial latency injection
    CORRUPT   = "corrupt"    # payload corruption (tag only)
    CRASH     = "crash"      # node goes dark (tracked separately)


@dataclass
class FailureConfig:
    """Probabilistic failure rates. All default to 0 (no failures)."""
    drop_rate:     float = 0.0   # 0.0–1.0
    dup_rate:      float = 0.0   # 0.0–1.0
    delay_min_ms:  float = 0.0   # minimum artificial delay (ms)
    delay_max_ms:  float = 0.0   # maximum artificial delay (ms)
    corrupt_rate:  float = 0.0   # 0.0–1.0
    seed:          int | None = None  # None = system entropy


class FailureEngine:
    """
    Applies probabilistic distortions to DRLMessage envelopes.

    Given a message:
      1. Decide (probabilistically) whether to drop it  → return None
      2. Decide (probabilistically) whether to delay it → set delivery_delay
      3. Decide (probabilistically) whether to duplicate → return (original, dup)

    Thread-safe. Deterministic when seeded.
    """

    def __init__(self, config: FailureConfig | None = None):
        self._cfg = config or FailureConfig()
        self._lock = threading.Lock()
        self._rng = random.Random(self._cfg.seed)

        # Per-node crash state
        self._crashed: Set[str] = set()

    # ── Core processing ─────────────────────────────────────────────────────────

    def process(self, msg) -> tuple | None:
        """
        Apply failure injection to a DRLMessage.

        Returns:
          None           → message should be dropped
          (msg,)         → normal delivery (possibly with delay set)
          (msg, dup_msg) → normal delivery + one injected duplicate

        The caller (DRLGateway) decides what to do with None.
        """
        with self._lock:
            # ── 1. Check if receiver is crashed ─────────────────────────
            # Crashed nodes silently drop everything.
            # We don't drop here — we let the message through but mark it.
            # The caller (Gateway) checks is_crashed() separately.
            pass

            # ── 2. Drop check ───────────────────────────────────────────
            if self._cfg.drop_rate > 0 and self._rng.random() < self._cfg.drop_rate:
                return None

            # ── 3. Corruption check ─────────────────────────────────────
            # We tag the message but don't actually corrupt payload
            # (DRL MUST NOT inspect payload)
            is_corrupted = (
                self._cfg.corrupt_rate > 0
                and self._rng.random() < self._cfg.corrupt_rate
            )

            # ── 4. Delay ───────────────────────────────────────────────
            delay_sec = 0.0
            if self._cfg.delay_min_ms > 0 or self._cfg.delay_max_ms > 0:
                delay_range = self._cfg.delay_max_ms - self._cfg.delay_min_ms
                delay_ms = self._cfg.delay_min_ms + self._rng.random() * delay_range
                delay_sec = delay_ms / 1000.0

            # ── 5. Duplicate check ──────────────────────────────────────
            duplicate = None
            if self._cfg.dup_rate > 0 and self._rng.random() < self._cfg.dup_rate:
                # Duplicate is created by Gateway after we return
                pass

            return msg, delay_sec, is_corrupted

    def maybe_drop(self) -> bool:
        """Direct drop check. Returns True = drop this message."""
        with self._lock:
            return self._cfg.drop_rate > 0 and self._rng.random() < self._cfg.drop_rate

    def sample_delay(self) -> float:
        """Sample a random delay in seconds."""
        with self._lock:
            if self._cfg.delay_min_ms == 0 and self._cfg.delay_max_ms == 0:
                return 0.0
            delay_range = self._cfg.delay_max_ms - self._cfg.delay_min_ms
            delay_ms = self._cfg.delay_min_ms + self._rng.random() * delay_range
            return delay_ms / 1000.0

    def maybe_duplicate(self) -> bool:
        """Direct duplicate check. Returns True = inject duplicate."""
        with self._lock:
            return self._cfg.dup_rate > 0 and self._rng.random() < self._cfg.dup_rate

    # ── Crash management ───────────────────────────────────────────────────────

    def crash_node(self, node_id: str) -> bool:
        """Mark a node as crashed."""
        with self._lock:
            self._crashed.add(node_id)
        return True

    def heal_node(self, node_id: str) -> bool:
        """Heal a crashed node."""
        with self._lock:
            self._crashed.discard(node_id)
        return True

    def is_crashed(self, node_id: str) -> bool:
        """Query crash state."""
        with self._lock:
            return node_id in self._crashed

    # ── Config ────────────────────────────────────────────────────────────────

    def update_config(self, **kwargs):
        """Update failure rates at runtime."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._cfg, k):
                    setattr(self._cfg, k, v)

    def get_config(self) -> dict:
        with self._lock:
            return {
                "drop_rate":     self._cfg.drop_rate,
                "dup_rate":      self._cfg.dup_rate,
                "delay_min_ms":  self._cfg.delay_min_ms,
                "delay_max_ms":  self._cfg.delay_max_ms,
                "corrupt_rate":  self._cfg.corrupt_rate,
                "seed":          self._cfg.seed,
                "crashed_nodes": list(self._crashed),
            }
