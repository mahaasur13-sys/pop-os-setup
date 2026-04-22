#!/usr/bin/env bash
#===================================
# lib/observability.sh — v9.4
# Observability layer: no silent execution
#===================================

# ─── Emit event to stdout + JSONL ────────────────────────────────────────────
# obs_emit <event_type> <message> [key=value ...]
obs_emit() {
    local event_type="$1"
    local message="$2"
    shift 2
    local run_id="${RUN_ID:-unknown}"
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local stage="${CURRENT_STAGE:-none}"

    # Build JSON payload
    local json="{\"type\":\"$event_type\",\"run_id\":\"$run_id\",\"stage\":\"$stage\",\"timestamp\":\"$ts\",\"message\":\"$message\""
    while [[ $# -gt 0 ]]; do
        local key="${1%%=*}"
        local val="${1#*=}"
        json+=",\"$key\":\"$val\""
        shift
    done
    json+="}"

    # stdout output — human readable with prefix
    echo -e "[\033[1;36mOBS\033[0m] [$event_type] $message"

    # Append to JSONL trace file if available
    if [[ -n "${OBS_TRACE_FILE:-}" ]]; then
        echo "$json" >> "$OBS_TRACE_FILE"
    fi
}

# ─── Live progress bar ─────────────────────────────────────────────────────────
# obs_progress <current> <total> <label>
obs_progress() {
    local cur="$1"
    local total="$2"
    local label="${3:-progress}"
    local pct=$((cur * 100 / total))
    local filled=$((cur * 40 / total))
    local empty=$((40 - filled))
    printf "\r  %-30s [%s%s] %3d%%" "$label" \
        "$(printf '#%.0s' $(seq 1 $filled 2>/dev/null))" \
        "$(printf '.%.0s' $(seq 1 $empty 2>/dev/null))" \
        "$pct"
    if [[ $cur -eq $total ]]; then
        echo ""
    fi
}

# ─── Emit stage enter/exit ─────────────────────────────────────────────────────
# obs_stage_begin <stage_num> <stage_name> <total_stages>
obs_stage_begin() {
    local num="$1"
    local name="$2"
    local total="$3"
    local run_id="${RUN_ID:-unknown}"
    obs_emit "stage_begin" "Stage $num/$total: $name" \
        stage_num="$num" stage_name="$name" total_stages="$total"
    echo ""
    echo -e "\033[1;35m═══ Stage $num/$total: ${name} ═══\033[0m"
}

obs_stage_end() {
    local num="$1"
    local name="$2"
    local status="$3"  # success|failure|skipped
    obs_emit "stage_end" "Stage $num complete: $name ($status)" \
        stage_num="$num" stage_name="$name" status="$status" \
        duration_seconds="${STAGE_START_TIME:-0}"
}

# ─── Emit operation with timing ────────────────────────────────────────────────
obs_op_begin() {
    local op="$1"
    local target="${2:-}"
    obs_emit "op_begin" "$op" operation="$op" target="$target"
    STAGE_START_TIME=$(date +%s)
}

obs_op_end() {
    local op="$1"
    local status="$2"  # ok|fail|skip
    local duration=0
    if [[ -n "${STAGE_START_TIME:-}" ]]; then
        duration=$(( $(date +%s) - STAGE_START_TIME ))
    fi
    obs_emit "op_end" "$op ($status, ${duration}s)" \
        operation="$op" status="$status" duration_seconds="$duration"
}

# ─── Emit metric ──────────────────────────────────────────────────────────────
# obs_metric <name> <value> [unit]
obs_metric() {
    local name="$1"
    local value="$2"
    local unit="${3:-}"
    obs_emit "metric" "$name=$value${unit:+ $unit}" \
        metric_name="$name" metric_value="$value" metric_unit="$unit"
}

# ─── Emit warning ─────────────────────────────────────────────────────────────
obs_warn() {
    obs_emit "warning" "$1" source="${CURRENT_STAGE:-unknown}"
}

# ─── Emit error ───────────────────────────────────────────────────────────────
obs_err() {
    obs_emit "error" "$1" source="${CURRENT_STAGE:-unknown}"
}

# ─── Observability init ───────────────────────────────────────────────────────
# obs_init <run_id> — set up trace file
obs_init() {
    local run_id="${1:-$(date +%s)-$$}"
    export OBS_TRACE_FILE="${STATE_DIR}/obs_${run_id}.jsonl"
    export RUN_ID="$run_id"
    obs_emit "run_started" "pop-os-setup v${RUNTIME_VERSION:-unknown} started" \
        run_id="$run_id" pid="$$" hostname="$(hostname)"
}

# ─── Emit run summary ─────────────────────────────────────────────────────────
obs_summary() {
    local status="$1"
    local stages_run="$2"
    local stages_skipped="$3"
    local stages_failed="$4"
    local duration="$5"

    obs_emit "run_summary" "Run complete: $status" \
        status="$status" stages_run="$stages_run" \
        stages_skipped="$stages_skipped" stages_failed="$stages_failed" \
        duration_seconds="$duration" \
        exit_code="${EXIT_CODE:-0}"

    echo ""
    echo "════════════════════════════════════"
    echo -e "  \033[1;37mRun Summary\033[0m"
    echo "════════════════════════════════════"
    echo "  Run ID:      ${RUN_ID:-unknown}"
    echo "  Version:     ${RUNTIME_VERSION:-unknown}"
    echo "  Duration:    ${duration}s"
    echo "  Status:      $status"
    echo "  Stages run:  $stages_run"
    echo "  Stages skip: $stages_skipped"
    echo "  Stages fail: $stages_failed"
    echo "  Trace file: ${OBS_TRACE_FILE:-none}"
    echo "════════════════════════════════════"
}