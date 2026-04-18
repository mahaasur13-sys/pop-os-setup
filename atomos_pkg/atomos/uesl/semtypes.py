"""
UESL v1 — Core semantic types.
All types are frozen/immutable where possible.
"""
from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field, fields
from typing import Any, FrozenSet


# ── Execution result ──────────────────────────────────────────────────────

class ExecutionResult(Enum):
    """Terminal decision from UESLEngine.execute()."""
    APPROVED            = auto()  # CCL contract satisfied, proceed to commit
    REJECTED_CONSENSUS  = auto()  # CCL contract violated — reject
    REJECTED_PARTITION  = auto()  # partition detected — block quorum
    REJECTED_BYZANTINE  = auto()  # corruption / non-detected anomaly
    PENDING              = auto()  # more ACKs needed
    PARTITION_BLOCK     = auto()  # cross-partition send blocked at DRL
    DROPPED              = auto()  # DRL dropped the message
    DELAYED              = auto()  # DRL holding message (not yet deliverable)


class ContractDecision(Enum):
    """CCL-level contract evaluation result."""
    APPROVED = auto()
    REJECTED  = auto()


class PartitionState(Enum):
    """Partition awareness state at execution time."""
    HEALTHY      = auto()   # all nodes reachable
    PARTITIONED  = auto()   # some nodes isolated
    HEALING      = auto()   # partition resolving


# ── UESL Event ────────────────────────────────────────────────────────────

class UESLEventType(Enum):
    """Semantic event types flowing through UESL."""
    SEND              = auto()
    ACK_RECEIVED      = auto()
    NACK_RECEIVED     = auto()
    QUORUM_REACHED    = auto()
    PARTITION_DETECTED = auto()
    PARTITION_HEALED  = auto()
    CONTRACT_APPROVED  = auto()
    CONTRACT_REJECTED  = auto()
    BYZANTINE_FLAGGED  = auto()
    DELIVERED         = auto()
    EXECUTION_COMMIT   = auto()
    EXECUTION_REJECT   = auto()


@dataclass(frozen=True)
class UESLEvent:
    """
    Immutable event flowing through UESL pipeline.
    Captures full causal history for replay.
    """
    event_id:    str
    event_type:  UESLEventType
    msg_id:      str
    sender:      str
    receiver:    str
    term:        int                    # Raft-style term for leader election
    partition_state: PartitionState
    clock_vector: tuple[tuple[str, int], ...]  # (node, lamport_ts) pairs
    drl_flags:   tuple[str, ...]         # distortion flags applied by DRL
    ccl_approved: bool
    contract_snapshot: str               # serialized TrackerSnapshot hash
    causal_index: int                    # sequence number for replay ordering

    def with_contract(self, decision: ContractDecision) -> UESLEvent:
        """Return new event with updated CCL decision."""
        return UESLEvent(
            event_id=self.event_id,
            event_type=UESLEventType.CONTRACT_APPROVED if decision == ContractDecision.APPROVED
                       else UESLEventType.CONTRACT_REJECTED,
            msg_id=self.msg_id,
            sender=self.sender,
            receiver=self.receiver,
            term=self.term,
            partition_state=self.partition_state,
            clock_vector=self.clock_vector,
            drl_flags=self.drl_flags,
            ccl_approved=decision == ContractDecision.APPROVED,
            contract_snapshot=self.contract_snapshot,
            causal_index=self.causal_index,
        )


# ── ExecutionContract ────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ExecutionContract:
    """
    Unified semantic envelope bridging DRL distortion and CCL contracts.

    Produced by DRLToCCLAdapter.translate() — consumed by UESLEngine.execute().
    Frozen: once created, fields cannot be changed (pure functional).
    """
    msg_id:            str
    sender:            str
    receiver:          str
    term:              int
    quorum_required:   int
    pending_nodes:     FrozenSet[str]     # nodes expected to ACK
    partition_state:   PartitionState
    clock_vector:      tuple[tuple[str, int], ...]
    drl_dropped:       bool
    drl_delayed:       bool
    drl_duplicated:    bool
    drl_corrupted:     bool
    drl_reordered:     bool
    ccl_approved:      bool
    ccl_reject_reason: str
    causal_index:      int                # must match UESLEvent.causal_index

    def is_final(self) -> bool:
        """True = contract has reached terminal state (ACKED or NACKED)."""
        return self.ccl_reject_reason != "" or (
            len(self.pending_nodes) == 0 and self.ccl_approved
        )

    def safety_check(self) -> tuple[bool, str]:
        """
        Run hard invariant checks on the contract itself.
        Returns (ok, reason).
        """
        # I3: Partition Safety — if partitioned, quorum MUST NOT proceed
        if self.partition_state == PartitionState.PARTITIONED:
            if self.ccl_approved:
                return False, "I3_VIOLATION: contract approved during partition"
            return True, "partitioned — commit blocked"

        # Byzantine: corrupted message must be rejected before quorum
        if self.drl_corrupted and self.ccl_approved:
            return False, "BYZANTINE: corrupted message approved"

        return True, "OK"

    def as_dict(self) -> dict:
        return {
            "msg_id":           self.msg_id,
            "sender":           self.sender,
            "receiver":         self.receiver,
            "term":             self.term,
            "quorum_required":  self.quorum_required,
            "pending_nodes":    set(self.pending_nodes),
            "partition_state":  self.partition_state.name,
            "clock_vector":     dict(self.clock_vector),
            "drl_dropped":      self.drl_dropped,
            "drl_delayed":      self.drl_delayed,
            "drl_duplicated":   self.drl_duplicated,
            "drl_corrupted":    self.drl_corrupted,
            "drl_reordered":    self.drl_reordered,
            "ccl_approved":     self.ccl_approved,
            "ccl_reject_reason": self.ccl_reject_reason,
            "causal_index":     self.causal_index,
        }
