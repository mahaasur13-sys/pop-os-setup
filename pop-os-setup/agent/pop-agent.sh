#!/bin/bash
#========================================================
# pop-os-setup v6 — Bash Agent Runtime
#========================================================
# Bash-native distributed agent.
# Zero heavy dependencies.
# Pulls tasks from control plane, executes DAG nodes,
# emits events back via WebSocket.
#========================================================
# Usage:
#   AGENT_ID="workstation_01" \
#   CONTROL_PLANE="https://api.example.com" \
#   pop-agent.sh
#========================================================

set -euo pipefail

# ─── CONFIG ────────────────────────────────────────────────────────────────────
AGENT_ID="${AGENT_ID:-$(hostname)_$$}"
CONTROL_PLANE="${CONTROL_PLANE:-http://localhost:8000}"
AGENT_HEARTBEAT_INTERVAL="${AGENT_HEARTBEAT_INTERVAL:-30}"
REGISTER_RETRY_MAX="${REGISTER_RETRY_MAX:-5}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

# ─── STATE ────────────────────────────────────────────────────────────────────
STATE_DIR="/var/lib/pop-os-setup/agent"
mkdir -p "$STATE_DIR" 2>/dev/null || mkdir -p "$HOME/.pop-os-setup/agent"
STATE_DIR="$HOME/.pop-os-setup/agent"
CHECKPOINT_DIR="$STATE_DIR/checkpoints"
mkdir -p "$CHECKPOINT_DIR"
EVENT_LOG="$STATE_DIR/events.jsonl"

# ─── LOGGING ───────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%dT%H:%M:%SZ')] [AGENT:$AGENT_ID] $*" | tee -a "$EVENT_LOG"; }
err() { echo "[$(date '+%Y-%m-%dT%H:%M:%SZ')] [AGENT:$AGENT_ID] [ERR] $*" | tee -a "$EVENT_LOG" >&2; }

# ─── HTTP HELPERS ───────────────────────────────────────────────────────────────
http_get() { curl -sf "${CONTROL_PLANE}$1" -H "X-Agent-ID: $AGENT_ID" "${2:+"-H"}" "${2:-}"; }
http_post() { curl -sf -X POST "${CONTROL_PLANE}$1" -H "Content-Type: application/json" -d "$2" -H "X-Agent-ID: $AGENT_ID"; }

# ─── EVENT EMITTER ─────────────────────────────────────────────────────────────
emit() {
    local type="$1" node="${2:-}" payload="${3:-{}}"
    local event=$(printf '%s\n' \
        "{\"type\":\"$type\"" \
        ",\"run_id\":\"${RUN_ID:-}\"" \
        ",\"node\":\"$node\"" \
        ",\"agent_id\":\"$AGENT_ID\"" \
        ",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
        ",\"payload\":$payload}")
    echo "$event" >> "$EVENT_LOG"
    # Try to send via WebSocket (if ws-url known)
    if [[ -n "${WS_URL:-}" ]]; then
        curl -sf -X POST "$WS_URL" -H "Content-Type: application/json" -d "$event" 2>/dev/null || true
    fi
    log "EVENT: $type | node=$node"
}

# ─── AGENT LIFECYCLE ───────────────────────────────────────────────────────────

agent_register() {
    local attempt=1
    while (( attempt <= REGISTER_RETRY_MAX )); do
        local platform; platform="$(uname -m)"
        local hostname; hostname="$(hostname)"
        local payload; payload="$(printf '%s\n' \
            "{\"agent_id\":\"$AGENT_ID\"" \
            ",\"hostname\":\"$hostname\"" \
            ",\"platform\":\"$platform\"" \
            ",\"tags\":{\"arch\":\"$platform\",\"os\":\"linux\"}}")"

        if http_post "/agents/register" "$payload" | grep -q '"registered"'; then
            log "Registered with control plane (attempt $attempt)"
            return 0
        fi

        err "Registration failed (attempt $attempt/$REGISTER_RETRY_MAX)"
        sleep $((attempt * 2))
        ((attempt++)) || true
    done

    err "Registration failed after $REGISTER_RETRY_MAX attempts — running in standalone mode"
    return 1
}

agent_heartbeat() {
    while true; do
        http_post "/agents/$AGENT_ID/heartbeat" \
            "{\"status\":\"alive\",\"uptime\":$(cat /proc/uptime | awk '{print $1}')}" \
            2>/dev/null || true
        sleep "$AGENT_HEARTBEAT_INTERVAL"
    done &
    HEARTBEAT_PID=$!
}

task_poll() {
    log "Polling for tasks..."
    local tasks; tasks=$(http_get "/tasks/pending?agent_id=$AGENT_ID&limit=1" || echo "[]")
    echo "$tasks"
}

task_claim() {
    local task_id="$1"
    local result; result=$(http_post "/tasks/$task_id/claim" \
        "{\"agent_id\":\"$AGENT_ID\"}" 2>/dev/null || echo "FAILED")
    [[ "$result" != "FAILED" ]]
}

task_execute() {
    local task="$1"
    local node; node=$(echo "$task" | grep -o '"node":"[^"]*"' | cut -d'"' -f4)
    local run_id; run_id=$(echo "$task" | grep -o '"run_id":"[^"]*"' | cut -d'"' -f4)
    local stage_file; stage_file=$(echo "$task" | grep -o '"stage_file":"[^"]*"' | cut -d'"' -f4)
    local manifest_sha; manifest_sha=$(echo "$task" | grep -o '"manifest_sha":"[^"]*"' | cut -d'"' -f4)

    export RUN_ID="$run_id"

    log "Executing node: $node (stage: $stage_file)"

    emit "NODE_STARTED" "$node" '{"status":"running"}'

    # ── Idempotency check ──
    local output_hash_file="$CHECKPOINT_DIR/${node}.output_hash"
    if [[ -f "$output_hash_file" ]]; then
        local prev_hash; prev_hash=$(cat "$output_hash_file")
        if [[ "$prev_hash" == "$manifest_sha" ]]; then
            log "[IDEMPOTENT] Skipping $node (output unchanged)"
            emit "NODE_COMPLETED" "$node" '{"status":"idempotent_skip"}'
            return 0
        fi
    fi

    # ── Execute stage ──
    local start_ts; start_ts=$(date +%s)
    local exit_code=0

    if [[ -f "$stage_file" ]]; then
        bash "$stage_file" >> "$STATE_DIR/logs/${node}.log" 2>&1 || exit_code=$?
    else
        err "Stage file not found: $stage_file"
        emit "NODE_FAILED" "$node" '{"error":"stage_file_not_found"}'
        return 1
    fi

    local duration_ms=$((($(date +%s) - start_ts) * 1000))

    # ── Verify + checkpoint ──
    local output_hash; output_hash=$(sha256sum "$STATE_DIR/logs/${node}.log" 2>/dev/null | awk '{print $1}')
    echo "$output_hash" > "$output_hash_file"
    echo "$manifest_sha" > "$CHECKPOINT_DIR/${node}.manifest_sha"

    if (( exit_code == 0 )); then
        emit "NODE_COMPLETED" "$node" "{\"duration_ms\":$duration_ms,\"exit_code\":0,\"output_hash\":\"$output_hash\"}"
        log "Node $node completed in ${duration_ms}ms"
        return 0
    else
        emit "NODE_FAILED" "$node" "{\"duration_ms\":$duration_ms,\"exit_code\":$exit_code,\"output_hash\":\"$output_hash\"}"
        err "Node $node failed with exit code $exit_code"
        return 1
    fi
}

task_report() {
    local task_id="$1"
    local status="$2"
    local duration="$3"
    http_post "/tasks/$task_id/report" \
        "{\"status\":\"$status\",\"duration_ms\":$duration,\"agent_id\":\"$AGENT_ID\"}" 2>/dev/null || true
}

# ─── MAIN ────────────────────────────────────────────────────────────────────────
main() {
    log "pop-os-setup Agent v6.0.0 starting..."
    log "AGENT_ID=$AGENT_ID | CONTROL_PLANE=$CONTROL_PLANE"
    log "STATE_DIR=$STATE_DIR"

    mkdir -p "$STATE_DIR/logs"

    # Register with control plane
    agent_register || true

    # Start heartbeat in background
    agent_heartbeat
    log "Heartbeat started (PID: $HEARTBEAT_PID)"

    # Main poll loop
    while true; do
        local tasks; tasks=$(task_poll)
        local task_id; task_id=$(echo "$tasks" | grep -o '"task_id":"[^"]*"' | head -1 | cut -d'"' -f4)

        if [[ -z "$task_id" ]]; then
            sleep "$POLL_INTERVAL"
            continue
        fi

        log "Task received: $task_id"

        if task_claim "$task_id"; then
            task_execute "$tasks"
            local result=$?
            task_report "$task_id" "$([[ $result -eq 0 ]] && echo "completed" || echo "failed")" "0"
        else
            log "Task $task_id already claimed by another agent"
        fi

        sleep 1
    done
}

main "$@"
