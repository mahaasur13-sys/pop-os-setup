#!/usr/bin/env bash
#===============================================
# lib/runtime.sh v9.2 — Production Grade Runtime
#===============================================
# Single Source of Truth for all paths + execution engine.
# Full idempotency, dry-run, checkpoint, rollback, fault isolation.
#===============================================

[[ -n "${_RUNTIME_SOURCED:-}" ]] && return 0 || _RUNTIME_SOURCED=1

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

# Resolved paths (must work from any cwd)
pushd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && SCRIPT_ROOT="$(pwd)" && popd >/dev/null 2>&1

readonly SCRIPT_ROOT="${SCRIPT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
readonly LIBDIR="${SCRIPT_ROOT}/lib"
readonly STAGEDIR="${SCRIPT_ROOT}/stages"
readonly ENGINEDIR="${SCRIPT_ROOT}/engine"
readonly STATE_DIR="${SCRIPT_ROOT}/state"
readonly LOG_DIR="${SCRIPT_ROOT}/logs"
readonly CHECKPOINT_DIR="${STATE_DIR}/checkpoints"
readonly SNAPSHOT_DIR="${STATE_DIR}/snapshots"
readonly LOCK_FILE="/var/lock/pop-os-setup.lock"
readonly METADATA_FILE="${STATE_DIR}/.metadata"

# Runtime flags
DRY_RUN="${DRY_RUN:-0}"
SAFE_MODE="${SAFE_MODE:-0}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)_$$}"
RECOVERY_POLICY="${RECOVERY_POLICY:-abort}"  # abort | skip | retry
VERBOSE="${VERBOSE:-0}"

# ═══════════════════════════════════════════════════════════
# BOOTSTRAP — Load dependencies
# ═══════════════════════════════════════════════════════════

bootstrap() {
    local errors=0

    # Ensure state dirs
    for d in "$STATE_DIR" "$CHECKPOINT_DIR" "$SNAPSHOT_DIR" "$LOG_DIR"; do
        mkdir -p "$d" 2>/dev/null || {
            echo "FATAL: Cannot create $d" >&2; ((errors++))
        }
    done

    # Load logging
    if [[ -f "${LIBDIR}/logging.sh" ]]; then
        source "${LIBDIR}/logging.sh" || ((errors++))
    else
        echo "FATAL: logging.sh not found at $LIBDIR" >&2; ((errors++))
    fi

    # Load utils
    if [[ -f "${LIBDIR}/utils.sh" ]]; then
        source "${LIBDIR}/utils.sh" || ((errors++))
    else
        echo "FATAL: utils.sh not found at $LIBDIR" >&2; ((errors++))
    fi

    ((errors == 0)) || {
        echo "Bootstrap failed with $errors error(s)"
        set_safe_mode
        return 1
    }

    log "Bootstrap OK — RUN_ID=$RUN_ID"
    return 0
}

# ═══════════════════════════════════════════════════════════
# SAFE MODE — Restrict operations on failure
# ═══════════════════════════════════════════════════════════

set_safe_mode() {
    export SAFE_MODE=1
    log "SAFE_MODE enabled — only --list/--validate/--dry-run allowed"
}

is_safe_mode() {
    [[ "${SAFE_MODE:-0}" == "1" ]]
}

check_safe_mode() {
    if is_safe_mode; then
        local cmd="${1:-}"
        case "$cmd" in
            --list|--validate|--dry-run|--help|-h) return 0 ;;
            *)
                err "SAFE_MODE: operation '$cmd' blocked"
                err "Allowed: --list | --validate | --dry-run | --help"
                return 1
                ;;
        esac
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════
# LOCK MANAGEMENT — Prevent concurrent runs
# ═══════════════════════════════════════════════════════════

acquire_lock() {
    local max_age="${1:-3600}"  # default 1h stale

    if [[ -f "$LOCK_FILE" ]]; then
        local pid age
        pid=$(cat "$LOCK_FILE" 2>/dev/null)
        age=$(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)
        local now=$(date +%s)

        if [[ -d "/proc/$pid" ]] && [[ $((now - age)) -lt $max_age ]]; then
            err "Lock held by PID $pid (age=$((now - age))s)"
            err "Remove lock: sudo rm $LOCK_FILE"
            return 1
        else
            warn "Stale lock detected (PID=$pid, age=$((now - age))s) — removing"
            rm -f "$LOCK_FILE"
        fi
    fi

    echo "$$" > "$LOCK_FILE"
    log "Lock acquired: PID=$$"
    return 0
}

release_lock() {
    local pid
    pid=$(cat "$LOCK_FILE" 2>/dev/null)
    if [[ "$pid" == "$$" ]]; then
        rm -f "$LOCK_FILE"
        log "Lock released"
    fi
}

# ═══════════════════════════════════════════════════════════
# STATE MACHINE
# ═══════════════════════════════════════════════════════════

# States: PENDING | RUNNING | SUCCESS | FAILED | SKIPPED | RETRYING

get_stage_state() {
    local stage="$1"
    local state_file="${STATE_DIR}/${stage}.state"
    if [[ -f "$state_file" ]]; then
        cat "$state_file"
    else
        echo "PENDING"
    fi
}

mark_stage() {
    local stage="$1"
    local state="$2"
    local state_file="${STATE_DIR}/${stage}.state"
    echo "$state" > "$state_file"
    log "[${stage}] → $state"
}

is_done() {
    local stage="$1"
    local state
    state=$(get_stage_state "$stage")
    [[ "$state" == "SUCCESS" ]] || [[ "$state" == "SKIPPED" ]]
}

is_failed() {
    local stage="$1"
    [[ "$(get_stage_state "$stage")" == "FAILED" ]]
}

is_running() {
    local stage="$1"
    [[ "$(get_stage_state "$stage")" == "RUNNING" ]]
}

# ═══════════════════════════════════════════════════════════
# DRY-RUN
# ═══════════════════════════════════════════════════════════

is_dry_run() {
    [[ "${DRY_RUN:-0}" == "1" ]]
}

check_dry_run() {
    if is_dry_run; then
        log "[DRY-RUN] Would execute: $*"
        return 1
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════
# RUN CMD — Dry-run aware executor
# ═══════════════════════════════════════════════════════════

run_cmd() {
    local stage="$1"
    shift
    local cmd=("$@")
    local start end duration

    if is_dry_run; then
        log "[DRY-RUN] $stage: ${cmd[*]}"
        mark_stage "$stage" "SUCCESS"
        return 0
    fi

    mark_stage "$stage" "RUNNING"
    log "[$stage] EXEC: ${cmd[*]}"
    start=$(date +%s%3N)

    if "${cmd[@]}" 2>&1 | tee -a "${LOG_DIR}/${stage}.log"; then
        end=$(date +%s%3N)
        duration=$((end - start))
        log "[$stage] DONE (${duration}ms)"
        mark_stage "$stage" "SUCCESS"
        _emit_event "$stage" "SUCCESS" "$duration"
        return 0
    else
        end=$(date +%s%3N)
        duration=$((end - start))
        log "[$stage] FAILED (${duration}ms)"
        mark_stage "$stage" "FAILED"
        _emit_event "$stage" "FAILED" "$duration"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════
# OBSERVABILITY — JSONL structured logs
# ═══════════════════════════════════════════════════════════

readonly RUN_LOG="${LOG_DIR}/run_${RUN_ID}.jsonl"

_emit_event() {
    local stage="$1"
    local status="$2"
    local duration_ms="${3:-0}"
    local timestamp
    timestamp=$(date -Iseconds)

    printf '%s\n' "{\"run_id\":\"${RUN_ID}\",\"stage\":\"${stage}\",\"status\":\"${status}\",\"timestamp\":\"${timestamp}\",\"duration_ms\":${duration_ms}}" >> "$RUN_LOG"
}

get_run_log() {
    echo "$RUN_LOG"
}

# ═══════════════════════════════════════════════════════════
# CHECKPOINT SYSTEM
# ═══════════════════════════════════════════════════════════

save_checkpoint() {
    local stage="$1"
    local checkpoint="${CHECKPOINT_DIR}/${stage}.checkpoint"
    local metadata="${CHECKPOINT_DIR}/${stage}.meta"

    if is_dry_run; then
        log "[DRY-RUN] save_checkpoint: $stage"
        return 0
    fi

    local ts
    ts=$(date -Iseconds)
    echo "{\"stage\":\"$stage\",\"timestamp\":\"$ts\",\"run_id\":\"$RUN_ID\"}" > "$checkpoint"
    log "[$stage] checkpoint saved"
}

restore_checkpoint() {
    local stage="$1"
    local checkpoint="${CHECKPOINT_DIR}/${stage}.checkpoint"

    if [[ -f "$checkpoint" ]]; then
        log "[$stage] checkpoint found — restore context"
        cat "$checkpoint"
        return 0
    else
        err "[$stage] no checkpoint found"
        return 1
    fi
}

get_last_success() {
    local stage_num="${1:-1}"

    for ((i=stage_num-1; i>=1; i--)); do
        local name
        name=$(get_stage_name "$i")
        if is_done "$name"; then
            echo "$name"
            return 0
        fi
    done
    return 1
}

# ═══════════════════════════════════════════════════════════
# SNAPSHOT — Pre-stage backup
# ═══════════════════════════════════════════════════════════

snapshot_stage() {
    local stage="$1"
    local snapshot="${SNAPSHOT_DIR}/${stage}.tar.gz"

    if is_dry_run; then
        log "[DRY-RUN] snapshot: $stage"
        return 0
    fi

    if [[ -d /etc/pop-os-setup ]]; then
        tar -czf "$snapshot" -C / etc/pop-os-setup 2>/dev/null || true
        log "[$stage] snapshot: $snapshot"
    fi
}

rollback_stage() {
    local stage="$1"
    local snapshot="${SNAPSHOT_DIR}/${stage}.tar.gz"

    if [[ ! -f "$snapshot" ]]; then
        warn "[$stage] no snapshot to rollback"
        return 1
    fi

    if is_dry_run; then
        log "[DRY-RUN] rollback: $stage from $snapshot"
        return 0
    fi

    tar -xzf "$snapshot" -C / 2>/dev/null || true
    log "[$stage] rollback completed"
}

rollback_pipeline() {
    log "ROLLBACK: reverting all stages"

    for state_file in "${STATE_DIR}"/*.state; do
        [[ -f "$state_file" ]] || continue
        local stage
        stage=$(basename "$state_file" .state)
        rollback_stage "$stage"
    done

    log "ROLLBACK: complete"
}

# ═══════════════════════════════════════════════════════════
# FAULT ISOLATION — Trap + recovery
# ═══════════════════════════════════════════════════════════

CURRENT_STAGE="${CURRENT_STAGE:-}"

stage_error_handler() {
    local line="${1:-0}"
    local stage="${CURRENT_STAGE:-unknown}"

    err "ERROR in $stage at line $line"
    _emit_event "$stage" "CRASHED" "0"

    case "$RECOVERY_POLICY" in
        skip)
            warn "RECOVERY_POLICY=skip — mark $stage SKIPPED and continue"
            mark_stage "$stage" "SKIPPED"
            ;;
        retry)
            warn "RECOVERY_POLICY=retry — will retry $stage"
            mark_stage "$stage" "RETRYING"
            ;;
        abort|*)
            err "RECOVERY_POLICY=abort — stop pipeline"
            set_safe_mode
            ;;
    esac
}

install_trap() {
    trap 'stage_error_handler $LINENO' ERR
}

restore_trap() {
    trap - ERR
}

# ═══════════════════════════════════════════════════════════
# STAGE RESOLUTION
# ═══════════════════════════════════════════════════════════

resolve_stage() {
    local input="$1"

    if [[ -f "${STAGEDIR}/${input}.sh" ]]; then
        echo "${STAGEDIR}/${input}.sh"
        return 0
    fi

    # Try as name
    local found
    found=$(find "${STAGEDIR}" -maxdepth 1 -name "*${input}*.sh" 2>/dev/null | head -1)
    if [[ -n "$found" ]]; then
        echo "$found"
        return 0
    fi

    return 1
}

get_stage_name() {
    local num="$1"
    local file
    file=$(find "${STAGEDIR}" -maxdepth 1 -name "stage${num}_*.sh" 2>/dev/null | head -1)
    basename "$file" .sh
}

get_stage_file() {
    local num="$1"
    find "${STAGEDIR}" -maxdepth 1 -name "stage${num}_*.sh" 2>/dev/null | head -1
}

# ═══════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════

validate_all() {
    local errors=0

    # Check lib files
    for lib in logging.sh utils.sh; do
        if [[ ! -f "${LIBDIR}/${lib}" ]]; then
            err "Missing: ${LIBDIR}/${lib}"
            ((errors++))
        fi
    done

    # Check SCRIPT_ROOT
    if [[ ! -d "$SCRIPT_ROOT" ]]; then
        err "Invalid SCRIPT_ROOT: $SCRIPT_ROOT"
        ((errors++))
    fi

    # Check stages dir
    if [[ ! -d "$STAGEDIR" ]]; then
        err "Missing stages directory: $STAGEDIR"
        ((errors++))
    fi

    # Syntax check all stages
    local stage_errors=0
    for stage_file in "${STAGEDIR}"/*.sh; do
        [[ -f "$stage_file" ]] || continue
        if ! bash -n "$stage_file" 2>/dev/null; then
            err "SYNTAX ERROR: $stage_file"
            ((stage_errors++))
        fi
    done

    if ((stage_errors > 0)); then
        err "$stage_errors stage(s) have syntax errors"
        ((errors += stage_errors))
    fi

    if is_safe_mode; then
        warn "SAFE_MODE: blocking full execution"
        ((errors++))
    fi

    if ((errors == 0)); then
        ok "Validation passed — pipeline ready"
    fi

    return $((errors > 0 ? 1 : 0))
}

validate_dependency() {
    local stage="$1"
    local before_file="${STAGEDIR}/${stage}.before"

    if [[ -f "$before_file" ]]; then
        while read -r dep; do
            [[ -z "$dep" ]] && continue
            if ! is_done "$dep"; then
                err "Dependency not met: $stage requires $dep"
                return 1
            fi
        done < "$before_file"
    fi
    return 0
}

validate_dag() {
    local errors=0
    log "DAG validation (no cycles check)"

    for before_file in "${STAGEDIR}"/*.before; do
        [[ -f "$before_file" ]] || continue
        local stage
        stage=$(basename "$before_file" .before)

        while read -r dep; do
            [[ -z "$dep" ]] && continue
            if [[ ! -f "${STAGEDIR}/${dep}.sh" ]]; then
                err "Broken dependency: $stage → $dep (not found)"
                ((errors++))
            fi
        done < "$before_file"
    done

    return $((errors > 0 ? 1 : 0))
}

# ═══════════════════════════════════════════════════════════
# INIT — Bootstrap on source
# ═══════════════════════════════════════════════════════════

bootstrap

# ═══════════════════════════════════════════════════════════
# RUNTIME VERSION
# ═══════════════════════════════════════════════════════════

readonly RUNTIME_VERSION="v9.2"

get_version() {
    echo "$RUNTIME_VERSION"
}