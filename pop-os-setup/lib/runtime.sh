#!/usr/bin/env bash
#===============================================
# lib/runtime.sh — pop-os-setup v9.0 Runtime Core
# Single Source of Truth for all paths
#===============================================

set -euo pipefail

# ─── ROOT RESOLUTION (symlink-aware, env-overrideable) ─────────────────────────
_resolve_root() {
    local src="${BASH_SOURCE[0]}"
    if [[ -L "$src" ]]; then
        cd "$(dirname "$(readlink -f "$src")")/../.." && pwd -P
    else
        cd "$(dirname "$src")/.." && pwd -P
    fi
}

# Allow override (useful for testing / packaging)
export SCRIPT_ROOT="${SCRIPT_ROOT:-$(_resolve_root)}"
export LIBDIR="${SCRIPT_ROOT}/lib"
export STAGEDIR="${SCRIPT_ROOT}/stages"
export ENGinedir="${SCRIPT_ROOT}/engine"
export PROFILEDIR="${SCRIPT_ROOT}/profiles"

# ─── RUNTIME DIRS ─────────────────────────────────────────────────────────────
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export STATE_DIR="${XDG_CONFIG_HOME}/pop-os-setup/state"
export RUN_DIR="${RUN_DIR:-/tmp/pop-os-setup/$(date +%s)}"

mkdir -p "$STATE_DIR" "$RUN_DIR" 2>/dev/null || true
chmod 755 "$STATE_DIR" 2>/dev/null || true

# ─── BOOTSTRAP ────────────────────────────────────────────────────────────────
bootstrap_libs() {
    local ok=0
    for lib in logging.sh utils.sh; do
        if [[ -f "${LIBDIR}/${lib}" ]]; then
            source "${LIBDIR}/${lib}"
        else
            echo "FATAL: ${LIBDIR}/${lib} missing" >&2
            ok=1
        fi
    done
    return $ok
}

# ─── STAGE GUARD (idempotency) ───────────────────────────────────────────────
stage_guard() {
    [[ "${_STAGE_SOURCED:-}" == "yes" ]] && return 0
    export _STAGE_SOURCED=yes
    bootstrap_libs
}

# ─── STAGE RESOLVER ──────────────────────────────────────────────────────────
resolve_stage() {
    local input="$1"
    # By number: "1" → stage01_* or "7" → stage07_*
    local padded
    padded=$(printf '%02d' "$input" 2>/dev/null || printf '%02d' "0")
    local found
    found=$(ls "${STAGEDIR}"/stage"${padded}"_*.sh 2>/dev/null | head -1)
    # By name fallback
    if [[ -z "$found" ]]; then
        found=$(ls "${STAGEDIR}"/stage*_"${input}"*.sh 2>/dev/null | head -1)
    fi
    if [[ -z "$found" ]]; then
        echo "ERROR: stage not found: $input" >&2
        return 1
    fi
    echo "$found"
}

# ─── PIPELINE VALIDATOR ──────────────────────────────────────────────────────
validate_pipeline() {
    local errors=0
    for f in "${STAGEDIR}"/stage*.sh; do
        [[ -f "$f" ]] || continue
        if ! bash -n "$f" 2>/dev/null; then
            echo "SYNTAX FAIL: $f" >&2
            errors=$((errors + 1))
        fi
    done
    return $errors
}

# ─── RUN CMD (dry-run aware) ─────────────────────────────────────────────────
run_cmd() {
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        echo "[DRY-RUN] $*"
    else
        eval "$@"
    fi
}

# ─── STATE HELPERS ───────────────────────────────────────────────────────────
is_done() { [[ -f "${STATE_DIR}/${1}.done" ]]; }
mark_done() { touch "${STATE_DIR}/${1}.done"; }
mark_failed() { touch "${STATE_DIR}/${1}.failed"; }
clear_state() { rm -f "${STATE_DIR}"/*.done "${STATE_DIR}"/*.failed 2>/dev/null; }

# ─── EXPORTED API ───────────────────────────────────────────────────────────
export -f bootstrap_libs stage_guard resolve_stage validate_pipeline run_cmd
export -f is_done mark_done mark_failed clear_state
