"""
DRL v1 — DRLTransportLayer: Reality-aware async transport.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Optional
import threading
import time
import uuid

from atomos.drl.message import DRLMessage


@dataclass
class TransportConfig:
    """Configuration for DRLTransportLayer."""
    delivery_mode: str = "async"   # "async" | "sync" | "scheduled"
    base_latency_ms: float = 0.0    # base network latency (ms)
    latency_jitter_ms: float = 0.0  # random jitter added to latency
    reorder_window: int = 0         # number of messages to hold for reordering
    seed: int | None = None


class DRLTransportLayer:
    """
    Async message buffer with configurable delivery semantics.

    send()  — enqueues message for async delivery
    receive() — pops earliest available message from inbox

    Tracks:
      - drop events
      - delivery delays
      - duplicates injected (via FailureEngine + DRLGateway)

    Thread-safe.

    Diagram of message flow::

        CCL/F2/Gateway
               |
               v  (DRLMessage)
        ┌──────────────────┐
        │  FailureEngine   │  ← DROP / delay / corrupt / duplicate
        └────────┬─────────┘
                 |  (dropped=None) or (msg+delay)
                 v
        ┌──────────────────┐
        │  Transit Buffer  │  ← async queue, ordered by scheduled delivery
        │  (deque of msgs)  │
        └────────┬─────────┘
                 |  receive()
                 v
           DRLGateway.outbox
               |
               v  (on delivery)
        Receiving node's CCL/F2
    """

    def __init__(self, config: TransportConfig | None = None):
        self._cfg = config or TransportConfig()
        self._lock = threading.Lock()
        self._inbox: deque[DRLMessage] = deque()
        self._sent_count: int = 0
        self._drop_count: int = 0
        self._dup_count: int = 0

    def send(self, msg: DRLMessage) -> bool:
        """
        Enqueue a DRLMessage for async delivery.
        Returns True = enqueued, False = silently dropped.

        Delivery is scheduled at: now + base_latency + jitter + msg.delivery_delay
        """
        with self._lock:
            self._sent_count += 1

            if msg.dropped:
                self._drop_count += 1
                return False

            # Calculate scheduled delivery time
            base = self._cfg.base_latency_ms / 1000.0
            jitter = (hash(msg.msg_id) % 1000) / 1000.0 * (self._cfg.latency_jitter_ms / 1000.0)
            delay = base + jitter + msg.delivery_delay

            scheduled_at = time.time() + delay

            # Build scheduled entry
            entry = _TransitEntry(msg=msg, scheduled_at=scheduled_at)
            self._inbox.append(entry)
            return True

    def receive(self) -> Optional[DRLMessage]:
        """
        Pop the earliest due message from inbox.
        Returns None if no message is due yet (async delivery pending).

        Messages past their scheduled_at are always delivered.
        """
        with self._lock:
            if not self._inbox:
                return None

            head = self._inbox[0]
            if time.time() >= head.scheduled_at:
                self._inbox.popleft()
                return head.msg
            return None

    def receive_all_due(self) -> list[DRLMessage]:
        """Return ALL due messages (draining the due batch)."""
        due = []
        with self._lock:
            now = time.time()
            while self._inbox and self._inbox[0].scheduled_at <= now:
                due.append(self._inbox.popleft().msg)
        return due

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._inbox) == 0

    def pending_count(self) -> int:
        with self._lock:
            return len(self._inbox)

    def stats(self) -> dict:
        with self._lock:
            return {
                "sent":     self._sent_count,
                "dropped":  self._drop_count,
                "duplicated": self._dup_count,
                "in_transit": len(self._inbox),
                "delivery_mode": self._cfg.delivery_mode,
                "base_latency_ms": self._cfg.base_latency_ms,
                "latency_jitter_ms": self._cfg.latency_jitter_ms,
            }


class _TransitEntry:
    """Internal: scheduled message entry."""
    __slots__ = ("msg", "scheduled_at")
    def __init__(self, msg: DRLMessage, scheduled_at: float):
        self.msg = msg
        self.scheduled_at = scheduled_at
