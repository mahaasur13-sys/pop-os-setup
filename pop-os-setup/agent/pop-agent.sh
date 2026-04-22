#!/bin/bash
#=====================================================
# pop-agent.sh — v7.0 Production Bash Agent
#=====================================================

set -euo pipefail

AGENT_ID="${AGENT_ID:-$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')}"
AGENT_NAME="${AGENT_NAME:-agent-${AGENT_ID:0:8}}"
AGENT_VERSION="7.0.0"

API_BASE="${API_BASE:-http://localhost:8000}"
HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-15}"
LOCK_TTL="${LOCK_TTL:-45}"
EXEC_TIMEOUT="${EXEC_TIMEOUT:-3600}"
MAX_RETRIES="${MAX_RETRIES:-3}"

# ─── STATE ───────────────────────────────────────────────
STATE_FILE="${STATE_FILE:-/tmp/pop-agent-${AGENT_ID:0:8}.state}"
VOLATILE_STATE_DIR="/tmp/pop-agent-${AGENT_ID:0:8}-work"
RESULT_CACHE_DIR="/tmp/pop-agent-results"
mkdir -p "$VOLATILE_STATE_DIR" "$RESULT_CACHE_DIR" 2>/dev/null || true

_current_task=""
_task_start_ts=""
_lock_id=""
_heartbeat_pid=""
_shutdown_requested=0

# ══════════════════════════════════════════════════════════
# INTERNAL API CLIENT
# ══════════════════════════════════════════════════════════

api_get() {
    local path="$1"
    curl -fsSL --connect-timeout 5 --max-time 30 \
         -H "X-Agent-ID: $AGENT_ID" \
         -H "X-Agent-Name: $AGENT_NAME" \
         "${API_BASE}${path}" 2>/dev/null
}

api_post() {
    local path="$1" data="$2"
    curl -fsSL --connect-timeout 5 --max-time 30 \
         -X POST -H "Content-Type: application/json" \
         -H "X-Agent-ID: $AGENT_ID" \
         -H "X-Agent-Name: $AGENT_NAME" \
         -d "$data" \
         "${API_BASE}${path}" 2>/dev/null
}

# ══════════════════════════════════════════════════════════
# DISTRIBUTED LOCK
# ══════════════════════════════════════════════════════════

acquire_lock() {
    local task_id="$1"
    local lock_result
    lock_result=$(api_post "/locks/acquire" \
        "{\"task_id\":\"$task_id\",\"agent_id\":\"$AGENT_ID\",\"agent_name\":\"$AGENT_NAME\",\"ttl\":${LOCK_TTL}}") || return 1

    _lock_id=$(echo "$lock_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('lock_id',''))" 2>/dev/null)
    [[ -n "$_lock_id" ]]
}

renew_lock() {
    [[ -z "$_lock_id" ]] && return 1
    api_post "/locks/renew" \
        "{\"lock_id\":\"$_lock_id\",\"ttl\":${LOCK_TTL}}" \
        >/dev/null 2>&1
}

release_lock() {
    [[ -z "$_lock_id" ]] && return 0
    api_post "/locks/release" \
        "{\"lock_id\":\"$_lock_id\"}" \
        >/dev/null 2>&1 || true
    _lock_id=""
}

# ══════════════════════════════════════════════════════════
# HEARTBEAT
# ══════════════════════════════════════════════════════════

start_heartbeat() {
    _heartbeat_pid=""
    (
        while (( ! _shutdown_requested )) && [[ -n "$_lock_id" ]]; do
            sleep "$HEARTBEAT_INTERVAL"
            renew_lock || break
        done
    ) &
    _heartbeat_pid=$!
}

stop_heartbeat() {
    [[ -n "$_heartbeat_pid" ]] && kill "$_heartbeat_pid" 2>/dev/null || true
    _heartbeat_pid=""
}

# ══════════════════════════════════════════════════════════
# TASK EXECUTION (idempotent, SIGTERM-safe)
# ══════════════════════════════════════════════════════════

execute_task() {
    local task_id="$1"
    local stage_file="$2"
    local params="$3"

    _task_start_ts=$(date +%s)
    local task_hash
    task_hash=$(echo "$params" | sha256sum | cut -d' ' -f1)
    local result_key="${task_id}_${task_hash}"
    local result_file="${RESULT_CACHE_DIR}/${result_key}.json"

    # Idempotency: skip if already succeeded
    if [[ -f "$result_file" ]]; then
        local cached_status
        cached_status=$(python3 -c "import json; print(json.load(open('$result_file')).get('status',''))" 2>/dev/null)
        if [[ "$cached_status" == "completed" ]]; then
            log "Task $task_id already completed (cached)"
            return 0
        fi
    fi

    # SIGTERM trap for graceful shutdown
    local exec_pid=""
    (
        trap "kill -TERM $$ 2>/dev/null; wait $$; exit 143" TERM
        set -e
        source "$stage_file" <<<"$params" 2>&1
    ) &
    exec_pid=$!
    local exec_status=0

    # Wait with periodic lock renewal check
    while kill -0 "$exec_pid" 2>/dev/null; do
        sleep 5
        if (( _shutdown_requested )); then
            kill -TERM "$exec_pid" 2>/dev/null
            wait "$exec_pid" 2>/dev/null || true
            log "Task $task_id terminated by shutdown signal"
            return 130
        fi
    done
    wait "$exec_pid" || exec_status=$?

    local status="completed"
    (( exec_status != 0 )) && status="failed"

    echo "{\"task_id\":\"$task_id\",\"agent_id\":\"$AGENT_ID\",\"status\":\"$status\",\"exit_code\":$exec_status,\"duration\":$(($(date +%s) - _task_start_ts))}" \
        > "$result_file"

    return $exec_status
}

# ══════════════════════════════════════════════════════════
# COMMIT (exactly-once)
# ══════════════════════════════════════════════════════════

commit_result() {
    local task_id="$1" status="$2" exit_code="$3" duration="$4"

    for ((attempt=0; attempt<MAX_RETRIES; attempt++)); do
        local resp
        resp=$(api_post "/tasks/${task_id}/commit" \
            "{\"status\":\"$status\",\"exit_code\":$exit_code,\"duration\":$duration,\"agent_id\":\"$AGENT_ID\"}") || true

        if echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
            log "Task $task_id committed ($status)"
            return 0
        fi
        sleep $((attempt * 2 + 1))
    done

    err "Task $task_id commit failed after $MAX_RETRIES attempts — saved to local result cache"
    return 1
}

# ══════════════════════════════════════════════════════════
# MAIN AGENT LOOP
# ══════════════════════════════════════════════════════════

agent_loop() {
    log "Agent $AGENT_NAME (id=$AGENT_ID) started — API: $API_BASE"
    log "Heartbeat every ${HEARTBEAT_INTERVAL}s, lock TTL ${LOCK_TTL}s"

    while (( ! _shutdown_requested )); do
        # Long-poll for task
        local task_json
        task_json=$(api_get "/tasks/poll?agent_id=${AGENT_ID}&name=${AGENT_NAME}") || {
            sleep 10
            continue
        }

        [[ -z "$task_json" || "$task_json" == "null" ]] && {
            sleep 5
            continue
        }

        local task_id task_name stage_file params
        task_id=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
        task_name=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
        params=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('params',{}))" 2>/dev/null)

        if [[ -z "$task_id" ]]; then
            sleep 5
            continue
        fi

        log "Received task: $task_name (id=$task_id)"
        stage_file=$(echo "$task_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stage_file',''))" 2>/dev/null)

        if [[ -z "$stage_file" || ! -f "$stage_file" ]]; then
            err "Stage file not found: $stage_file"
            commit_result "$task_id" "failed" 1 0
            continue
        fi

        # Acquire lock (idempotent)
        if ! acquire_lock "$task_id"; then
            log "Task $task_id locked by another agent — skipping"
            sleep 5
            continue
        fi

        # Execute with heartbeat
        start_heartbeat
        execute_task "$task_id" "$stage_file" "$params"
        local exec_status=$?
        stop_heartbeat

        # Commit with exactly-once guarantee
        local duration=$(($(date +%s) - _task_start_ts))
        local status="completed"
        (( exec_status != 0 )) && status="failed"
        commit_result "$task_id" "$status" "$exec_status" "$duration"

        # Always release lock
        release_lock
        _current_task=""
    done

    log "Agent $AGENT_NAME shutting down..."
    release_lock
    stop_heartbeat
}

# ══════════════════════════════════════════════════════════
# SIGNAL HANDLING
# ══════════════════════════════════════════════════════════

trap '_shutdown_requested=1' INT TERM

# ══════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════

log() { echo "[$(date '+%H:%M:%S')] [${AGENT_NAME}] $*" >> /var/log/pop-agent.log 2>/dev/null || echo "$*"; }
err() { echo "[$(date '+%H:%M:%S')] [${AGENT_NAME}] ERR: $*" >&2; }

# ══════════════════════════════════════════════════════════
# BOOTSTRAP

log "pop-agent v${AGENT_VERSION} bootstrap"
agent_loop
