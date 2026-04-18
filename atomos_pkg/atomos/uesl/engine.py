"""
UESL v1 — Unified Execution Semantic Layer Engine.

UESL is the SINGLE ENTRY POINT for all distributed execution.
No consensus logic exists outside UESL.

Pipeline per execute():
    DRLMessage (with distortion flags from FailureEngine/PartitionModel)
         ↓  DRLToCCLAdapter.translate()
    ExecutionContract (unified semantic envelope)
         ↓  UESLEngine.execute()
    CCL evaluation (QuorumContract + InvariantEngine)
         ↓
    ExecutionResult (APPROVED / REJECTED_* / PENDING)

Hard invariants enforced by UESLEngine:
    I1 — Deterministic Execution
        No randomness outside DRL seed. Same input → same output.
    I2 — Contract Finality
        Once CCL approves → DRL state cannot invalidate it.
    I3 — Partition Safety
        If partition detected: commit quorum MUST NOT proceed.
    I4 — Replay Equivalence
        replay(trace) == live_execution(state)
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from atomos.drl.message import DRLMessage
from atomos.drl.gateway import DRLGateway
from atomos.drl.partition import PartitionModel
from atomos.drl.failures import FailureEngine
from atomos.runtime.ccl_v1 import (
    TrackerSnapshot,
    QuorumContract,
    InvariantEngine,
    AckDecision,
    AckSemantic,
)
from atomos.uesl.semtypes import (
    ExecutionResult,
    ContractDecision,
    PartitionState,
    ExecutionContract,
    UESLEvent,
    UESLEventType,
)
from atomos.uesl.adapter import DRLToCCLAdapter
from atomos.uesl.statestore import UESLState, UESLSnapshot


class UESLEngine:
    """
    Unified Execution Semantic Layer — core engine.

    UESL is the ONLY path from DRL → CCL → execution commit.
    All distributed consensus calls MUST go through UESLEngine.execute().

    Usage:
        gateway  = DRLGateway(node_id="A", peers=["B","C"], seed=42)
        adapter  = DRLToCCLAdapter(node_id="A", peers=["A","B","C"], quorum_size=2)
        state    = UESLState(node_id="A", quorum_size=2, seed=42)
        engine   = UESLEngine(gateway, adapter, state)

        # DRL delivers a message
        for msg in gateway.deliver():
            result = engine.execute(msg, is_corrupted=False)
    """

    def __init__(
        self,
        gateway: DRLGateway,
        adapter: DRLToCCLAdapter,
        state: UESLState,
    ):
        self._gw = gateway
        self._adapter = adapter
        self._state = state

    # ── Main entry point ────────────────────────────────────────────────────

    def execute(
        self,
        msg: DRLMessage,
        is_corrupted: bool = False,
    ) -> tuple[ExecutionResult, ExecutionContract, UESLEvent]:
        """
        Execute one message through the full UESL pipeline.

        Parameters
        ----------
        msg         : DRLMessage from DRLTransportLayer.deliver()
        is_corrupted: True if FailureEngine flagged this message

        Returns
        -------
        (ExecutionResult, ExecutionContract, UESLEvent)
            result  — terminal decision
            contract — full contract with all annotations
            event   — causal event for replay log
        """
        # ── 1. Translate DRL → CCL contract ──────────────────────────────
        ccl_snapshot = self._state.get_tracker(msg.msg_id)
        contract = self._adapter.translate(
            msg=msg,
            gateway=self._gw,
            ccl_snapshot=ccl_snapshot,
            is_corrupted=is_corrupted,
        )

        # ── 2. Hard invariant checks (I3: Partition Safety first) ─────────
        ok, reason = contract.safety_check()
        if not ok:
            result = ExecutionResult.REJECTED_PARTITION
            event = self._build_event(contract, UESLEventType.PARTITION_DETECTED)
            self._state.append_event(event)
            return result, contract, event

        # ── 3. If DRL already dropped it ──────────────────────────────────
        if contract.drl_dropped:
            result = ExecutionResult.DROPPED
            event = self._build_event(contract, UESLEventType.SEND)
            self._state.append_event(event)
            return result, contract, event

        # ── 4. If DRL holding it (delay not yet elapsed) ──────────────────
        if contract.drl_delayed:
            result = ExecutionResult.DELAYED
            event = self._build_event(contract, UESLEventType.SEND)
            self._state.append_event(event)
            return result, contract, event

        # ── 5. Byzantine rejection ─────────────────────────────────────────
        if is_corrupted or contract.drl_corrupted:
            result = ExecutionResult.REJECTED_BYZANTINE
            event = self._build_event(contract, UESLEventType.BYZANTINE_FLAGGED)
            self._state.append_event(event)
            return result, contract, event

        # ── 6. CCL evaluation ─────────────────────────────────────────────
        ccl_result, updated_contract = self._ccl_evaluate(contract)

        # ── 7. Final invariant check (I2: Contract Finality) ─────────────
        if ccl_result == ContractDecision.APPROVED:
            # I2: once CCL approves, DRL distortion cannot revoke it
            # But partition during approval = immediate reject
            if updated_contract.partition_state == PartitionState.PARTITIONED:
                ccl_result = ContractDecision.REJECTED

        # ── 8. Build result ────────────────────────────────────────────────
        if ccl_result == ContractDecision.APPROVED:
            result = ExecutionResult.APPROVED
            event_type = UESLEventType.EXECUTION_COMMIT
            # Persist tracker update
            new_snap = self._build_tracker_from_contract(updated_contract)
            self._state.put_tracker(msg.msg_id, new_snap)
            self._state.commit(msg.msg_id)
        else:
            result = ExecutionResult.REJECTED_CONSENSUS
            event_type = UESLEventType.EXECUTION_REJECT

        event = self._build_event(updated_contract, event_type)
        self._state.append_event(event)

        return result, updated_contract, event

    # ── CCL evaluation ────────────────────────────────────────────────────

    def _ccl_evaluate(
        self,
        contract: ExecutionContract,
    ) -> tuple[ContractDecision, ExecutionContract]:
        """
        Run CCL contract evaluation over the ExecutionContract.
        Returns (decision, updated_contract).
        """
        snapshot = self._state.get_tracker(contract.msg_id)
        if snapshot is None:
            snapshot = TrackerSnapshot(
                status="PENDING",
                acks=frozenset(),
                pending=contract.pending_nodes,
                quorum_size=contract.quorum_required,
            )

        # Check InvariantEngine pre-conditions
        all_ok, inv_results = InvariantEngine.verify_all(snapshot)
        if not all_ok:
            return ContractDecision.REJECTED, replace(
                contract,
                ccl_reject_reason="INVARIANT_VIOLATION",
            )

        # CCL quorum check: is this message from a node in pending set?
        node_id = contract.sender
        ack_decision = QuorumContract.validate_ack(snapshot, node_id)

        if not ack_decision.ok:
            return ContractDecision.REJECTED, replace(
                contract,
                ccl_approved=False,
                ccl_reject_reason=ack_decision.reason,
            )

        # Build new snapshot with this ACK
        new_acks = snapshot.acks | {node_id}
        new_pending = snapshot.pending - {node_id}
        new_status = QuorumContract.expected_transition(
            snapshot.status,
            ack_decision,
            len(new_acks),
            snapshot.quorum_size,
        )
        new_snapshot = TrackerSnapshot(
            status=new_status,
            acks=new_acks,
            pending=new_pending,
            quorum_size=snapshot.quorum_size,
        )
        self._state.put_tracker(contract.msg_id, new_snapshot)

        # Determine if quorum reached
        if new_status == "ACKED":
            return ContractDecision.APPROVED, replace(
                contract,
                ccl_approved=True,
                ccl_reject_reason="",
            )
        else:
            return ContractDecision.REJECTED, replace(
                contract,
                ccl_approved=False,
                ccl_reject_reason="QUORUM_NOT_REACHED",
            )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_event(
        self,
        contract: ExecutionContract,
        event_type: UESLEventType,
    ) -> UESLEvent:
        """Build UESLEvent from ExecutionContract + event type."""
        return UESLEvent(
            event_id=f"ev-{contract.msg_id}-{self._state._causal_index}",
            event_type=event_type,
            msg_id=contract.msg_id,
            sender=contract.sender,
            receiver=contract.receiver,
            term=contract.term,
            partition_state=contract.partition_state,
            clock_vector=contract.clock_vector,
            drl_flags=self._drl_flags_tuple(contract),
            ccl_approved=contract.ccl_approved,
            contract_snapshot=repr(contract),
            causal_index=self._state._causal_index,
        )

    def _drl_flags_tuple(self, contract: ExecutionContract) -> tuple[str, ...]:
        flags = []
        if contract.drl_dropped:
            flags.append("DROPPED")
        if contract.drl_delayed:
            flags.append("DELAYED")
        if contract.drl_duplicated:
            flags.append("DUPLICATED")
        if contract.drl_corrupted:
            flags.append("CORRUPTED")
        if contract.drl_reordered:
            flags.append("REORDERED")
        return tuple(flags)

    def _build_tracker_from_contract(
        self,
        contract: ExecutionContract,
    ) -> TrackerSnapshot:
        """Build TrackerSnapshot from ExecutionContract for persistence."""
        return TrackerSnapshot(
            status="ACKED",
            acks=frozenset({contract.sender}),
            pending=contract.pending_nodes,
            quorum_size=contract.quorum_required,
        )

    # ── Replay ──────────────────────────────────────────────────────────────

    def replay(self, event_log: list[UESLEvent]) -> UESLSnapshot:
        """
        Replay an event log and verify final state matches live execution.
        Returns final UESLSnapshot from replay.
        """
        # Clone state for replay (fresh instance)
        replay_state = UESLState(
            node_id=self._state.node_id,
            quorum_size=self._state.quorum_size,
            seed=None,
        )

        for event in event_log:
            # Rebuild contract from event (simplified — full impl would deserialize)
            snapshot = replay_state.get_tracker(event.msg_id)
            if snapshot is not None:
                continue  # already processed

            # Advance causal index
            replay_state._causal_index = event.causal_index

            if event.event_type in (UESLEventType.EXECUTION_COMMIT,):
                replay_state.commit(event.msg_id)

            replay_state.append_event(event)

        return replay_state.current_snapshot()

    def verify_replay_equivalence(
        self,
        live_snapshot: UESLSnapshot,
        replay_snapshot: UESLSnapshot,
    ) -> bool:
        """
        Verify I4: replay(trace) == live_execution(state).
        Compares hash fields for fast equality check.
        """
        return live_snapshot.hash == replay_snapshot.hash
