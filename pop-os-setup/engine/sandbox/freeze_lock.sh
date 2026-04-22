#!/usr/bin/env bash
#===============================================================================
# engine/sandbox/freeze_lock.sh - v11.2 Execution Freeze Mechanism
# Locks stage definitions hash, prevents runtime modification
# Exit: 0=OK, 50=HARD FAIL
#===============================================================================
set -euo pipefail

FREEZE_VERSION="11.2"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
fi
LIBDIR="${SCRIPT_DIR}/lib"
ENGINEDIR="${SCRIPT_DIR}/engine"
STATEDIR="${STATEDIR:-/var/lib/pop-os-setup}"
source "${LIBDIR}/runtime.sh" 2>/dev/null || true

FREEZE_LOG="${STATEDIR}/freeze_lock.log"
FREEZE_META="${STATEDIR}/freeze_meta"

log_fr()  { echo "[$(date +%T)] $*" | tee -a "$FREEZE_LOG" 2>/dev/null || echo "$*"; }
err_fr()  { echo "[$(date +%T)] [ERR]  $*" >&2; }
ok_fr()   { echo "[$(date +%T)] [OK]  $*" | tee -a "$FREEZE_LOG" 2>/dev/null || echo "$*"; }

compute_component_hash() {
    local component="$1"
    local path

    case "$component" in
        stages)        path="${SCRIPT_DIR}/stages" ;;
        syscall_policy) path="${ENGINEDIR}/sandbox/syscall_policy.sh" ;;
        deterministic) path="${ENGINEDIR}/deterministic.sh" ;;
        runtime)       path="${LIBDIR}/runtime.sh" ;;
        sandbox)       path="${ENGINEDIR}/sandbox_runtime.sh" ;;
        *)             path="$component" ;;
    esac

    if [[ -d "$path" ]]; then
        find "$path" -type f \( -name "*.sh" -o -name "*.json" \) 2>/dev/null | sort | \
            xargs cat 2>/dev/null | sha256sum | awk '{print $1}'
    elif [[ -f "$path" ]]; then
        cat "$path" | sha256sum | awk '{print $1}'
    else
        echo "MISSING"
    fi
}

compute_freeze_hash() {
    local stage_hash syscall_hash det_hash rt_hash sb_hash
    stage_hash=$(compute_component_hash stages)
    syscall_hash=$(compute_component_hash syscall_policy)
    det_hash=$(compute_component_hash deterministic)
    rt_hash=$(compute_component_hash runtime)
    sb_hash=$(compute_component_hash sandbox)

    printf '%s%s%s%s%s' "$stage_hash" "$syscall_hash" "$det_hash" "$rt_hash" "$sb_hash" | \
        sha256sum | awk '{print $1}'
}

store_freeze() {
    local run_id="$1"
    local freeze_hash="$2"

    mkdir -p "$FREEZE_META" "${STATEDIR}" 2>/dev/null || true

    local freeze_file="${STATEDIR}/freeze_${run_id}.hash"
    local meta_file="${FREEZE_META}/freeze_${run_id}.meta"

    echo "$freeze_hash" > "$freeze_file"

    cat > "$meta_file" << EOF
{
  "run_id": "${run_id}",
  "freeze_hash": "${freeze_hash}",
  "stage_hash": "$(compute_component_hash stages)",
  "syscall_policy_hash": "$(compute_component_hash syscall_policy)",
  "deterministic_hash": "$(compute_component_hash deterministic)",
  "runtime_hash": "$(compute_component_hash runtime)",
  "sandbox_hash": "$(compute_component_hash sandbox)",
  "frozen_at": "$(date -Iseconds)",
  "version": "${FREEZE_VERSION}",
  "hostname": "$(hostname)"
}
EOF

    log_fr "FROZEN: run_id=${run_id} hash=${freeze_hash}"
    echo "[FREEZE] ${run_id}|${freeze_hash}" >> "${STATEDIR}/freeze_registry.jsonl" 2>/dev/null || true
}

validate_freeze() {
    local run_id="$1"
    local freeze_file="${STATEDIR}/freeze_${run_id}.hash"

    if [[ ! -f "$freeze_file" ]]; then
        err_fr "No freeze found for run_id: ${run_id}"
        return 50
    fi

    local stored_hash current_hash
    stored_hash=$(cat "$freeze_file")
    current_hash=$(compute_freeze_hash)

    if [[ "$stored_hash" != "$current_hash" ]]; then
        err_fr "HARD FAIL: Runtime hash mismatch"
        err_fr "  Stored:  ${stored_hash}"
        err_fr "  Current: ${current_hash}"
        err_fr "    stages:        $(compute_component_hash stages)"
        err_fr "    syscall_policy: $(compute_component_hash syscall_policy)"
        err_fr "    deterministic: $(compute_component_hash deterministic)"
        err_fr "    runtime:       $(compute_component_hash runtime)"
        err_fr "    sandbox:       $(compute_component_hash sandbox)"
        return 50
    fi

    ok_fr "Freeze validated: hash=${stored_hash}"
    return 0
}

freeze_lock() {
    local run_id="$1"
    local action="$2"

    echo "=========================================="
    echo "  Sandbox Freeze Lock v${FREEZE_VERSION}"
    echo "  Run ID: ${run_id}"
    echo "  Action: ${action}"
    echo "=========================================="
    echo ""

    mkdir -p "$FREEZE_META" "${STATEDIR}" 2>/dev/null || true

    case "$action" in
        lock)
            local fh
            fh=$(compute_freeze_hash)
            store_freeze "$run_id" "$fh"
            echo ""
            echo "  Freeze hash: ${fh}"
            echo "  Status: LOCKED"
            echo ""
            return 0
            ;;
        validate)
            validate_freeze "$run_id"
            local rc=$?
            if [[ $rc -eq 0 ]]; then
                echo ""
                echo "  Status: VALID (freeze intact)"
                echo ""
            else
                echo ""
                echo "  Status: HARD FAIL (exit 50)"
                echo ""
            fi
            return $rc
            ;;
        status)
            local freeze_file="${STATEDIR}/freeze_${run_id}.hash"
            if [[ -f "$freeze_file" ]]; then
                echo "  Status: LOCKED"
                echo "  Hash: $(cat "$freeze_file")"
            else
                echo "  Status: NOT FROZEN"
            fi
            echo ""
            return 0
            ;;
        *)
            err_fr "Unknown action: $action (use: lock|validate|status)"
            return 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    freeze_lock "${1:-default}" "${2:-lock}"
    exit $?
fi
