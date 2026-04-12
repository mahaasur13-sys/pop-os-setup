"""
Failure Replay Engine v7.0.

Modules:
  event_store         — append-only event log (SQLite)
  replay_engine      — deterministic replay iterator + state reconstruction
  determinism_checker — commutativity, idempotency, convergence checks

Usage:
  from failure_replay import EventStore, ReplayEngine, DeterminismChecker

  store = EventStore(db_path="/tmp/atom_events.db", node_id="node-a")
  engine = ReplayEngine(event_store=store)
  engine.load_config(ReplayConfig(from_ts=ts0))
  for event in engine.replay():
      apply_event(event)
"""

from failure_replay.event_store import EventStore
from failure_replay.replay_engine import (
    ReplayEngine,
    ReplayConfig,
    ReplaySpeed,
    ReplayState,
    StateReconstructor,
)
from failure_replay.determinism_checker import (
    DeterminismChecker,
    DeterminismResult,
    DivergenceEvent,
    ChaosToReplayBridge,
)

__all__ = [
    "EventStore",
    "ReplayEngine",
    "ReplayConfig",
    "ReplaySpeed",
    "ReplayState",
    "StateReconstructor",
    "DeterminismChecker",
    "DeterminismResult",
    "DivergenceEvent",
    "ChaosToReplayBridge",
]
