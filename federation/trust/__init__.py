"""
federation.trust — v9.5 Distributed Trust Consistency Layer

Modules:
  trust_vector          — TrustVector, TrustEntry, TrustDelta
  ledger_reconciliation — deterministic merge function
  trust_sync_protocol   — gossip protocol for trust state
"""

from federation.trust.trust_vector import TrustEntry, TrustDelta, TrustVector
from federation.trust.ledger_reconciliation import (
    MergeDecision, ConflictReport, LedgerReconciliation,
)
from federation.trust.trust_sync_protocol import (
    TrustMessageType, TrustSyncMessage, PeerTrustState, TrustSyncProtocol,
)

__all__ = [
    "TrustEntry",
    "TrustDelta",
    "TrustVector",
    "MergeDecision",
    "ConflictReport",
    "LedgerReconciliation",
    "TrustMessageType",
    "TrustSyncMessage",
    "PeerTrustState",
    "TrustSyncProtocol",
]
