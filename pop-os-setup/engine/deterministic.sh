#!/usr/bin/env bash
#===============================================
# engine/deterministic.sh — Deterministic Runner v11.0
# Pure bash, no runtime state in memory
#===============================================
set -euo pipefail

[[ -n "${_DETERMINISTIC:-}" ]] && return 0 || _DETERMINISTIC=1

source "${LIBDIR}/runtime.sh"
source "${LIBDIR}/state/cesm_store.sh" 2>/dev/null || source "${LIBDIR}/../state/cesm_store.sh"

# ─── Deterministic Run ──────────────────────────────────
run_deterministic() {
    local profile="${1:-full}"
    local epoch
    epoch=$(get_epoch)
    log "═══════════════════════════════════════"
    log "  Deterministic run — epoch $epoch"
    log "  Profile: $profile"
    log "  Replay from: ${REPLAY_FROM_EPOCH:-none}"
    log "═══════════════════════════════════════"

    if [[ "${REPLAY_FROM_EPOCH:-}" ]]; then
        log "REPLAY mode — reconstructing state from epoch $REPLAY_FROM_EPOCH"
    fi

    local run_id="det_${epoch}_$(date +%Y%m%d_%H%M%S)"
    local snap; snap=$(snap_save "$run_id" "preflight")
    log "Checkpoint: $snap"

    local failed=0 skipped=0 passed=0
    for stage in $(stages_by_profile "$profile"); do
        local stage_num="${stage%%_*}"
        local stage_name="${stage##*_}"

        # Skip if replay says so
        if [[ "${REPLAY_FROM_EPOCH:-}" ]] && is_stage_replayed "$stage_num"; then
            warn "[$stage_num] $stage_name — SKIPPED (replay)"
            ((skipped++)) || true; continue
        fi

        step "STAGE ${stage_num}" "$stage_name"
        if execute_stage "$stage"; then
            snap_save "$run_id" "${stage_num}_${stage_name}" >/dev/null
            ((passed++)) || true
        else
            err "[$stage_num] $stage_name — FAILED"
            ((failed++)) || true
            ((FAILED_STAGES+1)) || true
            [[ "${SAFE_MODE:-0}" == "1" ]] && return 1
        fi
    done

    snap_save "$run_id" "final" >/dev/null
    log "═══════════════════════════════════════"
    log "  PASSED: $passed | FAILED: $failed | SKIPPED: $skipped"
    log "═══════════════════════════════════════"
    return $((failed > 0 ? 1 : 0))
}

# Stub if CESM unavailable
is_stage_replayed() { [[ "${REPLAY_FROM_EPOCH:-}" ]] && return 0; }

export -f run_deterministic is_stage_replayed
