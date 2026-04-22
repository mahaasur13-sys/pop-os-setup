#!/usr/bin/env bash
#===============================================================================
# engine/sandbox_integrity_check.sh - v11.2 Sandbox Integrity Gate
# Mandatory pre-execution gate - ALL checks must pass before stage runs
#===============================================================================
set -euo pipefail

[[ -n "${_SANDBOX_INTEGRITY_SOURCED:-}" ]] && return 0

readonly INTEGRITY_VERSION="11.2"
readonly GATE_LOG="/var/log/pop-os-sandbox/integrity-gate.log"

log_gate()  { echo "[$(date +%T)] $*" | tee -a "$GATE_LOG" 2>/dev/null || echo "$*"; }
ok_gate()   { echo "[$(date +%T)] [OK]  $*" | tee -a "$GATE_LOG" 2>/dev/null || echo "$*"; }
warn_gate() { echo "[$(date +%T)] [WARN] $*" | tee -a "$GATE_LOG" 2>/dev/null || echo "$*"; }
err_gate()  { echo "[$(date +%T)] [ERR]  $*" >&2; }

sandbox_integrity_gate() {
    local run_id="${1:-gate-$(date +%s)}"
    local errors=0 warnings=0

    log_gate "[GATE] [INTEGRITY GATE v${INTEGRITY_VERSION}] Pre-stage verification..."

    log_gate "  Checking syscall policy..."
    local policy_sh
    policy_sh=$(find "${ENGINEDIR}" -name "syscall_policy.sh" -type f 2>/dev/null | head -1)
    if [[ -n "$policy_sh" ]]; then
        bash -n "$policy_sh" 2>/dev/null
        if [[ $? -eq 0 ]]; then
            ok_gate "  [OK] Syscall policy OK"
        else
            err_gate "  [ERR] Syscall policy SYNTAX ERROR"
            ((errors++)) || true
        fi
    else
        err_gate "  [ERR] Syscall policy NOT FOUND"
        ((errors++)) || true
    fi

    log_gate "  Checking sandbox runtime..."
    local sandbox_sh
    sandbox_sh=$(find "${ENGINEDIR}" -name "sandbox_runtime.sh" -type f 2>/dev/null | head -1)
    if [[ -n "$sandbox_sh" ]]; then
        bash -n "$sandbox_sh" 2>/dev/null
        if [[ $? -eq 0 ]]; then
            ok_gate "  [OK] Sandbox runtime OK"
        else
            err_gate "  [ERR] Sandbox runtime SYNTAX ERROR"
            ((errors++)) || true
        fi
    else
        err_gate "  [ERR] Sandbox runtime NOT FOUND"
        ((errors++)) || true
    fi

    log_gate "  Checking tracer..."
    if [[ -f "${SCRIPT_DIR}/observability/tracer.sh" ]]; then
        source "${SCRIPT_DIR}/observability/tracer.sh" 2>/dev/null || true
        if [[ "${TRACE_ENABLED:-0}" == "1" ]]; then
            ok_gate "  [OK] Tracer active"
        else
            warn_gate "  [WARN] Tracer DISABLED"
            ((warnings++)) || true
        fi
    else
        warn_gate "  [WARN] Tracer NOT FOUND"
        ((warnings++)) || true
    fi

    log_gate "  Checking pipeline lock..."
    local lock_file="${STATE_DIR:-/var/lib/pop-os-setup}/pipeline.lock"
    mkdir -p "$(dirname "$lock_file")" 2>/dev/null || true
    if [[ -f "$lock_file" ]]; then
        local lock_pid
        lock_pid=$(cat "$lock_file" 2>/dev/null || echo "")
        if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
            err_gate "  [ERR] Pipeline locked by PID $lock_pid"
            ((errors++)) || true
        else
            rm -f "$lock_file" 2>/dev/null || true
        fi
    fi
    ok_gate "  [OK] Lock file OK"

    log_gate "  Checking namespace support..."
    if unshare --help &>/dev/null; then
        ok_gate "  [OK] unshare available"
    else
        warn_gate "  [WARN] unshare NOT available"
        ((warnings++)) || true
    fi

    log_gate "  Checking sandbox state directory..."
    mkdir -p "/run/pop-os-sandbox" 2>/dev/null || true
    if [[ -d "/run/pop-os-sandbox" ]]; then
        ok_gate "  [OK] /run/pop-os-sandbox accessible"
    else
        err_gate "  [ERR] Sandbox state dir FAILED"
        ((errors++)) || true
    fi

    log_gate "  Checking failure classifier..."
    if [[ -f "${ENGINEDIR}/sandbox/failure_classifier.sh" ]]; then
        bash -n "${ENGINEDIR}/sandbox/failure_classifier.sh" 2>/dev/null
        if [[ $? -eq 0 ]]; then
            ok_gate "  [OK] Failure classifier OK"
        else
            err_gate "  [ERR] Failure classifier SYNTAX ERROR"
            ((errors++)) || true
        fi
    else
        warn_gate "  [WARN] Failure classifier NOT FOUND"
        ((warnings++)) || true
    fi

    log_gate ""
    if [[ $errors -gt 0 ]]; then
        err_gate "[X] INTEGRITY GATE FAILED - $errors error(s)"
        return 1
    elif [[ $warnings -gt 0 ]]; then
        warn_gate "[WARN] INTEGRITY GATE PASSED with $warnings warning(s)"
        return 0
    else
        ok_gate "[PASS] INTEGRITY GATE PASSED - all checks OK"
        return 0
    fi
}

log_integrity_gate_result() {
    local run_id="$1" result="$2" errors="$3" warnings="$4"
    local timestamp
    timestamp=$(date -Iseconds)
    mkdir -p "$(dirname "$GATE_LOG")" 2>/dev/null || true
    echo "[${timestamp}] INTEGRITY_GATE|run_id=${run_id}|result=${result}|errors=${errors}|warnings=${warnings}" \
        >> "$GATE_LOG" 2>/dev/null || true
}

export -f sandbox_integrity_gate log_integrity_gate_result
export INTEGRITY_VERSION GATE_LOG

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
    ENGINEDIR="${SCRIPT_DIR}/engine"
    STATEDIR="${STATEDIR:-/var/lib/pop-os-setup}"
    STATE_DIR="${STATEDIR}"
    source "${LIBDIR}/runtime.sh" 2>/dev/null || true

    echo "=========================================="
    echo "  Sandbox Integrity Gate v${INTEGRITY_VERSION}"
    echo "=========================================="
    echo ""

    sandbox_integrity_gate "standalone-$$"
    exit $?
fi

echo "[SANDBOX_INTEGRITY] v${INTEGRITY_VERSION} gate loaded"
