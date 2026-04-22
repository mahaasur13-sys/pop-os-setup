#!/usr/bin/env bash
#=================================================================
# observability/event_bus.sh — In-process event bus (v9.5)
#=================================================================
# Fan-out events to multiple handlers (stdout, file, metrics, hooks)
#=================================================================

[[ -n "${_OBS_EVENTBUS_SOURCED:-}" ]] && return 0 || _OBS_EVENTBUS_SOURCED=1

# ─── Bus Configuration ──────────────────────────────────────────
_EVENT_BUS_ENABLED="${EVENT_BUS_ENABLED:-1}"
declare -a _BUS_HANDLERS=()
declare -a _BUS_HOOKS_STAGE_START=()
declare -a _BUS_HOOKS_STAGE_SUCCESS=()
declare -a _BUS_HOOKS_STAGE_ERROR=()
declare -a _BUS_HOOKS_PIPELINE_START=()
declare -a _BUS_HOOKS_PIPELINE_END=()

# ─── Register handler ───────────────────────────────────────────
# register_event_handler <name> <script_path>
register_event_handler() {
    local name="$1"; local script="$2"
    if [[ -f "$script" ]]; then
        _BUS_HANDLERS+=("$name:$script")
        trace_debug "bus.register" "" "Event handler registered: $name"
    fi
}

# ─── Register lifecycle hooks ──────────────────────────────────
# register_hook <event_type> <function_name>
register_hook() {
    local event_type="$1"; local func="$2"
    case "$event_type" in
        stage.start)    _BUS_HOOKS_STAGE_START+=("$func") ;;
        stage.success)  _BUS_HOOKS_STAGE_SUCCESS+=("$func") ;;
        stage.error)   _BUS_HOOKS_STAGE_ERROR+=("$func") ;;
        pipeline.start) _BUS_HOOKS_PIPELINE_START+=("$func") ;;
        pipeline.end)   _BUS_HOOKS_PIPELINE_END+=("$func") ;;
    esac
}

# ─── Dispatch to handlers ─────────────────────────────────────
# _bus_dispatch <json_event>
_bus_dispatch() {
    local event="$1"

    # Dispatch to registered shell handlers
    for entry in "${_BUS_HANDLERS[@]}"; do
        local name="${entry%%:*}"
        local script="${entry#*:}"
        # Run handler in subshell (non-blocking)
        (
            source "$script" 2>/dev/null
            bus_handle_event "$event" 2>/dev/null
        ) &
    done

    # Dispatch to shell function hooks
    local event_type
    event_type="$(printf '%s' "$event" | grep -o '"event":"[^"]*"' | cut -d'"' -f4)"

    case "$event_type" in
        stage.start)
            for hook in "${_BUS_HOOKS_STAGE_START[@]}"; do
                "$hook" "$event" 2>/dev/null &
            done ;;
        stage.success)
            for hook in "${_BUS_HOOKS_STAGE_SUCCESS[@]}"; do
                "$hook" "$event" 2>/dev/null &
            done ;;
        stage.error)
            for hook in "${_BUS_HOOKS_STAGE_ERROR[@]}"; do
                "$hook" "$event" 2>/dev/null &
            done ;;
        pipeline.start)
            for hook in "${_BUS_HOOKS_PIPELINE_START[@]}"; do
                "$hook" "$event" 2>/dev/null &
            done ;;
        pipeline.end)
            for hook in "${_BUS_HOOKS_PIPELINE_END[@]}"; do
                "$hook" "$event" 2>/dev/null &
            done ;;
    esac
}

# ─── Emit via bus ──────────────────────────────────────────────
bus_emit() {
    local level="$1"; shift
    local event_type="$1"; shift
    local stage_id="$1"; shift
    local message="$1"; shift

    # Build full JSON event
    local ts fingerprint event_id
    ts="$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')"
    fingerprint="$(printf '%s' "$TRACE_RUN_ID$stage_id$event_type$message" | sha256sum 2>/dev/null | awk '{print $1}' | cut -c1-16)"
    event_id="$(generate_event_id)"

    local extras=""
    for pair in "$@"; do
        local key="${pair%%=*}"
        local val="${pair#*=}"
        extras="${extras},\"$(json_escape "$key")\":\"$(json_escape "$val")\""
    done

    local payload
    payload="$(printf '{"ts":"%s","level":"%s","event":"%s","run_id":"%s","stage_id":"%s","event_id":"%s","fingerprint":"%s","message":"%s"%s}' \
        "$(json_escape "$ts")" \
        "$(json_escape "$level")" \
        "$(json_escape "$event_type")" \
        "$(json_escape "$TRACE_RUN_ID")" \
        "$(json_escape "$stage_id")" \
        "$(json_escape "$event_id")" \
        "$(json_escape "$fingerprint")" \
        "$(json_escape "$message")" \
        "${extras}")"

    # Write to trace file
    if [[ -n "$TRACE_FILE" ]]; then
        echo "$payload" >> "$TRACE_FILE" 2>/dev/null || true
    fi

    # Write to stdout (always for events)
    printf '%s\n' "$payload"

    # Fan-out to handlers
    [[ "$_EVENT_BUS_ENABLED" == "1" ]] && _bus_dispatch "$payload"
}

export -f register_event_handler register_hook bus_emit
