#!/usr/bin/env bash
#=================================================
# engine/epoch_chain_validator.sh — v10.2
# Enforces strict epoch linearity + drift detection
#=================================================
[[ -n "${_EPOCH_VALIDATOR_SOURCED:-}" ]] && return 0 || _EPOCH_VALIDATOR_SOURCED=1

# ─── EPOCH DRIFT DETECTION ──────────────────────────────────────────────────
detect_epoch_drift() {
    local requested_epoch="${REPLAY_FROM_EPOCH:-0}"
    local latest_epoch
    latest_epoch=$(get_latest_epoch)
    local STATE_DIR="${STATE_DIR:-/var/lib/pop-os-setup/state}"
    local registry="${STATE_DIR}/epoch_registry.jsonl"

    # No skipping allowed: must reconstruct missing epochs
    if [[ "$requested_epoch" -lt "$latest_epoch" ]]; then
        # Check if intermediate epochs exist
        for e in $(seq $((requested_epoch + 1)) "$latest_epoch"); do
            [[ -f "${STATE_DIR}/checkpoints/epoch_${e}.json" ]] || {
                echo '{"event":"epoch.drift_detected","severity":"critical","detail":"missing_epoch_'${e}'"}'
                return 2
            }
        done
        echo "INFO: auto-reconstructing epochs ${requested_epoch}→${latest_epoch}"
        return 0
    fi

    # Replay epoch mismatch
    if [[ "$requested_epoch" -gt "$latest_epoch" ]]; then
        echo '{"event":"epoch.drift_detected","severity":"critical","detail":"epoch_not_yet_created"}'
        return 2
    fi

    echo "EPOCH_DRIFT_NONE"
    return 0
}

# ─── REPLAY BECOMES LINEARIZED ──────────────────────────────────────────────
linearized_replay() {
    local replay_epoch="${REPLAY_FROM_EPOCH:-0}"
    local latest
    latest=$(get_latest_epoch)

    detect_epoch_drift || {
        echo "FATAL: replay blocked — epoch chain broken or incomplete"
        return 1
    }

    # Reconstruct full CESM chain
    linearize_epochs "$replay_epoch" "$latest"
    echo "LINEARIZED_REPLAY_COMPLETE"
    return 0
}

# ─── METRICS ────────────────────────────────────────────────────────────────
epoch_chain_integrity_score() {
    local registry="${STATE_DIR:-/var/lib/pop-os-setup/state}/epoch_registry.jsonl"
    local total_epochs missing broken
    total_epochs=$(wc -l < "$registry")
    missing=$(grep -c '"status":"missing"' "$registry" 2>/dev/null || echo "0")
    broken=$((total_epochs == 0 ? 1 : 0))
    echo "scale=2; ($total_epochs - $missing - $broken) * 100 / $total_epochs" | bc 2>/dev/null || echo "0"
}

export -f detect_epoch_drift linearized_replay epoch_chain_integrity_score
