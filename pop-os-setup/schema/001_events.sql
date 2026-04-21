-- pop-os-setup v7.0 — Postgres Event Store Schema
-- Event-sourced system of record

BEGIN;

-- ── Event Log (append-only) ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id          UUID        DEFAULT gen_random_uuid(),
    run_id      TEXT        NOT NULL,
    node_id     TEXT        NOT NULL,
    event_type  TEXT        NOT NULL,  -- node_started|node_completed|node_failed|heartbeat|skip
    payload     JSONB       DEFAULT '{}',
    ts          TIMESTAMPTZ DEFAULT NOW(),
    seq         BIGSERIAL
);

CREATE UNIQUE INDEX IF NOT EXISTS events_seq_idx ON events (seq);

CREATE INDEX IF NOT EXISTS events_run_id_idx ON events (run_id);
CREATE INDEX IF NOT EXISTS events_run_ts_idx  ON events (run_id, ts);
CREATE INDEX IF NOT EXISTS events_node_idx    ON events (run_id, node_id);

-- ── Workflow Runs ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY DEFAULT '',
    workflow_id TEXT NOT NULL,
    profile     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',  -- pending|running|completed|failed|aborted
    started_at  TIMESTAMPTZ DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    error_msg   TEXT,
    checkpoint  JSONB DEFAULT '[]',  -- completed node IDs
    stats       JSONB DEFAULT '{"total":0,"completed":0,"failed":0,"skipped":0}'
);

-- ── Agents ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    hostname    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'idle',  -- idle|busy|offline
    load        REAL DEFAULT 0,
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    labels      JSONB DEFAULT '[]',
    capabilities JSONB DEFAULT '[]'
);

-- ── Tasks Queue ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id          UUID DEFAULT gen_random_uuid(),
    run_id      TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|dispatched|running|completed|failed|dlq
    attempts    INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    visibility_timeout TIMESTAMPTZ,
    heartbeat   TIMESTAMPTZ DEFAULT NOW(),
    payload     JSONB DEFAULT '{}',
    enqueued_at TIMESTAMPTZ DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    ended_at    TIMESTAMPTZ,
    error       TEXT,
    agent_id    TEXT REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS tasks_status_idx    ON tasks (status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS tasks_visibility_idx ON tasks (visibility_timeout) WHERE status = 'dispatched';
CREATE INDEX IF NOT EXISTS tasks_run_idx ON tasks (run_id);

-- ── Node Definitions (workflow manifest) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS node_defs (
    id          TEXT PRIMARY KEY DEFAULT '',  -- run_id:node_id
    run_id      TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    stage_num   INTEGER,
    deps        TEXT[] DEFAULT '{}',
    timeout     INTEGER DEFAULT 3600,
    retry_policy JSONB DEFAULT '{"max_attempts":3,"backoff":"exponential"}',
    sandboxed   BOOLEAN DEFAULT FALSE,
    version     TEXT DEFAULT '1.0.0'
);

-- ── Constraints ──────────────────────────────────────────────────────────────
ALTER TABLE events  ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks   ENABLE ROW LEVEL SECURITY;

COMMIT;