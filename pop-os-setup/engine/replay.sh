#!/bin/bash
#===============================================================================
# engine/replay.sh — v5.0.0 Replay Engine
# Re-run from any checkpoint, diff-only replay, replay-failed
#===============================================================================

[[ -z "${_ENGINE_SOURCED:-}" ]] && { _ENGINE_SOURCED=1; } || return 0

# ─── REPLAY FROM ─────────────────────────────────────────────────────────────
replay_from() {
    local cursor_node="$1"
    local state_file="${STATE_DIR}/state.json"

    [[ ! -f "$state_file" ]] && { err "No state.json found. Run full pipeline first."; return 1; }

    log "Replaying from: $cursor_node"

    python3 - << PYEOF
import json
state = json.load(open('${STATE_DIR}/state.json'))

# Find cursor position in execution plan
plan = json.load(open('${STATE_DIR}/execution-plan.json'))
levels = plan['graph']['levels']

cursor_idx = None
for lvl_idx, level in enumerate(levels):
    for n in level:
        if n['id'] == '${cursor_node}':
            cursor_idx = lvl_idx
            break
    if cursor_idx is not None:
        break

if cursor_idx is None:
    print(f"Node '${cursor_node}' not found in plan")
    exit(1)

# Reset nodes at and after cursor
for level in levels[cursor_idx:]:
    for n in level:
        nid = n['id']
        if nid in state['nodes']:
            old_status = state['nodes'][nid].get('status', 'pending')
            if old_status in ('success', 'checkpoint'):
                print(f"  Resetting {nid}: {old_status} → pending")
                state['nodes'][nid]['status'] = 'pending'
                state['nodes'][nid].pop('completed_at', None)
                state['nodes'][nid].pop('duration', None)
                state['nodes'][nid].pop('checkpoint', None)

state['status'] = 'replay'
state['replay_cursor'] = '${cursor_node}'
state['replay_at'] = '$(date -Iseconds)'

with open('${STATE_DIR}/state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f"Replay cursor set: ${cursor_node} (level {cursor_idx+1})")
PYEOF
    return $?
}

# ─── REPLAY FAILED ──────────────────────────────────────────────────────────────
replay_failed() {
    local state_file="${STATE_DIR}/state.json"
    [[ ! -f "$state_file" ]] && { err "No state.json found"; return 1; }

    log "Replaying failed nodes..."

    python3 - << PYEOF
import json
state = json.load(open('${STATE_DIR}/state.json'))
failed = [nid for nid, n in state['nodes'].items() if n.get('status') == 'failed']
if not failed:
    print("No failed nodes found")
    exit(0)

for nid in failed:
    print(f"  Resetting: {nid}")
    state['nodes'][nid]['status'] = 'pending'
    state['nodes'][nid].pop('failed_at', None)
    state['nodes'][nid].pop('exit_code', None)

state['status'] = 'replay'
state['replay_cursor'] = 'first_failed'
state['replay_at'] = '$(date -Iseconds)'

with open('${STATE_DIR}/state.json', 'w') as f:
    json.dump(state, f, indent=2)
print(f"Replaying: {len(failed)} failed nodes")
PYEOF
}

# ─── DIFF-ONLY REPLAY ─────────────────────────────────────────────────────────
replay_diff_only() {
    local state_file="${STATE_DIR}/state.json"
    [[ ! -f "$state_file" ]] && { err "No state.json found"; return 1; }

    log "Diff-only replay: re-run only changed nodes (by SHA256)..."

    python3 - << 'PYEOF'
import json, hashlib, subprocess, os

state = json.load(open('${STATE_DIR}/state.json'))
plan = json.load(open('${STATE_DIR}/execution-plan.json'))

def file_hash(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

changed = []
for n in plan['graph']['nodes']:
    nid = n['id']
    node_file = f"stages/{n.get('file', '')}"
    if not os.path.exists(node_file):
        continue
    current_hash = file_hash(node_file)
    prev_hash = state['nodes'].get(nid, {}).get('hash', '')
    if current_hash != prev_hash:
        changed.append(nid)
        print(f"  Changed: {nid} ({prev_hash[:8]} → {current_hash[:8]})")
        if nid in state['nodes']:
            state['nodes'][nid]['status'] = 'pending'
    else:
        print(f"  Unchanged: {nid}")

state['status'] = 'diff_replay'
state['replay_at'] = '$(date -Iseconds)'

with open('${STATE_DIR}/state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f"Diff replay: {len(changed)} changed nodes")
PYEOF
}

export -f replay_from replay_failed replay_diff_only