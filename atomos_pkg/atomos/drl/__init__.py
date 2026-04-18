"""
ATOMFederationOS v4.1 — DRL v1: DISTRIBUTED REALITY LAYER

Sits strictly between:
    CCL / F2-F8 (logic layer)
           ↓
    DRL v1 (reality distortion layer)
           ↓
    Transport / OS / Network (physical layer)

DRL does NOT:
  - change consensus logic
  - decide correctness
  - modify CCL/F2 contracts

DRL MUST:
  - distort delivery reality (loss/delay/dup/reorder/partition)
  - be deterministic given same seed
  - expose all distortion as observable metadata
  - fail-safe (never block indefinitely)

Validation targets:
  - quorum correctness under loss
  - no double-commit under duplication
  - DESC replay determinism preserved
  - CCL contract invariants still valid
"""

from atomos.drl.message import DRLMessage
from atomos.drl.transport import DRLTransportLayer, TransportConfig
from atomos.drl.clock import DRLClock, ClockType
from atomos.drl.partition import PartitionModel, PartitionConfig
from atomos.drl.failures import FailureEngine, FailureConfig, FaultKind
from atomos.drl.gateway import DRLGateway

__all__ = [
    "DRLMessage",
    "DRLTransportLayer", "TransportConfig",
    "DRLClock", "ClockType",
    "PartitionModel", "PartitionConfig",
    "FailureEngine", "FailureConfig", "FaultKind",
    "DRLGateway",
]
