#!/bin/bash
# lib/logging.sh — Deterministic Logging Contract v2 (v11.2)
# same input → same observable trace (always)
# No EUID branching, no filesystem probes, no fallback chains

[[ -n "${_LOGGING_SOURCED:-}" ]] && return 0 || _LOGGING_SOURCED=1

# ── Deterministic log target (v11.2) ──────────────────────────────────────────
# Respects LOG_MODE env var: deterministic | system | user
# Depends ONLY on: LOG_MODE + RUN_ID + RUNTIME_VERSION
_resolve_log_target() {
    local mode="${LOG_MODE:-deterministic}"
    local run_id="${RUN_ID:-default}"
    local ver="${RUNTIME_VERSION:-v11.2}"

    case "$mode" in
        deterministic)
            printf '%s/.logs/%s/%s' "${SCRIPT_DIR:-.}" "$ver" "$run_id"
            ;;
        system)
            printf '/var/log/pop-os-setup/%s/%s' "$ver" "$run_id"
            ;;
        user)
            printf '%s/.local/share/pop-os-setup/logs/%s/%s' "${HOME:-/tmp}" "$ver" "$run_id"
            ;;
        *)
            printf '%s/.logs/%s/%s' "${SCRIPT_DIR:-.}" "$ver" "$run_id"
            ;;
    esac
}

# ── Fail-fast ensure_dir ─────────────────────────────────────────────────────
# NO silent fallback — fails if log dir cannot be resolved
_ensure_log_dir() {
    local target
    target=$(_resolve_log_target)

    # Fail-fast: no filesystem probing or silent fallbacks
    if [[ -z "$target" ]]; then
        echo "[ERROR] Log target resolved to empty path — aborting" >&2
        return 1
    fi

    mkdir -p "$target" 2>/dev/null || {
        echo "[ERROR] Cannot create log directory: $target — aborting" >&2
        return 1
    }
    printf '%s' "$target"
}

# ── Log destination ───────────────────────────────────────────────────────────
# Set once per session; use _resolve_log_target directly for determinism
: "${LOGDIR:=$( _ensure_log_dir || echo '' )}"

# ── Fail if LOGDIR is still empty ─────────────────────────────────────────────
if [[ -z "$LOGDIR" ]]; then
    echo "[FATAL] LOGDIR resolution failed — LOG_MODE=${LOG_MODE:-deterministic} cannot produce valid path" >&2
    echo "[FATAL] Aborting execution to maintain log determinism contract" >&2
    exit 1
fi

# ════════════════════════════════════════════════════════════════════════════════
# LOG FUNCTIONS — all write to deterministic LOGDIR
# ════════════════════════════════════════════════════════════════════════════════

# Internal: write to both stdout and log file
_log_write() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date +'%H:%M:%S' 2>/dev/null || echo "HH:MM:SS")
    local line="[${ts}] [${level}] ${msg}"
    echo "$line"
    echo "$line" >> "${LOGDIR}/setup.log" 2>/dev/null || true
}

log()   { _log_write "LOG" "$*"; }
ok()    { _log_write "OK" "$*"; }
warn()  { _log_write "WARN" "$*"; }
err()   { _log_write "ERR" "$*" >&2; }
info()  { _log_write "INFO" "$*"; }

step() {
    printf '\n'
    printf '=%.0s' {1..70}; printf '\n'
    printf "  STAGE %s | %s\n" "$2" "$1"
    printf '=%.0s' {1..70}; printf '\n\n'
}

log_sep() { printf '=%.0s\n' {1..70}; }

# ── JSONL event logging (v11.2) ──────────────────────────────────────────────
# Structured, ordered, reproducible
log_jsonl_event() {
    local run_id="${RUN_ID:-default}"
    local event="$1"
    local stage="${2:-}"
    local status="${3:-info}"

    local ts fingerprint
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "$(date -u)")
    fingerprint="${PIPELINE_FINGERPRINT:-unknown}"

    local jsonl_file="${LOGDIR}/run_${run_id}.jsonl"
    printf '{"ts":"%s","run_id":"%s","event":"%s","stage":"%s","status":"%s","fingerprint":"%s","version":"%s","log_mode":"%s"}\n' \
        "$ts" "$run_id" "$event" "$stage" "$status" "$fingerprint" \
        "${RUNTIME_VERSION:-v11.2}" "${LOG_MODE:-deterministic}" \
        >> "$jsonl_file" 2>/dev/null || true
}

export -f log_jsonl_event
export LOG_MODE RUN_ID LOGDIR