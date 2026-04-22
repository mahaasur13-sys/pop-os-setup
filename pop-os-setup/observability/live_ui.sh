#!/usr/bin/env bash
#=================================================================
# observability/live_ui.sh — Real-time TTY progress display (v9.5)
#=================================================================
# Features:
#   • Stage progress bar
#   • Live log streaming
#   • Error highlighting
#   • Current stage pointer
#=================================================================

[[ -n "${_OBS_LIVEUI_SOURCED:-}" ]] && return 0 || _OBS_LIVEUI_SOURCED=1

# ─── State ────────────────────────────────────────────────────────
_LIVEUI_ENABLED=0
_LIVEUI_CLEARED=0
_LIVEUI_LAST_LINE=""
_LIVEUI_ERRORS=()
_LIVEUI_STAGE_START_MS=0

# ─── Init ────────────────────────────────────────────────────────
liveui_init() {
    [[ -t 1 ]] && _LIVEUI_ENABLED=1 || _LIVEUI_ENABLED=0
}

# ─── Draw progress bar ───────────────────────────────────────────
_liveui_progress_bar() {
    local pct="$1"; local width="${2:-32}"
    local filled=$((width * pct / 100))
    local empty=$((width - filled))
    printf '█%.0s' $(seq 1 $filled) 2>/dev/null || printf '%*s' "$filled" '' | tr ' ' '█'
    printf '░%.0s' $(seq 1 $empty) 2>/dev/null || printf '%*s' "$empty" '' | tr ' ' '░'
}

# ─── Draw stage line ─────────────────────────────────────────────
_liveui_draw() {
    local stage_num="$1"; local total="$2"; local stage_name="$3"
    local status="${4:-running}"  # running|success|failed|skipped
    local progress_pct="${5:-0}" local message="${6:-}"
    local errors="$7"  # extra info

    # Status symbol
    local sym="▓"
    case "$status" in
        success) sym="✔" ;;
        failed)  sym="✘" ;;
        skipped) sym="⊘" ;;
        running) sym="▓" ;;
        pending) sym="░" ;;
    esac

    # Progress bar for running stage
    local pbar=""
    if [[ "$status" == "running" && "$progress_pct" -gt 0 ]]; then
        pbar=" ["
        pbar+="$(_liveui_progress_bar "$progress_pct")"
        pbar+="] ${progress_pct}%"
    fi

    # Compose line
    local line
    line="$(printf '\r  %s Stage %02d/%02d — %-24s %-8s%s' \
        "$sym" "$stage_num" "$total" "$stage_name" "$status" "$pbar")"

    # Truncate to terminal width
    local cols="${COLUMNS:-80}"
    if ((${#line} > cols - 1)); then
        line="${line:0:$((cols - 4))}..."
    fi

    printf '%s' "$line"

    # Error line below
    if [[ -n "$errors" ]]; then
        printf '\n    \033[1;31m✘ %s\033[0m' "$errors"
    fi

    # Message line below
    if [[ -n "$message" && "$status" == "running" ]]; then
        printf '\n    → %s' "$message"
    fi

    # Clear to end of line
    printf '\033[K'
}

# ─── Stage events ────────────────────────────────────────────────
liveui_stage_start() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    _LIVEUI_STAGE_START_MS=$(($(date +%s%3N)))
    _LIVEUI_ERRORS=()
    _liveui_draw "$1" "$2" "$3" "running" 0 "$4"
}

liveui_stage_progress() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    _liveui_draw "$1" "$2" "$3" "running" "$4" "$5"
}

liveui_stage_output() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    # Just show current message
    :
}

liveui_stage_success() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    _liveui_draw "$1" "$2" "$3" "success" 100 ""
    echo ""
}

liveui_stage_failed() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    _liveui_draw "$1" "$2" "$3" "failed" 0 "$4"
    echo ""
}

liveui_stage_skipped() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    _liveui_draw "$1" "$2" "$3" "skipped" 0 "$4"
    echo ""
}

# ─── Summary on complete ─────────────────────────────────────────
liveui_summary() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0
    echo ""
    echo "─────────────────────────────────────────────"
    echo "  Pipeline complete"
    echo "  Run ID: ${TRACE_RUN_ID:-unknown}"
    echo "  Exit:   $1"
    echo "  Time:   ${2:-unknown}ms"
    echo "─────────────────────────────────────────────"
}

# ─── Attach to trace stream ─────────────────────────────────────
# liveui_attach — call this to start reading from trace file
liveui_attach() {
    [[ "$_LIVEUI_ENABLED" != "1" ]] && return 0

    local trace_file="$1"
    [[ ! -f "$trace_file" ]] && return 1

    # Watch trace file for changes and update display
    tail -n 0 -F "$trace_file" 2>/dev/null | while read -r line; do
        local event
        event="$(printf '%s' "$line" | grep -o '"event":"[^"]*"' | cut -d'"' -f4)"

        case "$event" in
            stage.start)
                local stage_id
                stage_id="$(printf '%s' "$line" | grep -o '"stage_id":"[^"]*"' | cut -d'"' -f4)"
                local total="${TOTAL_STAGES:-26}"
                local stage_num
                stage_num="$(printf '%s' "$stage_id" | sed 's/s//')"
                local msg
                msg="$(printf '%s' "$line" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)"
                _liveui_draw "$stage_num" "$total" "$msg" "running" 0
                ;;
            stage.success)
                local stage_id
                stage_id="$(printf '%s' "$line" | grep -o '"stage_id":"[^"]*"' | cut -d'"' -f4)"
                local stage_num
                stage_num="$(printf '%s' "$stage_id" | sed 's/s//')"
                local msg
                msg="$(printf '%s' "$line" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)"
                _liveui_draw "$stage_num" "${TOTAL_STAGES:-26}" "$msg" "success" 100 ""
                echo ""
                ;;
            stage.error)
                local stage_id
                stage_id="$(printf '%s' "$line" | grep -o '"stage_id":"[^"]*"' | cut -d'"' -f4)"
                local stage_num
                stage_num="$(printf '%s' "$stage_id" | sed 's/s//')"
                local err
                err="$(printf '%s' "$line" | grep -o '"error_msg":"[^"]*"' | cut -d'"' -f4)"
                _liveui_draw "$stage_num" "${TOTAL_STAGES:-26}" "ERROR" "failed" 0 "$err"
                echo ""
                ;;
        esac
    done &
}

export -f liveui_init liveui_stage_start liveui_stage_progress
export -f liveui_stage_output liveui_stage_success liveui_stage_failed
export -f liveui_stage_skipped liveui_summary liveui_attach
