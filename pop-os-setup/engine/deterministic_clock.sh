#!/usr/bin/env bash
#=======================================================================
# engine/deterministic_clock.sh — Fake Clock Injection System
# v11.1 — Replay-time fixed timestamps for reproducibility
#=======================================================================
[[ -n "${_DETERMINISTIC_CLOCK_SOURCED:-}" ]] && return 0 || _DETERMINISTIC_CLOCK_SOURCED=1

# ═══════════════════════════════════════════════════════════════════
# INJECTED TIME STATE
# ═══════════════════════════════════════════════════════════════════

# These are set by: --epoch <unix_ts> or by replay system
readonly _INJECTED_EPOCH="${INJECTED_EPOCH:-}"
readonly _INJECTED_TIMESTAMP="${INJECTED_TIMESTAMP:-}"
readonly _INJECTED_FNAME_TS="${INJECTED_FNAME_TS:-}"

# ═══════════════════════════════════════════════════════════════════
# FUNCTIONS — return deterministic values (never real system time)
# ═══════════════════════════════════════════════════════════════════

epoch_now() {
    if [[ -n "$_INJECTED_EPOCH" ]]; then
        echo "$_INJECTED_EPOCH"
    else
        echo "0"
    fi
}

timestamp_now() {
    local ts
    ts=$(epoch_now)
    if [[ "$ts" -gt 0 ]]; then
        date -d "@$ts" +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "1970-01-01 00:00:00"
    else
        echo "1970-01-01 00:00:00"
    fi
}

fname_ts_now() {
    if [[ -n "$_INJECTED_FNAME_TS" ]]; then
        echo "$_INJECTED_FNAME_TS"
    fi
    local ts
    ts=$(epoch_now)
    date -d "@$ts" +"%Y%m%d-%H%M%S" 2>/dev/null || echo "19700101-000000"
}

log_ts() {
    timestamp_now
}

epoch_ms() {
    local ts
    ts=$(epoch_now)
    echo $((ts * 1000))
}

# Override date command if in hermetic mode
if [[ -n "$_INJECTED_EPOCH" ]]; then
    date() {
        if [[ "${1:-}" == "+%s" ]]; then
            echo "$_INJECTED_EPOCH"
        elif [[ "${1:-}" == "+%Y-%m-%d" ]]; then
            date -d "@$_INJECTED_EPOCH" +"%Y-%m-%d" 2>/dev/null || echo "1970-01-01"
        elif [[ "${1:-}" == "+%Y-%m-%d %H:%M:%S" ]]; then
            date -d "@$_INJECTED_EPOCH" +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "1970-01-01 00:00:00"
        else
            command date "$@"
        fi
    }
fi

export -f epoch_now timestamp_now fname_ts_now log_ts epoch_ms
