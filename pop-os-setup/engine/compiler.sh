#!/bin/bash
#===============================================================================
# engine/compiler.sh — v5.0.0 MANIFEST → Execution Graph Compiler
# Reads MANIFEST.json, resolves dependencies, produces execution-plan.json
# with topological levels (parallel groups) and deterministic ordering
#===============================================================================

[[ -z "${_ENGINE_SOURCED:-}" ]] && { _ENGINE_SOURCED=1; } || return 0

# ─── INCLUDE DEPENDENCIES ──────────────────────────────────────────────────────
source "${LIBDIR}/_dag.sh" 2>/dev/null || true
source "${LIBDIR}/_state.sh" 2>/dev/null || true

# ─── COMPILER: MANIFEST → PLAN ───────────────────────────────────────────────
compile_manifest() {
    local manifest="${1:-${MANIFEST_PATH}}"
    local plan_file="${2:-${STATE_DIR}/execution-plan.json}"

    log "Compiling MANIFEST.json → execution plan..."

    ensure_dir "${STATE_DIR}"

    python3 - << 'PYEOF'
import json, sys, os

MANIFEST = os.environ.get('MANIFEST', os.environ.get('MANIFEST_PATH', 'MANIFEST.json'))
PLAN_FILE = os.environ.get('PLAN_FILE', os.environ.get('STATE_DIR', '.') + '/execution-plan.json')

try:
    m = json.load(open(MANIFEST))
except Exception as e:
    print(f"FATAL: {e}", file=sys.stderr); sys.exit(1)

stages = m.get('stages', [])
profile = os.environ.get('PROFILE', 'full')

# ── Filter by profile ─────────────────────────────────────────────────────
filtered = [
    s for s in stages
    if profile in s.get('profile', []) or 'all' in s.get('profile', [])
    if s.get('enabled', True) is not False
]

# ── Build node list ────────────────────────────────────────────────────────
nodes = []
node_ids = set()
for s in filtered:
    nid = s['id']
    node_ids.add(nid)
    nodes.append({
        'id': nid,
        'name': s.get('name', nid),
        'file': f"stages/stage{id_to_file(nid)}.sh",
        'deps': s.get('deps', []),
        'parallel': s.get('parallel', False),
        'timeout': s.get('timeout', 300),
        'rollback': s.get('rollback', True),
        'hash': s.get('sha256', None),
    })

# ── Kahn's algorithm for topological levels ──────────────────────────────────
def toposort(nodes):
    # Build adjacency and in-degree
    adj = {n['id']: [] for n in nodes}
    in_deg = {n['id']: 0 for n in nodes}
    all_ids = set(in_deg.keys())

    for n in nodes:
        for dep in n.get('deps', []):
            if dep in all_ids:
                adj[dep].append(n['id'])
                in_deg[n['id']] += 1

    # Level assignment: BFS
    levels = []
    remaining = set(all_ids)
    level_buckets = {nid: 0 for nid in all_ids}

    frontier = [nid for nid, d in in_deg.items() if d == 0]
    while frontier:
        level_nodes = []
        next_frontier = []
        for nid in frontier:
            if nid not in remaining:
                continue
            remaining.remove(nid)
            level_buckets[nid] = len(levels)
            level_nodes.append(nid)
            for neighbor in adj[nid]:
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    next_frontier.append(neighbor)
        levels.append(level_nodes)
        frontier = next_frontier

    if remaining:
        cycle = remaining
        print(f"CYCLE DETECTED: {cycle}", file=sys.stderr)
        sys.exit(1)

    return level_buckets

def id_to_file(nid):
    # stage01_preflight → stage1_preflight
    parts = nid.split('_', 1)
    num = int(parts[0])
    name = parts[1] if len(parts) > 1 else ''
    num_str = str(num)  # single-digit
    return f"stage{num_str}_{name}.sh"

# ── Group by level (parallel-safe within level) ──────────────────────────────
level_map = toposort(nodes)

level_groups = {}
for n in nodes:
    lvl = level_map[n['id']]
    level_groups.setdefault(lvl, []).append(n['id'])

# ── Edges ──────────────────────────────────────────────────────────────────────
edges = []
for n in nodes:
    for dep in n.get('deps', []):
        if dep in node_ids:
            edges.append({'from': dep, 'to': n['id']})

# ── Compute overall manifest SHA ────────────────────────────────────────────
import hashlib, subprocess
result = subprocess.run(
    ['find', 'stages', '-name', 'stage*.sh', '-type', 'f'],
    capture_output=True, text=True, cwd=os.environ.get('SCRIPT_DIR','.')
)
files = sorted(result.stdout.strip().split('\n'))
sha = hashlib.sha256()
for fpath in files:
    if os.path.isfile(fpath):
        with open(fpath, 'rb') as f:
            sha.update(f.read())
manifest_sha = sha.hexdigest()

# ── Build plan ──────────────────────────────────────────────────────────────
plan = {
    'version': m.get('version', '5.0.0'),
    'schema': m.get('schema', '2.0'),
    'run_id': os.environ.get('RUN_ID', 'unknown'),
    'profile': profile,
    'compiled_at': subprocess.run(['date', '-Iseconds'], capture_output=True, text=True).stdout.strip(),
    'graph': {
        'nodes': [{'id': n['id'], 'name': n['name']} for n in nodes],
        'edges': edges,
        'levels': [[{'id': nid, 'name': next(x['name'] for x in nodes if x['id']==nid)} for nid in level_groups[l]] for l in sorted(level_groups)],
    },
    'manifest_sha': manifest_sha,
    'validated': True,
    'total_stages': len(nodes),
    'total_levels': len(level_groups),
    'profile_filter': profile,
}

ensure_dir(os.path.dirname(PLAN_FILE))
with open(PLAN_FILE, 'w') as f:
    json.dump(plan, f, indent=2)

print(f"Compiled: {len(nodes)} stages, {len(level_groups)} levels")
print(f"Plan: {PLAN_FILE}")
PYEOF
    local rc=$?

    if [[ $rc -eq 0 ]]; then
        ok "Execution plan compiled: $(cat "${STATE_DIR}/execution-plan.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"{d[total_stages]} stages / {d[total_levels]} levels")' 2>/dev/null || echo "OK")"
    fi

    return $rc
}

export -f compile_manifest