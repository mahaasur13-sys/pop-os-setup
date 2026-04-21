#!/bin/bash
#===============================================================================
# engine/runtime.sh — v5.0.0 State-Aware DAG Runtime Engine
# Executes execution-plan.json with parallel-safe level groups,
# checkpoint/commit/rollback per node, state machine transitions
#===============================================================================

[[ -z "${_ENGINE_SOURCED:-}" ]] && { _ENGINE_SOURCED=1; } || return 0

# ─── INCLUDE DEPENDENCIES ──────────────────────────────────────────────────────
source "${LIBDIR}/_dag.sh"
source "${LIBDIR}/_state.sh"
source "${LIBDIR}/_path.sh"

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MAX_PARALLEL="${MAX_PARALLEL:-4}"
TIMEOUT_SCALE="${TIMEOUT_SCALE:-1}"
ROLLBACK_ON_ERROR="${ROLLBACK_ON_ERROR:-1}"
CHECKPOINT_DIR="${STATE_DIR}/checkpoints"
TRACE_FILE="${STATE_DIR}/traces/${RUN_ID}.jsonl"

# ─── LOGGING ─────────────────────────────────────────────────────────────────
trace() {
    # JSONL trace: {ts, level, node, msg, duration}
    local level="$1" node="$2" msg="$3" dur="${4:-null}"
    echo "{\"ts\":\"$(date -Iseconds)\",\"level\":\"$level\",\"node\":\"$node\",\"msg\":$(python3 -c "import json; print(json.dumps(\"$msg\"))")}"}${dur:+, \"duration\":$dur}" >> "$TRACE_FILE"
}

# ─── CHECKPOINT ──────────────────────────────────────────────────────────────
save_checkpoint() {
    local node="$1"
    local check_file="${CHECKPOINT_DIR}/${node}.json"
    ensure_dir "$(dirname "$check_file")"

    local timestamp
    timestamp=$(date -Iseconds)

    python3 - << PYEOF
import json, os
state = json.load(open('${STATE_DIR}/state.json'))
state['nodes']['${node}']['checkpoint'] = '${timestamp}'
state['nodes']['${node}']['status'] = 'checkpoint'
with open('${CHECKPOINT_DIR}/${node}.json', 'w') as f:
    json.dump(state['nodes']['${node}'], f, indent=2)
PYEOF
    ok "Checkpoint saved: $node @ ${timestamp}"
}

# ─── ROLLBACK ───────────────────────────────────────────────────────────────
rollback_node() {
    local node="$1" status="$2"
    warn "Rolling back: $node (status: $status)"

    local stage_file
    stage_file=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('file',''))" 2>/dev/null)

    if [[ -z "$stage_file" ]]; then
        err "Cannot rollback: unknown stage file for node $node"
        return 1
    fi

    # Call stage-rolled-back function if exists
    local rollback_func="rollback_${node}"
    if declare -f "$rollback_func" &>/dev/null; then
        log "Executing rollback: $rollback_func"
        "$rollback_func" || warn "Rollback function returned non-zero"
    else
        # Fallback: run stage with SKIP mode
        warn "No rollback function — re-running with skip on success"
        SKIP_MODE=1 RUN_MODE=rollback "${STAGES_DIR}/${stage_file}" 2>/dev/null || true
    fi

    python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json', 'r+') as f:
    state = json.load(f)
    if '${node}' in state['nodes']:
        state['nodes']['${node}']['status'] = 'rolled_back'
        state['nodes']['${node}']['rolled_at'] = '$(date -Iseconds)'
f.seek(0); json.dump(state, f, indent=2); f.truncate()
PYEOF

    ok "Rollback complete: $node"
    return 0
}

# ─── RUN SINGLE NODE ──────────────────────────────────────────────────────────
run_node() {
    local node="$1"
    local exit_code=0

    local stage_file name timeout rollback_enabled
    stage_file=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('file',''))" 2>/dev/null)
    name=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('name',''))" 2>/dev/null)
    timeout=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('timeout',300))" 2>/dev/null)
    rollback_enabled=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/execution-plan.json')); n=next(x for x in d['graph']['nodes'] if x['id']=='${node}'); print(n.get('rollback',True))" 2>/dev/null)

    [[ -z "$stage_file" ]] && { err "run_node: unknown file for $node"; return 1; }
    [[ ! -f "${STAGES_DIR}/${stage_file}" ]] && { err "run_node: file not found: ${STAGES_DIR}/${stage_file}"; return 1; }

    # State: already success?
    local current_status
    current_status=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/state.json')); print(d.get('nodes',{}).get('${node}',{}).get('status','pending'))" 2>/dev/null)
    if [[ "$current_status" == "success" ]]; then
        ok "[$node] Already succeeded — skipping"
        trace "skip" "$node" "already success"
        return 0
    fi

    # State: checkpoint → resume?
    if [[ "$current_status" == "checkpoint" ]]; then
        info "[$node] Checkpoint found — resuming from saved state"
    fi

    # Update state: RUNNING
    python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json', 'r+') as f:
    state = json.load(f)
    state['nodes']['${node}']['status'] = 'running'
    state['nodes']['${node}']['started_at'] = '$(date -Iseconds)'
f.seek(0); json.dump(state, f, indent=2); f.truncate()
PYEOF

    trace "start" "$node" "stage started"
    step "$name" "${node%%_*}"

    # Execute with timeout
    local start_time
    start_time=$(date +%s)

    local run_rc=0
    timeout "${TIMEOUT_SCALE}" "${timeout}" bash "${STAGES_DIR}/${stage_file}" 2>&1 || run_rc=$?

    local duration=$(( $(date +%s) - start_time ))

    if [[ $run_rc -eq 0 ]]; then
        # Success: checkpoint → commit
        save_checkpoint "$node"
        python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json', 'r+') as f:
    state = json.load(f)
    state['nodes']['${node}']['status'] = 'success'
    state['nodes']['${node}']['duration'] = ${duration}
    state['nodes']['${node}']['completed_at'] = '$(date -Iseconds)'
f.seek(0); json.dump(state, f, indent=2); f.truncate()
PYEOF
        trace "success" "$node" "stage completed" "$duration"
        ok "[$node] Success (${duration}s)"
    else
        # Failure: rollback
        trace "fail" "$node" "stage failed (rc=$run_rc)" "$duration"
        python3 - << PYEOF
import json
with open('${STATE_DIR}/state.json', 'r+') as f:
    state = json.load(f)
    state['nodes']['${node}']['status'] = 'failed'
    state['nodes']['${node}']['exit_code'] = ${run_rc}
    state['nodes']['${node}']['failed_at'] = '$(date -Iseconds)'
f.seek(0); json.dump(state, f, indent=2); f.truncate()
PYEOF

        if [[ "${ROLLBACK_ON_ERROR}" == "1" && "${rollback_enabled}" != "False" ]]; then
            rollback_node "$node"
        fi

        err "[$node] Failed (exit code: $run_rc)"
        exit_code=1
    fi

    return $exit_code
}

# ─── RUN LEVEL (parallel-safe) ───────────────────────────────────────────────
run_level() {
    local level_idx="$1"
    shift
    local node_ids=("$@")

    info "Level ${level_idx}: running ${#node_ids[@]} nodes..."

    local pids=()
    local results=()
    local failed=0

    for node in "${node_ids[@]}"; do
        (
            run_node "$node"
        ) &
        pids+=($!)
        results+=($!)
    done

    # Wait for all in parallel group
    local i
    for i in "${!pids[@]}"; do
        wait "${pids[$i]}" || ((failed++)) || true
    done

    if [[ $failed -gt 0 ]]; then
        err "${failed}/${#node_ids[@]} nodes in level ${level_idx} failed"
        return 1
    fi

    ok "Level ${level_idx}: all ${#node_ids[@]} nodes succeeded"
    return 0
}

# ─── EXECUTE PLAN ──────────────────────────────────────────────────────────────
execute_plan() {
    local plan_file="${STATE_DIR}/execution-plan.json"

    log "Starting execution from plan: $plan_file"

    ensure_dir "$(dirname "$TRACE_FILE")"
    trace "engine" "system" "execution_started"

    python3 - << 'PYEOF'
import json
with open('${STATE_DIR}/state.json', 'r+') as f:
    state = json.load(f)
    state['status'] = 'running'
    state['started_at'] = '$(date -Iseconds)'
f.seek(0); json.dump(state, f, indent=2); f.truncate()
PYEOF

    local plan_json
    plan_json=$(cat "$plan_file")
    local total_levels
    total_levels=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_levels'])" 2>/dev/null)
    local total_stages
    total_stages=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_stages'])" 2>/dev/null)

    info "Plan: ${total_stages} stages / ${total_levels} levels"

    local level_idx=0
    local failed=0

    for ((l=0; l<total_levels; l++)); do
        level_idx=$((l + 1))

        local nodes_at_level
        nodes_at_level=$(echo "$plan_json" | python3 -c "import json,sys; d=json.load(sys.stdin); lvl=d['graph']['levels'][${l}]; print([n['id'] for n in lvl])" 2>/dev/null)

        # Convert Python list to bash array
        local node_array
        node_array=$(echo "$nodes_at_level" | python3 -c "import json,sys; lst=json.load(sys.stdin); print(' '.join(lst))" 2>/dev/null)

        local -a node_ids_arr
        read -ra node_ids_arr <<< "$node_array"

        if [[ ${#node_ids_arr[@]} -eq 0 ]]; then
            continue
        fi

        if ! run_level "$level_idx" "${node_ids_arr[@]}"; then
            failed=1
            break
        fi
    done

    trace "engine" "system" "execution_${failed:-0}"
    return $failed
}

export -f run_node run_level execute_plan save_checkpoint rollback_node