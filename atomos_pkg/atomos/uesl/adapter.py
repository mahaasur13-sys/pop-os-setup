"""
UESL v1 — DRL ↔ CCL Bridge Adapter.

Translates DRLMessage envelope into ExecutionContract (CCL-ready semantic envelope).
This is the ONLY translation layer between DRL and CCL.
All other CCL calls must go through UESLEngine, never directly.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import FrozenSet

from atomos.drl.message import DRLMessage
from atomos.drl.gateway import DRLGateway
from atomos.drl.partition import PartitionModel
from atomos.runtime.ccl_v1 import TrackerSnapshot, QuorumContract, AckSemantic, AckDecision
from atomos.uesl.semtypes import ExecutionContract, PartitionState


class DRLToCCLAdapter:
    """
    Bridge: DRLMessage (with distortion flags) → ExecutionContract (CCL semantics).

    This adapter is PURE — no side effects, no execution.
    It only translates the DRL envelope into CCL-ready form.

    Usage:
        adapter = DRLToCCLAdapter(node_id="A", quorum_size=3, peers=["A","B","C"])
        contract = adapter.translate(drl_message)
    """

    def __init__(
        self,
        node_id: str,
        peers: list[str],
        quorum_size: int,
        partition_model: PartitionModel | None = None,
    ):
        self.node_id = node_id
        self.peers = set(peers)
        self.all_nodes = self.peers | {node_id}
        self.quorum_size = quorum_size
        self._partition = partition_model

    def _resolve_partition_state(self, msg: DRLMessage) -> PartitionState:
        """Query DRL partition model for current partition status."""
        if self._partition is None:
            return PartitionState.HEALTHY
        if not self._partition.can_communicate(self.node_id, msg.sender):
            return PartitionState.PARTITIONED
        # Check all peers — if any unreachable, consider partitioned
        unreachable = [
            p for p in self.peers
            if p != msg.sender and not self._partition.can_communicate(self.node_id, p)
        ]
        if unreachable:
            return PartitionState.PARTITIONED
        return PartitionState.HEALTHY

    def _build_clock_vector(self, msg: DRLMessage, gateway: DRLGateway) -> tuple:
        """Build Lamport vector from gateway clock + incoming message."""
        local_ts = gateway.now_clock()
        remote_ts = msg.lamport_ts
        merged = max(local_ts, remote_ts) + 1
        # Include all known nodes in vector (pairs of node_id → lamport_ts)
        return tuple(sorted([
            (self.node_id, merged),
            (msg.sender, msg.lamport_ts),
        ]))

    def _drl_flags_from_message(self, msg: DRLMessage) -> tuple[str, ...]:
        """Extract distortion flags as a tuple of strings."""
        flags = []
        if msg.dropped:
            flags.append("DROPPED")
        if msg.delivery_delay > 0.0:
            flags.append("DELAYED")
        if msg.duplicated:
            flags.append("DUPLICATED")
        if msg.reordered:
            flags.append("REORDERED")
        # corruption is not a DRLMessage field — inferred by caller
        return tuple(flags)

    def _resolve_quorum_nodes(self, msg: DRLMessage, gateway: DRLGateway) -> FrozenSet[str]:
        """
        Determine which nodes should be in the pending ACK set.
        Excludes: self (no self-ACK), dropped nodes, crashed nodes.
        """
        pending = set()
        for peer in self.peers:
            if peer == self.node_id:
                continue
            if not gateway.can_reach(peer):
                continue
            if gateway.is_crashed(peer):
                continue
            pending.add(peer)
        return frozenset(pending)

    def translate(
        self,
        msg: DRLMessage,
        gateway: DRLGateway,
        ccl_snapshot: TrackerSnapshot | None = None,
        is_corrupted: bool = False,
    ) -> ExecutionContract:
        """
        Translate DRLMessage into ExecutionContract.

        Parameters
        ----------
        msg           : DRLMessage with DRL-layer distortion flags
        gateway       : DRLGateway instance (for clock, partition, peers)
        ccl_snapshot  : Current TrackerSnapshot (for pending ACK set)
        is_corrupted  : True if FailureEngine marked this message corrupted

        Returns
        -------
        ExecutionContract — frozen semantic envelope for CCL evaluation
        """
        # Extract term from payload (Raft-style) or default to 0
        term = 0
        if msg.payload is not None and isinstance(msg.payload, dict):
            term = msg.payload.get("term", 0)

        partition_state = self._resolve_partition_state(msg)
        pending_nodes = self._resolve_quorum_nodes(msg, gateway)
        clock_vector = self._build_clock_vector(msg, gateway)

        # DRL-level distortion flags
        drl_dropped    = msg.dropped
        drl_delayed    = msg.delivery_delay > 0.0
        drl_duplicated = msg.duplicated
        drl_reordered  = msg.reordered
        drl_corrupted  = is_corrupted

        # CCL-level evaluation — always run even if DRL dropped/damaged
        snapshot = ccl_snapshot or TrackerSnapshot(
            status="PENDING",
            acks=frozenset(),
            pending=pending_nodes,
            quorum_size=self.quorum_size,
        )

        # Pre-CCL rejection rules (I3: Partition Safety)
        if partition_state == PartitionState.PARTITIONED:
            ccl_approved = False
            ccl_reject_reason = "PARTITION_DETECTED"
        elif is_corrupted:
            ccl_approved = False
            ccl_reject_reason = "BYZANTINE_CORRUPTION"
        elif drl_dropped:
            # DRL already dropped it — this contract is informational only
            ccl_approved = False
            ccl_reject_reason = "DRL_DROPPED"
        else:
            ccl_approved = True  # CCL will re-evaluate in UESLEngine.execute()
            ccl_reject_reason = ""

        # Serialized snapshot for replay determinism
        contract_snapshot = (
            f"{snapshot.status}:{sorted(snapshot.acks)}:{sorted(snapshot.pending)}"
            f":{snapshot.quorum_size}"
        )

        return ExecutionContract(
            msg_id=msg.msg_id,
            sender=msg.sender,
            receiver=msg.receiver,
            term=term,
            quorum_required=self.quorum_size,
            pending_nodes=pending_nodes,
            partition_state=partition_state,
            clock_vector=clock_vector,
            drl_dropped=drl_dropped,
            drl_delayed=drl_delayed,
            drl_duplicated=drl_duplicated,
            drl_corrupted=drl_corrupted,
            drl_reordered=drl_reordered,
            ccl_approved=ccl_approved,
            ccl_reject_reason=ccl_reject_reason,
            causal_index=0,  # set by UESLEngine
        )
