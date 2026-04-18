"""
ATOMFederationOS v4.2 — UESL: Unified Execution Semantic Layer

Architecture:
    DRL (reality distortion: drop/delay/dup/corrupt/partition)
         ↓  DRLToCCLAdapter.translate()
    UESL  ←  ExecutionContract (unified semantic envelope)
         ↓  UESLEngine.execute()
    CCL   ←  QuorumContract.validate_ack() / InvariantEngine
         ↓
    F2/F3 (quorum engine / execution kernel)
         ↓
    DESC  (event sourcing log / replay)

UESL is the SINGLE ENTRY POINT for all distributed execution.
No consensus logic exists outside UESL.
"""
from atomos.uesl.engine import UESLEngine, ExecutionResult, ExecutionContract
from atomos.uesl.adapter import DRLToCCLAdapter
from atomos.uesl.statestore import UESLState
from atomos.uesl.semtypes import (
    UESLEvent,
    UESLEventType,
    PartitionState,
    ContractDecision,
)

__all__ = [
    "UESLEngine",
    "ExecutionResult",
    "ExecutionContract",
    "DRLToCCLAdapter",
    "UESLState",
    "UESLEvent",
    "UESLEventType",
    "PartitionState",
    "ContractDecision",
]
