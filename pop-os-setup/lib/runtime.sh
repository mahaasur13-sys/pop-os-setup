#!/bin/bash
#==================================================
# lib/runtime.sh — Unified Runtime Core v8.0
#==================================================
# Single source of truth for all path resolution.
# All paths are computed, never hardcoded.
# Compatible with: standalone, staged, agent mode.
#==================================================

[[ -n "${_RUNTIME_SOURCED:-}" ]] && return 0
_RUNTIME_SOURCED=1

# ─── SAFETY ────────────────────────────────────────────
set -euo pipefail

# ─── ENV OVERRIDES ─────────────────────────────────────
# SCRIPT_ROOT  — root of the repo (default: auto-detect)
# LIBDIR       — lib/ directory (default: $SCRIPT_ROOT/lib)
# STAGEDIR    — stages/ directory (default: $SCRIPT_ROOT/stages)
# ENGDIR      — engine/ directory (default: $SCRIPT_ROOT/engine)
# PROFILEDIR  — profiles/ directory (default: $SCRIPT_ROOT/profiles)
# SCHEMADIR   — schema/ directory (default: $SCRIPT_ROOT/schema)
# RUNDIR      — runtime data dir (default: /tmp/pop-os-run)
# STATE_DIR   — execution state (default: $RUNDIR/state)
# LOG_DIR     — log output (default: /var/log)
# AGENT_MODE  — if set, agent mode (no TTY prompts)

# ─── PATH RESOLUTION ────────────────────────────────────
_resolve_script_root() {
    # Priority: env override → symlink-resolved → PWD fallback
    if [[ -n "${SCRIPT_ROOT:-}" ]]; then
        [[ -d "$SCRIPT_ROOT" ]] && { cd "$SCRIPT_ROOT" && pwd; return 0; }
    fi

    local src="${BASH_SOURCE[0]:-}"
    local dir

    if [[ -L "$src" ]]; then
        # Symlink-aware: resolve through symlink chain
        dir=$(cd "$(dirname "$(readlink -f "$src")")" && pwd)
    elif [[ -n "$src" ]]; then
        dir=$(cd "$(dirname "$src")" && pwd)
    else
        dir=$(pwd)
    fi

    # Normalize: stages/lib/foo.sh → repo root
    case "$dir" in
        */stages)    cd "$(dirname "$dir")" && pwd ;;
        */lib)       cd "$(dirname "$dir")" && pwd ;;
        */engine)    cd "$(dirname "$dir")" && pwd ;;
        */agent)     cd "$(dirname "$dir")" && pwd ;;
        */control-plane) cd "$(dirname "$dir")" && pwd ;;
        */schema)    cd "$(dirname "$dir")" && pwd ;;
        */profiles)  cd "$(dirname "$dir")" && pwd ;;
        *)           echo "$dir"
    esac
}

# Initialize once
SCRIPT_ROOT="${SCRIPT_ROOT:-}"
SCRIPT_ROOT="$(_resolve_script_root)" || SCRIPT_ROOT="$(pwd)"
readonly SCRIPT_ROOT

# ─── DIRECTORY VARIABLES ────────────────────────────────
LIBDIR="${LIBDIR:-${SCRIPT_ROOT}/lib}"
STAGEDIR="${STAGEDIR:-${SCRIPT_ROOT}/stages}"
ENGDIR="${ENGDIR:-${SCRIPT_ROOT}/engine}"
PROFILEDIR="${PROFILEDIR:-${SCRIPT_ROOT}/profiles}"
SCHEMADIR="${SCHEMADIR:-${SCRIPT_ROOT}/schema}"
AGENTDIR="${AGENTDIR:-${SCRIPT_ROOT}/agent}"
CONTROLDIR="${CONTROLDIR:-${SCRIPT_ROOT}/control-plane}"

# Runtime dirs (ephemeral)
RUNDIR="${RUNDIR:-/tmp/pop-os-run/${RUN_ID:-$(date +%Y%m%d_%H%M%S)}}"
STATE_DIR="${STATE_DIR:-${RUNDIR}/state}"
CACHE_DIR="${CACHE_DIR:-${RUNDIR}/cache}"
LOG_DIR="${LOG_DIR:-/var/log}"

# Ensure ephemeral dirs exist
mkdir -p "$RUNDIR" "$STATE_DIR" "$CACHE_DIR" 2>/dev/null || true

# ─── EXPORT ─────────────────────────────────────────────
export SCRIPT_ROOT LIBDIR STAGEDIR ENGDIR PROFILEDIR SCHEMADIR AGENTDIR CONTROLDIR
export RUNDIR STATE_DIR CACHE_DIR LOG_DIR

# ─── STAGE DETECTION ───────────────────────────────────
# Resolves a stage number or glob to actual file.
# Usage: resolve_stage "7"        → /path/to/stage7_docker.sh
#        resolve_stage "docker"   → /path/to/stage7_docker.sh
#        resolve_stage "stage7*"   → first match
resolve_stage() {
    local query="$1"

    # Direct file check
    if [[ -f "$query" ]]; then
        echo "$(readlink -f "$query")"
        return 0
    fi

    # By number: "7" or "07"
    local num="${query#stage}"
    num="${num%%_*}"
    num="${num#0}" # strip leading zero

    local glob1="${STAGEDIR}/stage${num}_*.sh"
    local glob2="${STAGEDIR}/stage$(printf '%02d' "$num")_*.sh"

    for glob in "$glob1" "$glob2"; do
        local match
        match=$(ls $glob 2>/dev/null | sort -V | head -1)
        if [[ -n "$match" ]]; then
            echo "$match"
            return 0
        fi
    done

    # By name substring
    local name_match
    name_match=$(grep -l "_${query}\.sh$" "${STAGEDIR}"/*.sh 2>/dev/null | head -1)
    if [[ -n "$name_match" ]]; then
        echo "$name_match"
        return 0
    fi

    return 1
}

# ─── BOOTSTRAP LIBS ─────────────────────────────────────
bootstrap_libs() {
    local needed="${1:-all}"
    local errors=0

    for lib in \
        "$LIBDIR/_path.sh" \
        "$LIBDIR/logging.sh" \
        "$LIBDIR/utils.sh" \
        "$LIBDIR/profiles.sh" \
        "$LIBDIR/installer.sh"; do

        if [[ ! -f "$lib" ]]; then
            echo "[runtime] FATAL: missing $lib" >&2
            ((errors++)) || true
            continue
        fi

        source "$lib" 2>/dev/null || {
            echo "[runtime] FATAL: failed to source $lib" >&2
            ((errors++)) || true
        }
    done

    # Engine libs (optional, non-fatal)
    for elib in "$ENGDIR/_dag.sh" "$ENGDIR/_state.sh" "$ENGDIR/event-store.sh"; do
        [[ -f "$elib" ]] && source "$elib" 2>/dev/null || true
    done

    return $errors
}

# ─── STAGE GUARD ────────────────────────────────────────
# Call at top of every stage script:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/runtime.sh"
#   stage_guard || return 0
stage_guard() {
    [[ "${_STAGE_SOURCED:-}" == "yes" ]] && {
        log "Stage already sourced — skipping"
        return 0
    }
    export _STAGE_SOURCED="yes"
}

# ─── HELPERS ────────────────────────────────────────────
is_root() { [[ $EUID -eq 0 ]]; }

require_command() {
    command -v "$1" &>/dev/null || {
        echo "[runtime] FATAL: required command not found: $1" >&2
        return 1
    }
}

require_file() {
    [[ -f "$1" ]] || {
        echo "[runtime] FATAL: required file not found: $1" >&2
        return 1
    }
}

log_stage_start() {
    local stage_num="$1" stage_name="$2"
    log "=== STAGE ${stage_num} | ${stage_name} | ${USER:-unknown} @ $(hostname) ==="
}

log_stage_end() {
    local stage_num="$1" status="$2" duration="${3:-0}"
    log "=== STAGE ${stage_num} | ${status} | ${duration}s ==="
}

# ─── DRY RUN ────────────────────────────────────────────
is_dry_run() { [[ "${DRY_RUN:-0}" == "1" ]]; }

# ─── VERIFY ─────────────────────────────────────────────
runtime_verify() {
    local ok=0
    [[ -d "$LIBDIR" ]] || { echo "FATAL: LIBDIR not a dir: $LIBDIR" >&2; ok=1; }
    [[ -d "$STAGEDIR" ]] || { echo "FATAL: STAGEDIR not a dir: $STAGEDIR" >&2; ok=1; }
    [[ -d "$SCRIPT_ROOT" ]] || { echo "FATAL: SCRIPT_ROOT not a dir: $SCRIPT_ROOT" >&2; ok=1; }
    [[ -f "$LIBDIR/logging.sh" ]] || { echo "FATAL: logging.sh missing" >&2; ok=1; }
    return $ok
}
