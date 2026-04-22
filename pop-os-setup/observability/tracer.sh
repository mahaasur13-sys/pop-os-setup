#!/usr/bin/env bash
#=================================================================
# observability/tracer.sh — Trace context + event emission (v9.5)
#=================================================================
# Every event carries: run_id, stage_id, event_id, fingerprint
# Emit to: stdout (TTY) + JSONL trace file
#=================================================================

[[ -n "${_OBS_TRACER_SOURCED:-}" ]] && return 0 || _OBS_TRACER_SOURCED=1

TRACE_RUN_ID="${TRACE_RUN_ID:-}"
TRACE_ENABLED="${TRACE_ENABLED:-1}"
TRACE_FILE="${TRACE_FILE:-}"
TRACE_LEVEL="${TRACE_LEVEL:-info}"
_OBS_EVENT_COUNT=0

generate_event_id() {
    printf '%s-%s-%04x-%04x-%012x' \
        "${RANDOM}${RANDOM}" \
        "${RANDOM}" \
        $((RANDOM & 0x0fff | 0x4000)) \
        $((RANDOM & 0x3fff | 0x8000)) \
        $((RANDOM * RANDOM + RANDOM))
}

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

generate_fingerprint() {
    local input="$1"
    if command -v sha256sum &>/dev/null; then
        printf '%s' "$input" | sha256sum | awk '{print $1}' | cut -c1-16
    else
        printf '%s' "$input" | sum | awk '{print $1}'
    fi
}

trace_ts() { date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z'; }

_trace_level_to_num() {
    case "$1" in
        debug)   echo 0 ;;
        info)    echo 1 ;;
        warn)    echo 2 ;;
        error)   echo 3 ;;
        critical) echo 4 ;;
        *)       echo 1 ;;
    esac
}

_is_level_enabled() {
    local ev="$1" mi="$TRACE_LEVEL"
    [[ $(_trace_level_to_num "$ev") -ge $(_trace_level_to_num "$mi") ]]
}

emit_event() {
    local level="$1" etype="$2" sid="${3:-}" msg="${4:-}"; shift 4

    [[ "$TRACE_ENABLED" != "1" ]] && return 0
    _is_level_enabled "$level" || return 0

    local eid fp ts
    eid="$(generate_event_id)"
    fp="$(generate_fingerprint "${TRACE_RUN_ID}${sid}${etype}${msg}")"
    ts="$(trace_ts)"
    ((_OBS_EVENT_COUNT++)) || true

    local p="{\"ts\":\"$(json_escape "$ts")\",\"level\":\"$(json_escape "$level")\",\"event\":\"$(json_escape "$etype")\",\"run_id\":\"$(json_escape "$TRACE_RUN_ID")\",\"stage_id\":\"$(json_escape "$sid")\",\"event_id\":\"$(json_escape "$eid")\",\"fingerprint\":\"$(json_escape "$fp")\",\"message\":\"$(json_escape "$msg")\""

    local extra=""
    for pair in "$@"; do
        local k="${pair%%=*}" v="${pair#*=}"
        extra="${extra},\"$(json_escape "$k")\":\"$(json_escape "$v")\""
    done

    if [[ -n "$extra" ]]; then
        p="${p}${extra}}"
    else
        p="${p}}"
    fi

    [[ -n "$TRACE_FILE" ]] && echo "$p" >> "$TRACE_FILE" 2>/dev/null || true

    if [[ -t 1 || "$level" == "error" || "$level" == "critical" || "$TRACE_LEVEL" == "debug" ]]; then
        printf '%s\n' "$p"
    fi
}

trace_debug()   { emit_event "debug"    "$1" "$2" "$3" "${@:4}"; }
trace_info()    { emit_event "info"     "$1" "$2" "$3" "${@:4}"; }
trace_warn()    { emit_event "warn"     "$1" "$2" "$3" "${@:4}"; }
trace_error()   { emit_event "error"    "$1" "$2" "$3" "${@:4}"; }
trace_critical(){ emit_event "critical" "$1" "$2" "$3" "${@:4}"; }

trace_pipeline_start() {
    trace_info "pipeline.start" "root" "Pipeline starting" \
        "profile=$1" "total_stages=${TOTAL_STAGES:-unknown}" \
        "arch=$(uname -m)" "os=$(detect_os 2>/dev/null || echo unknown)"
}

trace_pipeline_end() {
    trace_info "pipeline.end" "root" "Pipeline finished" \
        "exit_code=$1" "duration_ms=$2" "event_count=${_OBS_EVENT_COUNT:-0}"
}

trace_stage_start() {
    trace_info "stage.start" "s$1" "Stage $1 started: $2"
}

trace_stage_output() {
    trace_info "stage.output" "s$1" "$3" "stage_name=$2"
}

trace_stage_progress() {
    trace_info "stage.progress" "s$1" "$4" "stage_name=$2" "progress_pct=$3"
}

trace_stage_success() {
    trace_info "stage.success" "s$1" "Stage $1 succeeded: $2" "stage_name=$2" "duration_ms=$3"
}

trace_stage_error() {
    trace_error "stage.error" "s$1" "Stage $1 FAILED: $2" "stage_name=$2" "error_msg=$3" "stderr=$(json_escape "${4:-}")"
}

trace_stage_retry() {
    trace_warn "stage.retry" "s$1" "Stage $1 retry $3: $2" "stage_name=$2" "retry_attempt=$3"
}

trace_stage_skip() {
    trace_info "stage.skip" "s$1" "Stage $1 skipped: $2" "stage_name=$2" "skip_reason=$3"
}

trace_checkpoint_save() {
    trace_info "checkpoint.save" "s$1" "Checkpoint saved: $2" "checkpoint_id=$2" "state_path=$3"
}

trace_rollback_trigger() {
    trace_error "rollback.trigger" "s$1" "Rollback triggered: $2" "trigger_reason=$2" "checkpoint_id=$3"
}

trace_init() {
    TRACE_RUN_ID="$1"
    TRACE_FILE="$2"
    [[ -n "$TRACE_FILE" ]] && mkdir -p "$(dirname "$TRACE_FILE")" 2>/dev/null || true
}

export -f emit_event trace_debug trace_info trace_warn trace_error trace_critical
export -f trace_pipeline_start trace_pipeline_end
export -f trace_stage_start trace_stage_output trace_stage_progress
export -f trace_stage_success trace_stage_error trace_stage_retry trace_stage_skip
export -f trace_checkpoint_save trace_rollback_trigger trace_init
export TRACE_RUN_ID TRACE_ENABLED TRACE_FILE TRACE_LEVEL