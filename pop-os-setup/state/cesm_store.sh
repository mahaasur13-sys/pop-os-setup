#!/usr/bin/env bash
#===============================================
# state/cesm_store.sh — CESM State Store v11.0
# Deterministic, reproducible, file-based state
#===============================================
set -euo pipefail

[[ -n "${_CESM_STORE:-}" ]] && return 0 || _CESM_STORE=1

declare -g CESM_STORE_DIR="${CESM_STORE_DIR:-/var/lib/pop-os-setup/state}"
declare -g CESM_SCHEMA_VERSION="2.0"
declare -g CESM_EPOCH=""

# ─── Epoch ─────────────────────────────────────────────
get_epoch() {
    local epoch_file="${CESM_STORE_DIR}/.epoch"
    if [[ -f "$epoch_file" ]]; then
        CESM_EPOCH=$(<"$epoch_file")
    else
        CESM_EPOCH="1"
    fi
    echo "$CESM_EPOCH"
}

next_epoch() {
    ensure_dir "$CESM_STORE_DIR"
    echo $((CESM_EPOCH + 1)) > "${CESM_STORE_DIR}/.epoch"
    CESM_EPOCH=$((CESM_EPOCH + 1))
}

# ─── Snapshot ───────────────────────────────────────────
snap_save() {
    local run_id="$1"; shift
    local label="${1:-snapshot}"
    ensure_dir "$CESM_STORE_DIR/checkpoints/${run_id}"
    local snap="${CESM_STORE_DIR}/checkpoints/${run_id}/${CESM_EPOCH}_${label}.json"
    cat > "$snap" <<-'SNAPEOF'
{"version":"2.0","schema":"checkpoint","epoch":null,"label":null,"created_at":null,"system":null,"stages":null}
SNAPEOF
    local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local sys; sys=$(uname -a 2>/dev/null || echo "unknown")
    local ver; ver=$(get_version 2>/dev/null || echo "unknown")
    python3 -c "
import json, sys
d=json.load(open('$snap'))
d['epoch']=$CESM_EPOCH
d['label']='$label'
d['created_at']='$ts'
d['system']={'uname':'$sys','version':'$ver','mode':${SAFE_MODE:-0}}
d['stages']={'completed':[],'failed':[],'skipped':[]}
json.dump(d,open('$snap','w'),indent=2)
" 2>/dev/null || true
    echo "SNAPSHOT:${snap}"
}

# ─── Replay ─────────────────────────────────────────────
snap_list() {
    local run_id="${1:-default}"
    local dir="${CESM_STORE_DIR}/checkpoints/${run_id}"
    [[ -d "$dir" ]] && ls -1t "$dir"/*.json 2>/dev/null || echo ""
}

snap_load() {
    local snap="${1?snap_load: need path}"
    [[ -f "$snap" ]] || { echo "SNAP_NOT_FOUND:$snap"; return 1; }
    python3 -c "import json; d=json.load(open('$snap')); print(d.get('epoch','?'))" 2>/dev/null
}

snap_reconstruct() {
    local snap="${1?snap_reconstruct: need path}"
    python3 -c "
import json, sys
d=json.load(open('$snap'))
print('epoch:', d.get('epoch'))
print('label:', d.get('label'))
print('created:', d.get('created_at'))
for k,v in d.get('stages',{}).items():
    print(k+':', ', '.join(v) or 'none')
" 2>/dev/null
}

export -f snap_save snap_list snap_load snap_reconstruct
