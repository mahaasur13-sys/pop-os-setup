#!/bin/bash
# engine/runtime.sh - v5.0.0 State-Aware DAG Runtime Engine

[[ -z "${_ENGINE_SOURCED:-}" ]] && { _ENGINE_SOURCED=1; } || return 0

source "${LIBDIR}/_dag.sh" 2>/dev/null || true
source "${LIBDIR}/_state.sh" 2>/dev/null || true
source "${LIBDIR}/_path.sh" 2>/dev/null || true

MAX_PARALLEL="${MAX_PARALLEL:-4}"
TIMEOUT_SCALE="${TIMEOUT_SCALE:-1}"
ROLLBACK_ON_ERROR="${ROLLBACK_ON_ERROR:-1}"
CHECKPOINT_DIR="${STATE_DIR}/checkpoints"
TRACE_FILE="${STATE_DIR}/traces/${RUN_ID}.jsonl"

trace() {
    local level="$1" node="$2" msg="$3" dur="${4:-null}"
    echo "{\"ts\":\"$(date -Iseconds)\",\"level\":\"$level\",\"node\":\"$node\",\"msg\":\"$msg\"${dur:+, \"duration\":$dur}}" >> "$TRACE_FILE"
}

save_checkpoint() {
    local node="$1" check_file="${CHECKPOINT_DIR}/${node}.json"
    ensure_dir "$(dirname "$check_file")"
    python3 - << PYEOF
import json, os
s = json.load(open('${STATE_DIR}/state.json'))
s['nodes']['${node}']['checkpoint'] = '$(date -Iseconds)'
s['nodes']['${node}']['status'] = 'checkpoint'
with open('${CHECKPOINT_DIR}/${node}.json','w') as f:
    json.dump(s['nodes']['${node}'], f)
PYEOF
}

rollback_node() {
    local node="$1" status="$2"
    warn "Rolling back: $node (status: $status)"
    local stage_file
    stage_file=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('file',''))" 2>/dev/null)
    [[ -z "$stage_file" ]] && { err "Unknown stage for $node"; return 1; }
    local rollback_func="rollback_${node}"
    if declare -f "$rollback_func" &>/dev/null; then
        "$rollback_func" || warn "Rollback failed"
    fi
    python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json','r+') as f:
    s=json.load(f)
    if '${node}' in s['nodes']:
        s['nodes']['${node}']['status']='rolled_back'
        s['nodes']['${node}']['rolled_at']='$(date -Iseconds)'
f.seek(0); json.dump(s,f); f.truncate()
PYEOF
}

run_node() {
    local node="$1" exit_code=0
    local stage_file name timeout rollback_enabled
    stage_file=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('file',''))" 2>/dev/null)
    name=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('name',''))" 2>/dev/null)
    timeout=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('timeout',300))" 2>/dev/null)
    rollback_enabled=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('rollback',True))" 2>/dev/null)
    [[ -z "$stage_file" ]] && { err "run_node: unknown file for $node"; return 1; }
    [[ ! -f "${STAGES_DIR}/${stage_file}" ]] && { err "run_node: file not found: ${STAGES_DIR}/${stage_file}"; return 1; }
    local current_status
    current_status=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/state.json')); print(d.get('nodes',{}).get('${node}',{}).get('status','pending'))" 2>/dev/null)
    if [[ "$current_status" == "success" ]]; then
        ok "[$node] Already succeeded - skipping"; trace "skip" "$node" "already success"; return 0
    fi
    python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json','r+') as f:
    s=json.load(f)
    s['nodes']['${node}']['status']='running'
    s['nodes']['${node}']['started_at']='$(date -Iseconds)'
f.seek(0); json.dump(s,f); f.truncate()
PYEOF
    trace "start" "$node" "stage started"
    step "$name" "${node%%_*}"
    local start_time=$(date +%s)
    local run_rc=0
    timeout "${TIMEOUT_SCALE}" "${timeout}" bash "${STAGES_DIR}/${stage_file}" 2>&1 || run_rc=$?
    local duration=$(( $(date +%s) - start_time ))
    if [[ $run_rc -eq 0 ]]; then
        save_checkpoint "$node"
        python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json','r+') as f:
    s=json.load(f)
    s['nodes']['${node}']['status']='success'
    s['nodes']['${node}']['duration']=${duration}
    s['nodes']['${node}']['completed_at']='$(date -Iseconds)'
f.seek(0); json.dump(s,f); f.truncate()
PYEOF
        trace "success" "$node" "stage completed" "$duration"
        ok "[$node] Success (${duration}s)"
    else
        trace "fail" "$node" "stage failed (rc=$run_rc)" "$duration"
        python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json','r+') as f:
    s=json.load(f)
    s['nodes']['${node}']['status']='failed'
    s['nodes']['${node}']['exit_code']=${run_rc}
    s['nodes']['${node}']['failed_at']='$(date -Iseconds)'
f.seek(0); json.dump(s,f); f.truncate()
PYEOF
        if [[ "${ROLLBACK_ON_ERROR}" == "1" && "${rollback_enabled}" != "False" ]]; then
            rollback_node "$node"
        fi
        err "[$node] Failed (exit code: $run_rc)"
        exit_code=1
    fi
    return $exit_code
}

run_level() {
    local level_idx="$1"; shift
    local node_ids=("$@")
    info "Level ${level_idx}: running ${#node_ids[@]} nodes..."
    local pids=() failed=0
    for node in "${node_ids[@]}"; do
        (run_node "$node") &
        pids+=($!)
    done
    local i
    for i in "${!pids[@]}"; do
        wait "${pids[$i]}" || ((failed++)) || true
    done
    [[ $failed -gt 0 ]] && err "${failed}/${#node_ids[@]} nodes in level ${level_idx} failed" && return 1
    ok "Level ${level_idx}: all ${#node_ids[@]} nodes succeeded"
    return 0
}

execute_plan() {
    local plan_file="${STATE_DIR}/execution-plan.json"
    log "Starting execution from plan: $plan_file"
    ensure_dir "$(dirname "$TRACE_FILE")"
    python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json','r+') as f:
    s=json.load(f)
    s['status']='running'
    s['started_at']='$(date -Iseconds)'
f.seek(0); json.dump(s,f); f.truncate()
PYEOF
    local plan_json=$(cat "$plan_file")
    local total_levels=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_levels'])" 2>/dev/null)
    local total_stages=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_stages'])" 2>/dev/null)
    info "Plan: ${total_stages} stages / ${total_levels} levels"
    local failed=0
    for ((l=0; l<total_levels; l++)); do
        local nodes_at_level=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); lvl=d['graph']['levels'][${l}]; print([n['id'] for n in lvl])" 2>/dev/null)
        local node_array=$(echo "$nodes_at_level" | python3 -c "import json,sys; lst=json.load(sys.stdin); print(' '.join(lst))" 2>/dev/null)
        local -a node_ids_arr; read -ra node_ids_arr <<< "$node_array"
        [[ ${#node_ids_arr[@]} -eq 0 ]] && continue
        if ! run_level $((l+1)) "${node_ids_arr[@]}"; then failed=1; break; fi
    done
    return $failed
}

export -f run_node run_level execute_plan save_checkpoint rollback_node