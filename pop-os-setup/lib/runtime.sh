#!/usr/bin/env bash
#===============================================
# lib/runtime.sh v9.1 — Production Runtime Core
#===============================================
# Single Source of Truth для всех путей и состояния.
# Используется ВО ВСЕХ stage-файлах.
#
# Usage:
#   source /path/to/lib/runtime.sh
#   bootstrap                    # подключить все библиотеки
#   run_stage "docker"           # запустить stage
#   is_done "docker" || do_it    # проверить состояние
#===============================================

set -euo pipefail

[[ -n "${_RUNTIME_SOURCED:-}" ]] && return 0 || export _RUNTIME_SOURCED=1

# ═══════════════════════════════════════════════════════
# VERSION & METADATA
# ═══════════════════════════════════════════════════════

export RUNTIME_VERSION="9.1.0"
export RUNTIME_SCHEMA="2.0"

# ═══════════════════════════════════════════════════════
# PATH RESOLUTION — symlink-aware, env-overridable
# ═══════════════════════════════════════════════════════

_resolve_root() {
    local src="${BASH_SOURCE[0]:-$(pwd)/runtime.sh}"
    local dir

    if [[ -L "$src" ]]; then
        dir=$(dirname "$(readlink -f "$src")")
        cd "$dir/../.." && pwd -P
    elif [[ -f "$src" ]]; then
        cd "$(dirname "$src")/.." && pwd -P
    elif [[ -n "${SCRIPT_ROOT:-}" ]]; then
        echo "$SCRIPT_ROOT"
    else
        echo "$(pwd)"
    fi
}

# Экспортируем пути (можно переопределить через env)
export SCRIPT_ROOT="${SCRIPT_ROOT:-$(_resolve_root)}"
export LIBDIR="${SCRIPT_ROOT}/lib"
export STAGEDIR="${SCRIPT_ROOT}/stages"
export ENGINEDIR="${SCRIPT_ROOT}/engine"
export SCHEMADIR="${SCRIPT_ROOT}/schema"

# State & runtime dirs
export STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/pop-os-setup/state"
export RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}/pop-os-setup"
export LOG_DIR="${LOG_DIR:-/tmp/pop-os-setup}"

mkdir -p "$STATE_DIR" "$RUN_DIR" "$LOG_DIR" 2>/dev/null || true

# ═══════════════════════════════════════════════════════
# STRUCTURED LOGGING
# ═══════════════════════════════════════════════════════

export LOGFILE="${LOG_DIR}/pop-os-setup-$(date +%Y-%m-%d_%H-%M-%S).log"
log() {
    local level="${1:-INFO}"
    local msg="${2:-}"
    local ts
    ts=$(date +%F_%T)
    echo "[${ts}] [${level}] ${msg}" | tee -a "$LOGFILE" 2>/dev/null || echo "[${ts}] [${level}] ${msg}"
}
ok()   { log "OK" "$*"; }
warn() { log "WARN" "$*" >&2; }
err()  { log "ERROR" "$*" >&2; }
step() { log "STEP" "$1 | Stage $2"; }
info() { log "INFO" "$*"; }

# ═══════════════════════════════════════════════════════
# BOOTSTRAP — подключить все библиотеки
# ═══════════════════════════════════════════════════════

bootstrap() {
    local errors=0

    for lib in logging.sh utils.sh; do
        local lp="${LIBDIR}/${lib}"
        if [[ -f "$lp" ]]; then
            source "$lp"
        else
            err "MISSING: ${lp}"; errors=$((errors + 1))
        fi
    done

    if [[ -f "${ENGINEDIR}/runner.sh" ]]; then
        source "${ENGINEDIR}/runner.sh"
    else
        warn "ENGINE: runner.sh not found at ${ENGINEDIR}/runner.sh"
    fi

    return $errors
}

# ═══════════════════════════════════════════════════════
# STAGE GUARD — защита от повторного sourcing
# ═══════════════════════════════════════════════════════

export _STAGE_SOURCED="${_STAGE_SOURCED:-yes}"

stage_guard() {
    [[ "${_STAGE_SOURCED:-}" == "yes" ]] && return 0 || true
}

# ═══════════════════════════════════════════════════════
# STATE MANAGEMENT — idempotency core
# ═══════════════════════════════════════════════════════

# PENDING / RUNNING / SUCCESS / FAILED / SKIPPED

STATE_PENDING="PENDING"
STATE_RUNNING="RUNNING"
STATE_SUCCESS="SUCCESS"
STATE_FAILED="FAILED"
STATE_SKIPPED="SKIPPED"

_get_state_file() {
    echo "${STATE_DIR}/.$1.state"
}

get_state() {
    local name="$1"
    local sf="$(_get_state_file "$name")"
    [[ -f "$sf" ]] && cat "$sf" || echo "$STATE_PENDING"
}

is_done() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    [[ "$(get_state "$name")" == "$STATE_SUCCESS" ]] && return 0 || return 1
}

is_failed() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    [[ "$(get_state "$name")" == "$STATE_FAILED" ]] && return 0 || return 1
}

is_running() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    [[ "$(get_state "$name")" == "$STATE_RUNNING" ]] && return 0 || return 1
}

mark_running() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    echo "$STATE_RUNNING" > "$(_get_state_file "$name")"
}

mark_success() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    echo "$STATE_SUCCESS" > "$(_get_state_file "$name")"
    # Удаляем failed-маркер если был
    rm -f "${STATE_DIR}/.$name.failed" 2>/dev/null || true
}

mark_failed() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    echo "$STATE_FAILED" > "$(_get_state_file "$name")"
    touch "${STATE_DIR}/.$name.failed" 2>/dev/null || true
}

mark_skipped() {
    local name="${1:-}"
    [[ -z "$name" ]] && return 1
    echo "$STATE_SKIPPED" > "$(_get_state_file "$name")"
}

reset_state() {
    local name="${1:-}"
    rm -f "$(_get_state_file "$name")" "${STATE_DIR}/.$name.failed" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════
# DRY-RUN AWARENESS
# ═══════════════════════════════════════════════════════

is_dry_run() {
    [[ "${DRY_RUN:-0}" == "1" ]]
}

check_dry_run() {
    if is_dry_run; then
        ok "[DRY-RUN] $*"
        return 1  # возвращаем 1 чтобы вызывающий знал что это dry-run
    fi
    return 0  # продолжаем
}

# ═══════════════════════════════════════════════════════
# STAGE RESOLUTION — number/name → file path
# ═══════════════════════════════════════════════════════

resolve_stage() {
    local input="${1:-}"
    local num=""
    local name=""
    local file=""

    # "7" или "07" → padding
    if [[ "$input" =~ ^[0-9]+$ ]]; then
        num=$(printf '%02d' "$input" 2>/dev/null)
        file=$(ls "${STAGEDIR}"/stage"${num}"_*.sh 2>/dev/null | head -1)
    else
        # Имя → поиск
        file=$(ls "${STAGEDIR}"/stage*_"${input}".sh 2>/dev/null | head -1)
    fi

    if [[ -z "$file" || ! -f "$file" ]]; then
        err "Stage not found: ${input}"
        return 1
    fi

    echo "$file"
    return 0
}

# ═══════════════════════════════════════════════════════
# PIPELINE VALIDATION
# ═══════════════════════════════════════════════════════

validate_all() {
    local errors=0
    local count=0
    for f in "${STAGEDIR}"/stage*.sh; do
        [[ -f "$f" ]] || continue
        count=$((count + 1))
        if ! bash -n "$f" 2>/dev/null; then
            err "SYNTAX FAIL: $f"
            errors=$((errors + 1))
        fi
    done
    if [[ $errors -eq 0 ]]; then
        ok "All ${count} stages syntax-valid"
        return 0
    else
        err "${errors}/${count} stages have errors"
        return 1
    fi
}

validate_runtime() {
    local errors=0
    for lib in logging.sh utils.sh; do
        [[ -f "${LIBDIR}/${lib}" ]] || { err "MISSING: ${lib}"; errors=$((errors + 1)); }
    done
    [[ -f "${ENGINEDIR}/runner.sh" ]] || { err "MISSING: runner.sh"; errors=$((errors + 1)); }
    return $errors
}

# ═══════════════════════════════════════════════════════
# RUN COMMAND — dry-run aware executor
# ═══════════════════════════════════════════════════════

run_cmd() {
    local label="${1:-}"
    local cmd="${2:-}"
    shift 2 || true

    if is_dry_run; then
        ok "[DRY-RUN] Would execute: ${cmd}"
        return 0
    fi

    info "Executing: ${label}"
    if eval "$cmd" "$@"; then
        ok "Done: ${label}"
        return 0
    else
        err "Failed: ${label} (exit $?)"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════
# EXPORT для дочерних процессов
# ═══════════════════════════════════════════════════════

export -f bootstrap stage_guard is_done is_failed is_running
export -f mark_running mark_success mark_failed mark_skipped reset_state
export -f is_dry_run check_dry_run
export -f resolve_stage validate_all validate_runtime run_cmd