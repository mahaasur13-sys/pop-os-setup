#!/usr/bin/env bash
#===============================================================================
# engine/sandbox/failure_classifier.sh - v11.2 Sandbox Failure Classification
# Classifies violations into 4 categories with structured exit codes
# Attach classification to JSONL trace events
#===============================================================================

set -euo pipefail

[[ -n "${_FAILURE_CLASSIFIER_SOURCED:-}" ]] && return 0 || _FAILURE_CLASSIFIER_SOURCED=1

# Allowlists
source "${ENGINEDIR}/sandbox/syscall_policy.sh" 2>/dev/null || true

# --- EXIT CODES ---
readonly EXIT_SYSCALL_VIOLATION=10
readonly EXIT_WRITE_BOUNDARY_VIOLATION=20
readonly EXIT_NETWORK_ESCAPE=30
readonly EXIT_STATE_CORRUPTION=40
readonly EXIT_LOG_DIVERGENCE=50

# --- CLASSIFICATION ---
classify_failure() {
    local failure_type="$1"
    local detail="$2"
    local run_id="${3:-${SANDBOX_RUN_ID:-unknown}}"
    local stage="${4:-unknown}"
    local timestamp
    timestamp=$(date -Iseconds)

    local exit_code category severity classification

    case "$failure_type" in
        SYS_CALL_DENIED)
            exit_code=$EXIT_SYSCALL_VIOLATION
            category="SYSCALL_SECURITY"
            severity="HIGH"
            classification="Syscall denied by policy whitelist"
            ;;
        WRITE_BOUNDARY_VIOLATION)
            exit_code=$EXIT_WRITE_BOUNDARY_VIOLATION
            category="FILESYSTEM_SECURITY"
            severity="HIGH"
            classification="Attempted write outside sandbox boundary"
            ;;
        NETWORK_ESCAPE_ATTEMPT)
            exit_code=$EXIT_NETWORK_ESCAPE
            category="NETWORK_SECURITY"
            severity="CRITICAL"
            classification="Network operation attempted in isolated sandbox"
            ;;
        STATE_CORRUPTION_DETECTED)
            exit_code=$EXIT_STATE_CORRUPTION
            category="STATE_INTEGRITY"
            severity="CRITICAL"
            classification="State hash mismatch - execution integrity broken"
            ;;
        LOG_DIVERGENCE_FAILURE)
            exit_code=$EXIT_LOG_DIVERGENCE
            category="LOG_INTEGRITY"
            severity="MEDIUM"
            classification="Log divergence detected - potential tampering"
            ;;
        *)
            exit_code=1
            category="UNKNOWN"
            severity="MEDIUM"
            classification="Unclassified failure: $failure_type"
            ;;
    esac

    local event_json
    event_json=$(printf '{"ts":"%s","level":"error","event":"sandbox.failure.classified","run_id":"%s","stage_id":"%s","failure_type":"%s","exit_code":%d,"category":"%s","severity":"%s","classification":"%s","detail":"%s","hostname":"%s","user":"%s","pid":%d,"fingerprint":"%s"}' \
        "$timestamp" "$run_id" "$stage" "$failure_type" "$exit_code" "$category" "$severity" "$classification" "$detail" "$(hostname)" "$(whoami)" "$$" "${SANDBOX_FINGERPRINT:-unknown}")

    echo "$event_json" | tee -a "${TRACE_FILE:-/dev/stdout}" 2>/dev/null

    mkdir -p "$(dirname "${VIOLATION_LOG:-/var/log/pop-os-sandbox/syscall_violations.log}")" 2>/dev/null || true
    printf '[%s] CLASSIFIED|%s|exit=%d|%s\n' "$timestamp" "$failure_type" "$exit_code" "$detail" \
        >> "${VIOLATION_LOG:-/var/log/pop-os-sandbox/syscall_violations.log}" 2>/dev/null || true

    return $exit_code
}

attach_classification() {
    local run_id="$1"
    local stage="$2"
    local failure_type="$3"
    local detail="$4"
    classify_failure "$failure_type" "$detail" "$run_id" "$stage"
    return $?
}

get_exit_code_for() {
    local failure_type="$1"
    case "$failure_type" in
        SYS_CALL_DENIED)           echo $EXIT_SYSCALL_VIOLATION ;;
        WRITE_BOUNDARY_VIOLATION)   echo $EXIT_WRITE_BOUNDARY_VIOLATION ;;
        NETWORK_ESCAPE_ATTEMPT)     echo $EXIT_NETWORK_ESCAPE ;;
        STATE_CORRUPTION_DETECTED)  echo $EXIT_STATE_CORRUPTION ;;
        LOG_DIVERGENCE_FAILURE)     echo $EXIT_LOG_DIVERGENCE ;;
        *)                          echo 1 ;;
    esac
}

get_severity_for() {
    local failure_type="$1"
    case "$failure_type" in
        SYS_CALL_DENIED)           echo "HIGH" ;;
        WRITE_BOUNDARY_VIOLATION)   echo "HIGH" ;;
        NETWORK_ESCAPE_ATTEMPT)     echo "CRITICAL" ;;
        STATE_CORRUPTION_DETECTED) echo "CRITICAL" ;;
        *)                          echo "MEDIUM" ;;
    esac
}

export -f classify_failure attach_classification
export -f get_exit_code_for get_severity_for

export EXIT_SYSCALL_VIOLATION EXIT_WRITE_BOUNDARY_VIOLATION
export EXIT_NETWORK_ESCAPE EXIT_STATE_CORRUPTION

echo "[FAILURE_CLASSIFIER] v11.2 loaded - exit codes: SYSCALL=10 WRITE=20 NETWORK=30 STATE=40"
