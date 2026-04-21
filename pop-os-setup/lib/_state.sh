#!/bin/bash
#=======================================================================
# lib/_state.sh — State Layer v4.1
#=======================================================================
# Persistent execution state with atomic writes and rollback checkpoints
#=======================================================================

[[ -n "${_STATE_SOURCED:-}" ]] && return 0 || _STATE_SOURCED=1

# ─── CONFIG ────────────────────────────────────────────────────────────────
STATE_DIR="${STATE_DIR:-/var/lib/pop-os-setup}"
STATE_FILE="${STATE_FILE:-${STATE_DIR}/state.json}"
STATE_BACKUP="${STATE_BACKUP:-${STATE_DIR}/state.backup.json}"

# ─── BOOTSTRAP: ensure state directory ───────────────────────────────────
_state_bootstrap() {
    if [[ ! -d "$STATE_DIR" ]]; then
        mkdir -p "$STATE_DIR" 2>/dev/null || {
            # Fallback to /tmp if /var/lib not writable
            STATE_DIR="/tmp/pop-os-setup-state"
            mkdir -p "$STATE_DIR"
            STATE_FILE="${STATE_DIR}/state.json"
            STATE_BACKUP="${STATE_DIR}/state.backup.json"
        }
    fi
    chmod 700 "$STATE_DIR"
}

# ─── API: load_state ─────────────────────────────────────────────────────────
# load_state
# Returns: 0=loaded, 1=new state (first run)
load_state() {
    _state_bootstrap

    if [[ -f "$STATE_FILE" ]]; then
        # Validate JSON before loading
        if ! jq . "$STATE_FILE" >/dev/null 2>&1; then
            _log "WARN" "Corrupted state.json — backing up and starting fresh"
            cp "$STATE_FILE" "${STATE_FILE}.corrupted.$(date +%s)"
        fi
        _CURRENT_STATE=$(cat "$STATE_FILE")
        _log "INFO" "State loaded: $(echo "$_CURRENT_STATE" | jq '.stages | length') stages tracked"
        return 0
    else
        _CURRENT_STATE='{"version":"4.1","created":"'"$(date -Iseconds)"'","updated":"'"$(date -Iseconds)"'","profile":"","stages":{}}'
        _state_save
        _log "INFO" "New state created"
        return 1
    fi
}

# ─── API: get_state ─────────────────────────────────────────────────────────
# get_state [stage_id]
# If stage_id given: returns status string (INIT|CHECK|EXEC|etc.)
# If no stage_id: returns full state JSON
get_state() {
    local stage="${1:-}"
    if [[ -z "$stage" ]]; then
        echo "$_CURRENT_STATE"
    else
        echo "$_CURRENT_STATE" | jq -r ".stages[\"$stage\"].status // \"\""
    fi
}

# ─── API: set_state ──────────────────────────────────────────────────────────
# set_state <stage_id> <status> [message]
# Returns: 0 always
set_state() {
    local stage="$1" status="$2" msg="${3:-}"
    _state_set "$stage" "$status" "$msg"
    _state_save
}

# ─── INTERNAL: merge update (in-memory) ────────────────────────────────────
_state_set() {
    local stage="$1" status="$2" msg="$3"
    local timestamp now
    now=$(date -Iseconds)

    _CURRENT_STATE=$(echo "$_CURRENT_STATE" | jq \
        --arg s="$stage" \
        --arg st="$status" \
        --arg msg "${msg:- }" \
        --arg ts "$now" \
        'if .stages[$s] == null then .stages[$s] = {} end |
         .stages[$s].status = $st |
         .stages[$s].message = $msg |
         .stages[$s].updated = $ts |
         .updated = $ts')
}

# ─── INTERNAL: atomic write ─────────────────────────────────────────────────
_state_save() {
    local tmp="${STATE_FILE}.tmp.$$"

    # Write to temp file first
    echo "$_CURRENT_STATE" > "$tmp"

    # Atomic rename (kernel guaranteed)
    if mv "$tmp" "$STATE_FILE"; then
        chmod 600 "$STATE_FILE"
        return 0
    else
        _log "ERROR" "Failed to write state — atomic rename failed"
        rm -f "$tmp"
        return 1
    fi
}

# ─── API: checkpoint ─────────────────────────────────────────────────────────
# checkpoint [stage_id]
# Creates timestamped backup before critical operations
checkpoint() {
    local stage="${1:-}"
    local ts
    ts=$(date +%Y%m%d%H%M%S)

    if [[ -f "$STATE_FILE" ]]; then
        cp "$STATE_FILE" "${STATE_DIR}/checkpoint.${ts}.json"
        _log "INFO" "Checkpoint created: checkpoint.${ts}.json"
    fi

    if [[ -n "$stage" ]]; then
        set_state "$stage" "CHECKPOINT" "Before $stage"
    fi
}

# ─── API: restore_checkpoint ──────────────────────────────────────────────────
# restore_checkpoint [checkpoint_name]
restore_checkpoint() {
    local name="${1:-latest}"
    local target

    if [[ "$name" == "latest" ]]; then
        target=$(ls -t "${STATE_DIR}"/checkpoint.*.json 2>/dev/null | head -1)
    else
        target="${STATE_DIR}/checkpoint.${name}.json"
    fi

    if [[ -z "$target" ]] || [[ ! -f "$target" ]]; then
        _log "ERROR" "Checkpoint not found: $name"
        return 1
    fi

    cp "$target" "$STATE_FILE"
    _CURRENT_STATE=$(cat "$STATE_FILE")
    _log "INFO" "State restored from: $(basename "$target")"
}

# ─── API: get_failed_stages ─────────────────────────────────────────────────
# Returns: list of stages with FAILED status
get_failed_stages() {
    echo "$_CURRENT_STATE" | jq -r '.stages | to_entries[] |
        select(.value.status == "FAILED") | .key' 2>/dev/null
}

# ─── API: get_unexecuted_stages ──────────────────────────────────────────────
# Returns: stages with INIT|CHECK|EXEC|VERIF|empty status
get_unexecuted_stages() {
    echo "$_CURRENT_STATE" | jq -r '.stages | to_entries[] |
        select(.value.status == null or
               .value.status == "INIT" or
               .value.status == "CHECK" or
               .value.status == "EXEC" or
               .value.status == "VERIFY") |
        .key' 2>/dev/null
}

# ─── API: mark_profile ───────────────────────────────────────────────────────
mark_profile() {
    local profile="$1"
    _CURRENT_STATE=$(echo "$_CURRENT_STATE" | jq \
        --arg p "$profile" \
        '. + {profile: $p}')
    _state_save
}

# ─── INTERNAL ───────────────────────────────────────────────────────────────
_log() { echo "[$1] $(date '+%H:%M:%S') $*" >&2; }
declare -g _CURRENT_STATE="{}"
