#!/usr/bin/env bash
#=================================================================
# observability/metrics.sh — Metrics collector + exporter (v9.5)
#=================================================================
# Exposes: stage_duration_ms, total_pipeline_time, retry_count,
#          rollback_count, failure_rate
#=================================================================

[[ -n "${_OBS_METRICS_SOURCED:-}" ]] && return 0 || _OBS_METRICS_SOURCED=1

# ─── Metric Store ────────────────────────────────────────────────
declare -A _METRICS=()
declare -A _STAGE_START_TIMES=()
declare -A _STAGE_DURATIONS=()
declare -A _STAGE_OUTCOMES=()

# Counters
_METRICS[retry_count]=0
_METRICS[rollback_count]=0
_METRICS[failure_count]=0
_METRICS[success_count]=0
_METRICS[skip_count]=0
_METRICS[checkpoint_count]=0

# Gauge
_METRICS[current_stage]=0
_METRICS[total_stages]=0
_METRICS[stages_completed]=0

# Timing
_METRICS[pipeline_start_ms]=0
_METRICS[pipeline_end_ms]=0

# ─── Record pipeline start ────────────────────────────────────────
metrics_pipeline_start() {
    _METRICS[pipeline_start_ms]=$(($(date +%s%3N)))
    _METRICS[current_stage]=0
    _METRICS[stages_completed]=0
    _METRICS[retry_count]=0
    _METRICS[rollback_count]=0
    _METRICS[failure_count]=0
    _METRICS[success_count]=0
    _METRICS[skip_count]=0
}

# ─── Record stage timing ─────────────────────────────────────────
metrics_stage_begin() {
    local stage_num="$1"; local stage_name="$2"
    _STAGE_START_TIMES[$stage_num]=$(($(date +%s%3N)))
    _STAGE_OUTCOMES[$stage_num]="pending"
    _METRICS[current_stage]=$stage_num
}

metrics_stage_end() {
    local stage_num="$1"; local stage_name="$2"; local status="$3"
    local start_ms="${_STAGE_START_TIMES[$stage_num]:-0}"
    local end_ms
    end_ms=$(($(date +%s%3N)))
    local duration_ms=$((end_ms - start_ms))

    _STAGE_DURATIONS[$stage_num]=$duration_ms
    _STAGE_OUTCOMES[$stage_num]="$status"

    case "$status" in
        success) ((_METRICS[success_count]++)) ;;
        failed)  ((_METRICS[failure_count]++)) ;;
        skipped) ((_METRICS[skip_count]++)) ;;
    esac

    ((_METRICS[stages_completed]++))
}

# ─── Increment counters ──────────────────────────────────────────
metrics_inc() {
    local name="$1"; local delta="${2:-1}"
    _METRICS[$name]=$((${_METRICS[$name]:-0} + delta))
}

# ─── Record retry ────────────────────────────────────────────────
metrics_retry() {
    local stage_num="$1"; local stage_name="$2"; local attempt="$3"
    metrics_inc "retry_count"
    metrics_inc "stage_${stage_num}_retries"
}

# ─── Record rollback ─────────────────────────────────────────────
metrics_rollback() {
    local stage_num="$1"; local stage_name="$2"
    metrics_inc "rollback_count"
    metrics_inc "stage_${stage_num}_rollbacks"
    trace_warn "rollback.recorded" "s${stage_num}" \
        "Rollback recorded for stage ${stage_num}" \
        "stage_name=${stage_name}" "rollback_count=${_METRICS[rollback_count]}"
}

# ─── Record checkpoint ────────────────────────────────────────────
metrics_checkpoint() {
    local stage_num="$1"; local checkpoint_id="$2"
    metrics_inc "checkpoint_count"
}

# ─── Export to JSON ──────────────────────────────────────────────
metrics_to_json() {
    local metrics_file="${1:-${STATE_DIR:-$HOME/.local/state/pop-os-setup}/metrics.json}"
    local end_ms
    end_ms=$(($(date +%s%3N)))
    local total_ms=$((end_ms - ${_METRICS[pipeline_start_ms]:-end_ms}))
    local total_stages=${_METRICS[total_stages]:-0}
    local completed=${_METRICS[stages_completed]:-0}
    local failures=${_METRICS[failure_count]:-0}
    local rate="0.000"
    if ((completed > 0)); then
        rate="$(printf '%.3f' "$(echo "scale=4; $failures / $completed" | bc -l 2>/dev/null || echo "0")")"
    fi

    # Stage durations JSON array
    local durations_json="["
    local first=1
    for i in $(seq 1 ${_METRICS[total_stages]:-0}); do
        [[ $first -eq 0 ]] && durations_json+=","
        first=0
        durations_json+="{\"stage\":$i,\"duration_ms\":${_STAGE_DURATIONS[$i]:-0},\"outcome\":\"${_STAGE_OUTCOMES[$i]:-unknown}\"}"
    done
    durations_json+="]"

    cat > "$metrics_file" << METEOF
{
  "run_id": "${TRACE_RUN_ID:-unknown}",
  "generated_at": "$(date -Iseconds)",
  "pipeline": {
    "total_ms": ${total_ms},
    "total_stages": ${total_stages},
    "stages_completed": ${completed},
    "success_count": ${_METRICS[success_count]:-0},
    "failure_count": ${failures},
    "skip_count": ${_METRICS[skip_count]:-0},
    "failure_rate": ${rate}
  },
  "counters": {
    "retry_count": ${_METRICS[retry_count]:-0},
    "rollback_count": ${_METRICS[rollback_count]:-0},
    "checkpoint_count": ${_METRICS[checkpoint_count]:-0}
  },
  "stages": ${durations_json}
}
METEOF
    echo "$metrics_file"
}

# ─── Prometheus-style output ─────────────────────────────────────
metrics_prom_text() {
    cat << PROMEOF
# HELP popos_pipeline_duration_ms Total pipeline execution time in milliseconds
# TYPE popos_pipeline_duration_ms gauge
popos_pipeline_duration_ms $((${_METRICS[pipeline_end_ms]:-0} - ${_METRICS[pipeline_start_ms]:-0}))

# HELP popos_pipeline_stages_total Total number of stages
# TYPE popos_pipeline_stages_total gauge
popos_pipeline_stages_total ${_METRICS[total_stages]:-0}

# HELP popos_pipeline_stages_completed Number of completed stages
# TYPE popos_pipeline_stages_completed gauge
popos_pipeline_stages_completed ${_METRICS[stages_completed]:-0}

# HELP popos_stage_duration_ms Stage execution time in milliseconds
# TYPE popos_stage_duration_ms gauge
PROMEOF
    for i in $(seq 1 ${_METRICS[total_stages]:-0}); do
        echo "popos_stage_duration_ms{stage=\"$i\",outcome=\"${_STAGE_OUTCOMES[$i]:-unknown}\"} ${_STAGE_DURATIONS[$i]:-0}"
    done
}

export -f metrics_pipeline_start metrics_stage_begin metrics_stage_end
export -f metrics_inc metrics_retry metrics_rollback metrics_checkpoint
export -f metrics_to_json metrics_prom_text
