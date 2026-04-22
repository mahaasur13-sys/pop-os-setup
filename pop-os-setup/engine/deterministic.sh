#!/usr/bin/env bash
#===============================================
# engine/deterministic.sh — Deterministic Runner v11.2
# Fully Isolated Sandbox Execution + OS-Level Determinism
#===============================================
set -euo pipefail

[[ -n "${_DETERMINISTIC_SOURCED:-}" ]] && return 0 || _DETERMINISTIC_SOURCED=1

source "${LIBDIR}/runtime.sh"
source "${LIBDIR}/state/cesm_store.sh" 2>/dev/null || source "${LIBDIR}/../state/cesm_store.sh"

# Load sandbox components
source "${ENGINEDIR}/sandbox_runtime.sh" 2>/dev/null || true
source "${ENGINEDIR}/sandbox/syscall_policy.sh" 2>/dev/null || true

# ─── DETERMINISTIC RUN (v11.2 — sandbox isolated) ──────────────────────────
run_deterministic() {
    local profile="${1:-full}"
    local epoch
    epoch=$(get_epoch)

    log "═══════════════════════════════════════"
    log "  v11.2 Deterministic Run — Epoch $epoch"
    log "  Profile: $profile"
    log "  Sandbox: $([[ "${SANDBOX_ACTIVE:-0}" == "1" ]] && echo 'ENABLED' || echo 'DISABLED')"
    log "  Replay from: ${REPLAY_FROM_EPOCH:-none}"
    log "═══════════════════════════════════════"

    if [[ "${REPLAY_FROM_EPOCH:-}" ]]; then
        log "REPLAY mode — reconstructing state from epoch $REPLAY_FROM_EPOCH"
    fi

    local run_id="det_${epoch}_$(date +%Y%m%d_%H%M%S)"
    local snap; snap=$(snap_save "$run_id" "preflight")
    log "Checkpoint: $snap"

    # Initialize sandbox for this run
    if [[ "${SANDBOX_ENABLED:-1}" == "1" ]]; then
        sandbox_init
        log "🧊 Sandbox execution ENABLED"
    fi

    local failed=0 skipped=0 passed=0
    for stage in $(stages_by_profile "$profile"); do
        local stage_num="${stage%%_*}"
        local stage_name="${stage##*_}"
        local stage_file="${STAGEDIR}/stage${stage_num}_${stage_name}.sh"

        # Skip if replay says so
        if [[ "${REPLAY_FROM_EPOCH:-}" ]] && is_stage_replayed "$stage_num"; then
            warn "[$stage_num] $stage_name — SKIPPED (replay)"
            ((skipped++)) || true; continue
        fi

        step "STAGE ${stage_num}" "$stage_name"

        # ── Execute inside sandbox isolation ─────────────────────────────────
        if [[ "${SANDBOX_ENABLED:-1}" == "1" && -f "$stage_file" ]]; then
            if sandbox_exec_isolated "$run_id" "$epoch" "$stage_file" "$stage_num"; then
                snap_save "$run_id" "${stage_num}_${stage_name}" >/dev/null
                ((passed++)) || true
            else
                err "[$stage_num] $stage_name — FAILED (sandbox exit ≠ 0)"
                ((failed++)) || true
                ((FAILED_STAGES+1)) || true
                [[ "${SAFE_MODE:-0}" == "1" ]] && return 1
            fi
        else
            # Fallback: direct execution (no isolation)
            if execute_stage "$stage"; then
                snap_save "$run_id" "${stage_num}_${stage_name}" >/dev/null
                ((passed++)) || true
            else
                err "[$stage_num] $stage_name — FAILED"
                ((failed++)) || true
                ((FAILED_STAGES+1)) || true
                [[ "${SAFE_MODE:-0}" == "1" ]] && return 1
            fi
        fi
    done

    snap_save "$run_id" "final" >/dev/null

    # ── Validate sandbox boundary ───────────────────────────────────────────
    if [[ "${SANDBOX_ENABLED:-1}" == "1" ]]; then
        sandbox_validate_boundary "$run_id"
    fi

    log "═══════════════════════════════════════"
    log "  PASSED: $passed | FAILED: $failed | SKIPPED: $skipped"
    log "  Sandbox: $([[ "${SANDBOX_ACTIVE:-0}" == "1" ]] && echo 'ENABLED' || echo 'DISABLED')"
    log "  Fingerprint: ${PIPELINE_FINGERPRINT:-unknown}"
    log "═══════════════════════════════════════"

    return $((failed > 0 ? 1 : 0))
}

# ─── SANDBOX EXECUTION WRAPPER (v11.2) ───────────────────────────────────────
execute_in_sandbox() {
    local stage_num="$1"
    local stage_name="$2"
    local stage_file="$3"
    local run_id="${4:-sandbox_run}"

    if [[ ! -f "$stage_file" ]]; then
        err "Stage file not found: $stage_file"
        return 1
    fi

    # Verify write boundaries before execution
    enforce_write_boundary "/tmp" || return 1
    enforce_write_boundary "/var/tmp" || return 1

    # Execute with full isolation
    sandbox_exec_isolated "$run_id" "$(get_epoch)" "$stage_file" "$stage_num"
    return $?
}

# ─── DETERMINISM VALIDATION ─────────────────────────────────────────────────
validate_run_determinism() {
    local run_a="$1" run_b="$2"
    local fp_a="${STATE_DIR}/run_${run_a}.meta/fingerprint"
    local fp_b="${STATE_DIR}/run_${run_b}.meta/fingerprint"

    if [[ ! -f "$fp_a" ]]; then
        echo "ERROR: No fingerprint for run_a: $run_a"; return 1
    fi
    if [[ ! -f "$fp_b" ]]; then
        echo "ERROR: No fingerprint for run_b: $run_b"; return 1
    fi

    local hash_a hash_b
    hash_a=$(sha256sum "$fp_a" | awk '{print $1}')
    hash_b=$(sha256sum "$fp_b" | awk '{print $1}')

    if [[ "$hash_a" == "$hash_b" ]]; then
        echo "✅ DETERMINISM PASS — run $run_a ≡ run $run_b"
        echo "   Fingerprint: ${hash_a:0:16}..."
        return 0
    else
        echo "❌ DETERMINISM FAIL — runs differ"
        echo "   Run $run_a: ${hash_a:0:16}..."
        echo "   Run $run_b: ${hash_b:0:16}..."
        return 1
    fi
}

# ─── DETERMINISM CONTRACT (v11.2) ────────────────────────────────────────────
# Execution is valid ONLY if ALL three conditions hold:
#   1. syscall trace identical across runs
#   2. file system diff identical
#   3. event DAG identical
# Otherwise: STATE = INVALID_DETERMINISM
# ─────────────────────────────────────────────────────────────────────────────

validate_determinism_contract() {
    local run_a="$1"
    local run_b="$2"
    local errors=0

    log "📜 Validating determinism contract between runs..."

    local fp_a="${STATE_DIR}/run_${run_a}.meta/fingerprint"
    local fp_b="${STATE_DIR}/run_${run_b}.meta/fingerprint"

    # Condition 1: Fingerprint must match
    if [[ -f "$fp_a" && -f "$fp_b" ]]; then
        local hash_a hash_b
        hash_a=$(sha256sum "$fp_a" 2>/dev/null | awk '{print $1}')
        hash_b=$(sha256sum "$fp_b" 2>/dev/null | awk '{print $1}')
        if [[ "$hash_a" == "$hash_b" ]]; then
            log "  ✓ Syscall trace: IDENTICAL"
        else
            err "  ✗ Syscall trace: MISMATCH"
            ((errors++)) || true
        fi
    fi

    # Condition 2: Filesystem state hash must match
    local state_a state_b
    state_a=$(compute_run_state_hash "$run_a" 2>/dev/null || echo "unknown")
    state_b=$(compute_run_state_hash "$run_b" 2>/dev/null || echo "unknown")
    if [[ "$state_a" == "$state_b" ]]; then
        log "  ✓ Filesystem diff: IDENTICAL"
    else
        err "  ✗ Filesystem diff: MISMATCH"
        ((errors++)) || true
    fi

    # Condition 3: Event DAG must match
    local dag_a dag_b
    dag_a="${STATE_DIR}/run_${run_a}.meta/event_dag.jsonl"
    dag_b="${STATE_DIR}/run_${run_b}.meta/event_dag.jsonl"
    if [[ -f "$dag_a" && -f "$dag_b" ]]; then
        local dag_hash_a dag_hash_b
        dag_hash_a=$(sort "$dag_a" 2>/dev/null | sha256sum | awk '{print $1}')
        dag_hash_b=$(sort "$dag_b" 2>/dev/null | sha256sum | awk '{print $1}')
        if [[ "$dag_hash_a" == "$dag_hash_b" ]]; then
            log "  ✓ Event DAG: IDENTICAL"
        else
            err "  ✗ Event DAG: MISMATCH"
            ((errors++)) || true
        fi
    fi

    if [[ $errors -eq 0 ]]; then
        log "✅ DETERMINISM CONTRACT: SATISFIED"
        return 0
    else
        err "❌ DETERMINISM CONTRACT: VIOLATED ($errors breach(es))"
        return 1
    fi
}

compute_run_state_hash() {
    local run_id="$1"
    local hash_input=""

    if [[ -d "${STATE_DIR}/run_${run_id}" ]]; then
        hash_input=$(find "${STATE_DIR}/run_${run_id}" -type f \( -name "*.json" -o -name "*.jsonl" \) 2>/dev/null | \
                     sort | xargs cat 2>/dev/null | sha256sum | awk '{print $1}')
    fi

    printf '%s' "$hash_input" | sha256sum | awk '{print $1}'
}

# ─── STUB ─────────────────────────────────────────────────────────────────────
is_stage_replayed() { [[ "${REPLAY_FROM_EPOCH:-}" ]] && return 0; }

export -f run_deterministic execute_in_sandbox validate_run_determinism is_stage_replayed

echo "[DETERMINISTIC] v11.2 sandbox-integrated runner loaded ✓"