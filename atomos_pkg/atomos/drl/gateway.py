"""
DRL v1 — DRLGateway: Main entry point for all cross-node communication.
Sits between CCL/F2 logic and the physical transport layer.

Responsibilities:
  1. Apply failure injection (loss/delay/dup) via FailureEngine
  2. Enforce partition rules via PartitionModel
  3. Advance DRLClock on send/receive
  4. Route messages through DRLTransportLayer
  5. Handle broadcast (fan-out)
  6. Support deterministic chaos mode (seed-based replay)

All distortion metadata is embedded in DRLMessage.flags — the
receiving CCL/F2 layer can reason about it.

Usage:
    gateway = DRLGateway(node_id="node-A", peers=["node-B", "node-C"])

    # Send (CCL/F2 calls this):
    gateway.send(sender="node-A", receiver="node-B", payload={"term": 3, "type": "vote"})

    # Deliver (CCL/F2 calls this in its event loop):
    for msg in gateway.deliver():
        process(msg)   # msg is DRLMessage
"""
from __future__ import annotations
from collections import deque
from typing import Any, Optional
import threading
import time
import uuid

from atomos.drl.message import DRLMessage
from atomos.drl.transport import DRLTransportLayer, TransportConfig
from atomos.drl.clock import DRLClock, ClockType
from atomos.drl.partition import PartitionModel, PartitionConfig
from atomos.drl.failures import FailureEngine, FailureConfig


class DRLGateway:
    """
    Central ingress/egress point for all cross-node messages.

    Pipeline per send()::

        CCL/F2 calls send()
              |
              v
        [DRLGateway.send()]
              |
              +-- tick local DRLClock
              |
              +-- FailureEngine.process()  → drop / delay / corrupt
              |       (returns None = drop, (msg, delay, corrupt) = proceed)
              |
              +-- PartitionModel.can_communicate()  → block if partitioned
              |
              +-- DRLTransportLayer.send()  → async inbox
              |
              +-- if dup: inject duplicate through same pipeline
              |
              v
        DRLTransportLayer async buffer

    Pipeline per deliver()::

        DRLTransportLayer.receive()  → due DRLMessage
              |
              +-- merge remote Lamport timestamp into local DRLClock
              |
              +-- mark delivery_delay in DRLMessage
              |
              v
        CCL/F2 receives DRLMessage with distortion flags
    """

    def __init__(
        self,
        node_id: str,
        peers: list[str],
        transport_cfg: TransportConfig | None = None,
        failure_cfg: FailureConfig | None = None,
        partition_cfg: PartitionConfig | None = None,
        seed: int | None = None,
    ):
        self.node_id = node_id
        self.peers = set(peers)

        self._transport  = DRLTransportLayer(transport_cfg or TransportConfig(seed=seed))
        self._clock      = DRLClock(ClockType.LAMPORT)
        self._partition  = PartitionModel(partition_cfg or PartitionConfig(seed=seed))
        self._failure    = FailureEngine(failure_cfg or FailureConfig(seed=seed))

        self._lock       = threading.Lock()
        self._outbox: deque[DRLMessage] = deque()

        # Metrics
        self._sent_count: int = 0
        self._drop_count: int = 0
        self._dup_count: int = 0
        self._block_count: int = 0

    # ── Send ──────────────────────────────────────────────────────────────────

    def send(
        self,
        sender: str,
        receiver: str,
        payload: Any,
        lamport_ts: int | None = None,
    ) -> Optional[str]:
        """
        Send a message through the DRL pipeline.

        Parameters
        ----------
        sender    : node ID of the logical sender
        receiver  : node ID of the logical receiver (or "BROADCAST")
        payload   : opaque object for CCL/F2 layer
        lamport_ts: optional pre-set Lamport timestamp (for replicated sends)

        Returns
        -------
        msg_id of the sent message, or None if dropped/blocked.
        """
        with self._lock:
            self._sent_count += 1

            # ── 1. Advance local clock ───────────────────────────────────
            ts = lamport_ts if lamport_ts is not None else self._clock.tick()

            # ── 2. Build envelope ─────────────────────────────────────────
            msg = DRLMessage(
                msg_id=uuid.uuid4().hex[:16],
                sender=sender,
                receiver=receiver,
                payload=payload,
                lamport_ts=ts,
                physical_ts=time.time(),
                delivery_delay=0.0,
                dropped=False,
                duplicated=False,
                reordered=False,
                path=(sender,),
            )

            # ── 3. Partition check ──────────────────────────────────────
            if receiver != "BROADCAST":
                if not self._partition.can_communicate(sender, receiver):
                    self._block_count += 1
                    return None

            # ── 4. Failure injection ─────────────────────────────────────
            result = self._failure.process(msg)
            if result is None:
                # Dropped
                self._drop_count += 1
                return None

            base_msg, delay_sec, is_corrupted = result
            if delay_sec > 0:
                base_msg = base_msg.with_distortion(delay=delay_sec)

            # ── 5. Transport ─────────────────────────────────────────────
            ok = self._transport.send(base_msg)
            if not ok:
                self._drop_count += 1
                return None

            # ── 6. Duplicate injection ──────────────────────────────────
            if self._failure.maybe_duplicate():
                dup = DRLMessage(
                    msg_id=uuid.uuid4().hex[:16],   # new ID for dup
                    sender=base_msg.sender,
                    receiver=base_msg.receiver,
                    payload=base_msg.payload,
                    lamport_ts=base_msg.lamport_ts,
                    physical_ts=time.time(),
                    delivery_delay=0.0,
                    dropped=False,
                    duplicated=True,
                    reordered=False,
                    path=base_msg.path,
                )
                self._transport.send(dup)
                self._dup_count += 1

            return base_msg.msg_id

    def broadcast(
        self,
        sender: str,
        payload: Any,
        exclude: set[str] | None = None,
    ) -> list[str]:
        """
        Fan-out send to all peers, respecting partition + failure rules.
        Returns list of successfully enqueued msg_ids.
        """
        excluded = exclude or set()
        results = []
        for peer in self.peers:
            if peer in excluded:
                continue
            msg_id = self.send(sender=sender, receiver=peer, payload=payload)
            if msg_id is not None:
                results.append(msg_id)
        return results

    # ── Deliver ───────────────────────────────────────────────────────────────

    def deliver(self) -> list[DRLMessage]:
        """
        Drain all due messages from the transport layer.
        Merges remote Lamport timestamps into local DRLClock.
        Returns list (may be empty).
        """
        messages = self._transport.receive_all_due()
        for msg in messages:
            # Merge remote Lamport timestamp
            self._clock.merge(msg.lamport_ts)
        return messages

    def receive(self) -> Optional[DRLMessage]:
        """Single-message deliver."""
        batch = self.deliver()
        return batch[0] if batch else None

    # ── Clock ────────────────────────────────────────────────────────────────

    def tick_clock(self) -> int:
        """Advance local logical clock. Returns new value."""
        return self._clock.tick()

    def now_clock(self) -> int:
        """Current logical clock value."""
        return self._clock.now()

    # ── Partition ───────────────────────────────────────────────────────────

    def can_reach(self, peer: str) -> bool:
        """Query connectivity to a specific peer."""
        return self._partition.can_communicate(self.node_id, peer)

    def is_partitioned(self) -> bool:
        return self._partition.is_partitioned()

    def heal(self) -> bool:
        """Heal all partitions."""
        return self._partition.heal_partition()

    # ── Failure config ─────────────────────────────────────────────────────

    def update_failure(self, **kwargs):
        """Update failure rates at runtime."""
        self._failure.update_config(**kwargs)

    def is_crashed(self, node_id: str) -> bool:
        return self._failure.is_crashed(node_id)

    def crash_node(self, node_id: str) -> bool:
        return self._failure.crash_node(node_id)

    def heal_node(self, node_id: str) -> bool:
        return self._failure.heal_node(node_id)

    # ── Metrics ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "node_id":       self.node_id,
            "sent":          self._sent_count,
            "dropped":       self._drop_count,
            "duplicated":    self._dup_count,
            "blocked":       self._block_count,
            "in_transit":    self._transport.pending_count(),
            "clock_now":     self._clock.now(),
            "is_partitioned": self.is_partitioned(),
            "transport":     self._transport.stats(),
            "partition":     self._partition.status(),
            "failure":       self._failure.get_config(),
        }
