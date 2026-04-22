-- =====================================================
-- pop-os-setup v7.0 — PostgreSQL Event Store Schema
-- Migration: 001_events.sql
-- =====================================================

BEGIN;

-- ─── RUNS ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT        PRIMARY KEY,  -- run_id (uuid)
    dag_id      TEXT        NOT NULL,
    profile     TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING|RUNNING|COMPLETED|FAILED|ABORTED
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    metadata    JSONB       DEFAULT '{}',
    CONSTRAINT runs_status_check CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','ABORTED'))
);

-- ─── AGENTS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT        PRIMARY KEY,
    name        TEXT        UNIQUE NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'IDLE',  -- IDLE|BUSY|DEAD
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    capabilities JSONB      DEFAULT '[]',
    metadata    JSONB       DEFAULT '{}',
    CONSTRAINT agents_status_check CHECK (status IN ('IDLE','BUSY','DEAD'))
);

-- ─── TASKS ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT        PRIMARY KEY,
    run_id          TEXT        NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    node            TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING|ASSIGNED|IN_PROGRESS|COMPLETED|FAILED|DLQ
    assigned_agent  TEXT        REFERENCES agents(id),
    idempotency_key TEXT        UNIQUE NOT NULL,  -- sha256(run_id + node + manifest_sha)
    lock_token      TEXT,                          -- uuid — prevents brain split
    lock_expires_at TIMESTAMPTZ,                   -- TTL for distributed lock
    attempts        INTEGER     NOT NULL DEFAULT 0,
    max_attempts    INTEGER     NOT NULL DEFAULT 3,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    payload         JSONB       DEFAULT '{}',
    result          JSONB       DEFAULT '{}',
    CONSTRAINT tasks_status_check CHECK (status IN ('PENDING','ASSIGNED','IN_PROGRESS','COMPLETED','FAILED','DLQ'))
);

CREATE INDEX idx_tasks_run_id    ON tasks(run_id);
CREATE INDEX idx_tasks_status    ON tasks(status);
CREATE INDEX idx_tasks_idempotency ON tasks(idempotency_key);
CREATE INDEX idx_tasks_lock_expires ON tasks(lock_expires_at) WHERE lock_expires_at IS NOT NULL;

-- ─── EVENTS ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL   PRIMARY KEY,
    run_id      TEXT        NOT NULL,
    task_id     TEXT,
    agent_id    TEXT,
    node        TEXT,
    type        TEXT        NOT NULL,  -- TASK_ASSIGNED|TASK_STARTED|TASK_COMPLETED|TASK_FAILED|AGENT_HEARTBEAT|...
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload     JSONB       DEFAULT '{}',
    checksum    TEXT        NOT NULL,  -- sha256 of payload for integrity
    -- Ordering: (run_id, ts, id) gives total order within a run
    UNIQUE(run_id, ts, id)
);

CREATE INDEX idx_events_run_id ON events(run_id);
CREATE INDEX idx_events_task_id ON events(task_id);
CREATE INDEX idx_events_ts     ON events(ts);
CREATE INDEX idx_events_type   ON events(type);

-- ─── LOCKS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS locks (
    resource    TEXT        PRIMARY KEY,
    owner       TEXT        NOT NULL,  -- agent_id
    token       TEXT        NOT NULL,  -- uuid — prevents accidental release
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_locks_expires ON locks(expires_at);

-- ─── IDEMPOTENCY KEYS ─────────────────────────────────
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key         TEXT        PRIMARY KEY,
    task_id     TEXT        NOT NULL REFERENCES tasks(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at     TIMESTAMPTZ
);

-- ─── FUNCTIONS ────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION task_lock_acquire(p_task_id TEXT, p_agent_id TEXT, p_lock_token TEXT, p_ttl INTERVAL)
RETURNS BOOLEAN AS $$
DECLARE
    acquired BOOLEAN;
BEGIN
    -- Atomic: set lock only if not held or expired
    WITH updated AS (
        UPDATE tasks
        SET assigned_agent = p_agent_id,
            lock_token = p_lock_token,
            lock_expires_at = NOW() + p_ttl,
            status = 'ASSIGNED',
            updated_at = NOW()
        WHERE id = p_task_id
          AND (lock_expires_at IS NULL OR lock_expires_at < NOW())
          AND status IN ('PENDING', 'FAILED')
        RETURNING id
    )
    SELECT EXISTS (SELECT 1 FROM updated) INTO acquired;

    RETURN COALESCE(acquired, FALSE);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION task_lock_release(p_task_id TEXT, p_lock_token TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    released BOOLEAN;
BEGIN
    UPDATE tasks
    SET lock_token = NULL,
        lock_expires_at = NULL,
        status = 'COMPLETED',
        updated_at = NOW(),
        completed_at = NOW()
    WHERE id = p_task_id
      AND lock_token = p_lock_token
      AND status = 'ASSIGNED';
    GET DIAGNOSTICS released = ROW_COUNT;
    RETURN released > 0;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION task_lock_heartbeat(p_task_id TEXT, p_lock_token TEXT, p_ttl INTERVAL)
RETURNS BOOLEAN AS $$
DECLARE
    renewed BOOLEAN;
BEGIN
    UPDATE tasks
    SET lock_expires_at = NOW() + p_ttl,
        updated_at = NOW()
    WHERE id = p_task_id
      AND lock_token = p_lock_token
      AND status IN ('ASSIGNED', 'IN_PROGRESS');
    GET DIAGNOSTICS renewed = ROW_COUNT;
    RETURN renewed > 0;
END;
$$ LANGUAGE plpgsql;

-- Requeue expired tasks (called by cron every 30s)
CREATE OR REPLACE FUNCTION requeue_expired_tasks()
RETURNS INTEGER AS $$
DECLARE
    count INTEGER;
BEGIN
    WITH requeued AS (
        UPDATE tasks
        SET status = 'PENDING',
            assigned_agent = NULL,
            lock_token = NULL,
            lock_expires_at = NULL,
            updated_at = NOW(),
            attempts = attempts + 1,
            error = 'Lock expired — requeued'
        WHERE lock_expires_at < NOW()
          AND status IN ('ASSIGNED', 'IN_PROGRESS')
          AND attempts < max_attempts
        RETURNING id
    )
    SELECT COUNT(*) INTO count FROM requeued;

    -- Move over-max-attempt to DLQ
    UPDATE tasks
    SET status = 'DLQ',
        error = 'Max attempts exceeded'
    WHERE lock_expires_at < NOW()
      AND status IN ('ASSIGNED', 'IN_PROGRESS')
      AND attempts >= max_attempts;

    RETURN count;
END;
$$ LANGUAGE plpgsql;

-- Atomic event append (prevents partial writes)
CREATE OR REPLACE FUNCTION append_event(
    p_run_id  TEXT,
    p_task_id TEXT,
    p_agent_id TEXT,
    p_node    TEXT,
    p_type    TEXT,
    p_payload JSONB
) RETURNS BIGINT AS $$
DECLARE
    evt_id BIGINT;
    chk    TEXT;
BEGIN
    chk := encode(sha256(p_payload::text::bytea), 'hex');

    INSERT INTO events(run_id, task_id, agent_id, node, type, payload, checksum)
    VALUES (p_run_id, p_task_id, p_agent_id, p_node, p_type, p_payload, chk)
    RETURNING id INTO evt_id;

    RETURN evt_id;
END;
$$ LANGUAGE plpgsql;

-- Rebuild task state from events (for replay)
CREATE OR REPLACE FUNCTION rebuild_task_state(p_task_id TEXT)
RETURNS JSONB AS $$
DECLARE
    state JSONB := '{"status":"PENDING","events":[]}';
BEGIN
    FOR rec IN
        SELECT type, payload, ts, id
        FROM events
        WHERE task_id = p_task_id
        ORDER BY ts ASC, id ASC
    LOOP
        state := jsonb_set(state, '{events}', state->'events' || jsonb_build_object(
            'type', rec.type,
            'ts', rec.ts,
            'id', rec.id
        ));

        CASE rec.type
            WHEN 'TASK_STARTED'    THEN state := jsonb_set(state, '{status}', '"IN_PROGRESS"');
            WHEN 'TASK_COMPLETED'  THEN state := jsonb_set(state, '{status}', '"COMPLETED"');
            WHEN 'TASK_FAILED'     THEN state := jsonb_set(state, '{status}', '"FAILED"');
            WHEN 'TASK_DLQ'        THEN state := jsonb_set(state, '{status}', '"DLQ"');
        END CASE;
    END LOOP;

    RETURN state;
END;
$$ LANGUAGE plpgsql;

-- ─── TRIGGERS ─────────────────────────────────────────
CREATE TRIGGER trg_runs_updated_at
    BEFORE UPDATE ON runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;