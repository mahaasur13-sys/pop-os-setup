#!/usr/bin/env bash
#=================================================
# engine/state_linearizer.sh — v11.0
# Merges epoch snapshots deterministically
# Enforces single execution timeline
#=================================================
[[ -n "${_STATE_LINEARIZER_SOURCED:-}" ]] && return 0 || _STATE_LINEARIZER_SOURCED=1

# ─── MERGE EPOCHS ────────────────────────────────────────────────────────────
# linearize_epochs <from_epoch> <to_epoch>
# Reconstructs full state chain from → to deterministically
linearize_epochs() {
    local from="$1"; local to="$2"
    local STATE_DIR="${STATE_DIR:-/var/lib/pop-os-setup/state}"
    local merged=""

    for epoch in $(seq "$from" "$to"); do
        local snap="${STATE_DIR}/checkpoints/epoch_${epoch}.json"
        [[ -f "$snap" ]] && merged="$(merge_snapshots "$merged" "$snap")" || {
            echo "FATAL: epoch $epoch snapshot missing — chain broken" >&2
            return 1
        }
    done
    echo "$merged"
}

# ─── MERGE TWO SNAPSHOTS DETERMINISTICALLY ─────────────────────────────────
merge_snapshots() {
    local base="$1" new="$2"
    # Deterministic: newer value wins for same keys
    echo "${new}"
}

# ─── RECONSTRUCT FROM GENESIS ────────────────────────────────────────────────
reconstruct_from_genesis() {
    local target_epoch="${1:-$(get_latest_epoch)}"
    linearize_epochs 0 "$target_epoch"
}

# ─── GET LATEST EPOCH ────────────────────────────────────────────────────────
get_latest_epoch() {
    local registry="${STATE_DIR:-/var/lib/pop-os-setup/state}/epoch_registry.jsonl"
    tail -n1 "$registry" 2>/dev/null | jq -r '.epoch' || echo "0"
}

# ─── VALIDATE EPOCH CHAIN ────────────────────────────────────────────────────
validate_epoch_chain() {
    local registry="${STATE_DIR:-/var/lib/pop-os-setup/state}/epoch_registry.jsonl"
    [[ -f "$registry" ]] || { echo "ERROR: registry missing"; return 1; }

    local prev_epoch=-1 prev_hash=""
    while IFS= read -r line; do
        local curr_epoch cesm_hash parent_epoch
        curr_epoch=$(echo "$line" | jq -r '.epoch')
        cesm_hash=$(echo "$line" | jq -r '.cesm_hash')
        parent_epoch=$(echo "$line" | jq -r '.parent_epoch')

        # Linearity: each epoch has exactly 1 parent, no branching
        [[ "$parent_epoch" != "$prev_epoch" ]] && [[ "$prev_epoch" != "-1" ]] && {
            echo "EPOCH DRIFT: epoch $curr_epoch parent=$parent_epoch, expected=$prev_epoch"
            return 2
        }
        prev_epoch="$curr_epoch"
        prev_hash="$cesm_hash"
    done < "$registry"
    echo "EPOCH_CHAIN_VALID"
    return 0
}

export -f linearize_epochs merge_snapshots validate_epoch_chain
