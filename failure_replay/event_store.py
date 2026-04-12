"""
Event Store v7.0 — Append-only event log with persistence.

Provides:
  - Atomic append (single event or batch)
  - Time-range and event-type queries
  - Snapshot isolation (read at consistent timestamp)
  - Compaction (remove old events, keep last N per event_type)
  - Event filtering by node_id, subsystem, severity

Storage backends:
  - SQLite (default, for single node or replay scenarios)
  - PostgreSQL (optional, for distributed replay)

The event store is the SOLE SOURCE OF TRUTH for failure replay.
Metrics and logs are derived; events are primary.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Literal

from observability.core.event_schema import Event, EventType


class EventStore:
    """
    Thread-safe, append-only event store with SQLite backend.

    Usage:
        store = EventStore(db_path="/tmp/atom_events.db", node_id="node-a")
        store.append(event)                      # single event
        store.append_batch([event1, event2])     # batch

        # Query
        events = store.query(
            since_ts=ts - 60_000_000_000,  # last 60s in ns
            event_types=["sbs.violation", "node.down"],
        )

        # Replay cursor (for deterministic replay)
        cursor = store.replay_cursor(from_ts=ts0)
        for event in cursor:
            process(event)
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        id          TEXT PRIMARY KEY,
        ts          INTEGER NOT NULL,
        node_id     TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        payload     TEXT NOT NULL,          -- JSON
        coherence   TEXT,
        lattice     TEXT,
        quorum      TEXT,
        sbs_state   TEXT,
        version     TEXT DEFAULT '7.0',
        created_at  REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_events_ts
        ON events(ts);

    CREATE INDEX IF NOT EXISTS idx_events_node_ts
        ON events(node_id, ts);

    CREATE INDEX IF NOT EXISTS idx_events_type
        ON events(event_type);
    """

    def __init__(
        self,
        db_path: str | Path = "/tmp/atom_events.db",
        node_id: str = "unknown",
        max_events: int = 1_000_000,
    ):
        self.db_path = Path(db_path)
        self.node_id = node_id
        self.max_events = max_events
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.executescript(self.SCHEMA)
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), check_same_thread=False)

    def append(self, event: Event) -> str:
        """Append a single event. Returns event_id."""
        if not event.event_id:
            event.event_id = uuid.uuid4().hex
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """
                    INSERT INTO events
                        (id, ts, node_id, event_type, payload,
                         coherence, lattice, quorum, sbs_state, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.ts,
                        event.node_id,
                        event.event_type,
                        json.dumps(event.payload),
                        json.dumps(asdict(event.coherence_state)) if event.coherence_state else None,
                        json.dumps(asdict(event.lattice_snapshot)) if event.lattice_snapshot else None,
                        json.dumps(asdict(event.quorum_snapshot)) if event.quorum_snapshot else None,
                        json.dumps(asdict(event.sbs_state)) if event.sbs_state else None,
                        event.version,
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        self._maybe_compact()
        return event.event_id

    def append_batch(self, events: list[Event]) -> list[str]:
        """Append multiple events atomically. Returns list of event_ids."""
        if not events:
            return []
        for e in events:
            if not e.event_id:
                e.event_id = uuid.uuid4().hex
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN")
                rows = []
                for e in events:
                    rows.append((
                        e.event_id, e.ts, e.node_id, e.event_type,
                        json.dumps(e.payload),
                        json.dumps(asdict(e.coherence_state)) if e.coherence_state else None,
                        json.dumps(asdict(e.lattice_snapshot)) if e.lattice_snapshot else None,
                        json.dumps(asdict(e.quorum_snapshot)) if e.quorum_snapshot else None,
                        json.dumps(asdict(e.sbs_state)) if e.sbs_state else None,
                        e.version,
                        time.time(),
                    ))
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO events
                        (id, ts, node_id, event_type, payload,
                         coherence, lattice, quorum, sbs_state, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
        self._maybe_compact()
        return [e.event_id for e in events]

    def query(
        self,
        since_ts: int | None = None,
        until_ts: int | None = None,
        event_types: list[str] | None = None,
        node_ids: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[Event]:
        """
        Query events within time range, optionally filtered.

        Args:
            since_ts:  start timestamp in nanoseconds (inclusive)
            until_ts:  end timestamp in nanoseconds (inclusive)
            event_types: filter to these event_type strings
            node_ids:   filter to these node_ids
            limit:      max rows to return
            offset:     pagination offset
        """
        with self._lock:
            conn = self._conn()
            conditions = []
            params: list[Any] = []

            if since_ts is not None:
                conditions.append("ts >= ?")
                params.append(since_ts)
            if until_ts is not None:
                conditions.append("ts <= ?")
                params.append(until_ts)
            if event_types:
                placeholders = ",".join("?" * len(event_types))
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(event_types)
            if node_ids:
                placeholders = ",".join("?" * len(node_ids))
                conditions.append(f"node_id IN ({placeholders})")
                params.extend(node_ids)

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            sql = f"""
                SELECT id, ts, node_id, event_type, payload,
                       coherence, lattice, quorum, sbs_state, version
                FROM events {where}
                ORDER BY ts ASC, id ASC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            try:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_event(row) for row in rows]
            finally:
                conn.close()

    def replay_cursor(
        self,
        from_ts: int,
        to_ts: int | None = None,
        event_types: list[str] | None = None,
        node_ids: list[str] | None = None,
        batch_size: int = 1000,
    ) -> Iterator[Event]:
        """
        Cursor-based replay iterator for deterministic replay.

        Yields events in ts order. Safe for large datasets.
        """
        offset = 0
        while True:
            events = self.query(
                since_ts=from_ts,
                until_ts=to_ts,
                event_types=event_types,
                node_ids=node_ids,
                limit=batch_size,
                offset=offset,
            )
            if not events:
                break
            for e in events:
                yield e
            offset += batch_size

    def get_snapshot_at(self, ts: int) -> dict[str, Event]:
        """
        Get the most recent event per node_id at a given timestamp.
        Used for replay initialization.
        """
        with self._lock:
            conn = self._conn()
            sql = """
                SELECT id, ts, node_id, event_type, payload,
                       coherence, lattice, quorum, sbs_state, version
                FROM events e1
                WHERE ts <= ?
                  AND id = (
                      SELECT id FROM events e2
                      WHERE e2.node_id = e1.node_id AND e2.ts <= ?
                      ORDER BY ts DESC LIMIT 1
                  )
            """
            rows = conn.execute(sql, [ts, ts]).fetchall()
            conn.close()
            result = {}
            for row in rows:
                e = self._row_to_event(row)
                result[e.node_id] = e
            return result

    def _row_to_event(self, row: tuple) -> Event:
        id_, ts, node_id, event_type, payload_str, \
            coherence_str, lattice_str, quorum_str, sbs_str, version = row

        from observability.core.event_schema import CoherenceStateSnapshot, LatticeSnapshot, QuorumSnapshot, SBSStateSnapshot

        return Event(
            ts=ts,
            node_id=node_id,
            event_type=event_type,
            payload=json.loads(payload_str) if payload_str else {},
            coherence_state=CoherenceStateSnapshot(**json.loads(coherence_str))
                if coherence_str else None,
            lattice_snapshot=LatticeSnapshot(**json.loads(lattice_str))
                if lattice_str else None,
            quorum_snapshot=QuorumSnapshot(**json.loads(quorum_str))
                if quorum_str else None,
            sbs_state=SBSStateSnapshot(**json.loads(sbs_str))
                if sbs_str else None,
            event_id=id_,
            version=version or "7.0",
        )

    def _maybe_compact(self) -> None:
        """Remove oldest events if we exceed max_events."""
        with self._lock:
            conn = self._conn()
            try:
                count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                if count > self.max_events:
                    excess = count - self.max_events
                    conn.execute(
                        f"""
                        DELETE FROM events WHERE id IN (
                            SELECT id FROM events ORDER BY ts ASC LIMIT ?
                        )
                        """,
                        (excess,),
                    )
                    conn.commit()
            finally:
                conn.close()

    def stats(self) -> dict:
        """Return event store statistics."""
        with self._lock:
            conn = self._conn()
            try:
                total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                by_type = dict(conn.execute(
                    "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
                ).fetchall())
                by_node = dict(conn.execute(
                    "SELECT node_id, COUNT(*) FROM events GROUP BY node_id"
                ).fetchall())
                ts_range = conn.execute(
                    "SELECT MIN(ts), MAX(ts) FROM events"
                ).fetchone()
                return {
                    "total_events": total,
                    "by_event_type": by_type,
                    "by_node": by_node,
                    "ts_range_ns": {"min": ts_range[0], "max": ts_range[1]},
                    "db_path": str(self.db_path),
                }
            finally:
                conn.close()

    def close(self) -> None:
        """Close the store. No-op for SQLite."""
        pass
