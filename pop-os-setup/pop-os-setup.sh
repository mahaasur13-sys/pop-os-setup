#!/usr/bin/env bash
#=================================================================
# pop-os-setup.sh v9.5 — Observability-Native Installer
#=================================================================
# New in v9.5: full event-driven observability layer
#   • tracer.sh  — trace context + JSONL emission
#   • event_bus  — fan-out to handlers/hooks
#   • metrics.sh — stage_duration_ms, failure_rate, retry_count
#   • live_ui.sh — real-time TTY progress bar
#=================================================================

set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# Bootstrap
# ═══════════════════════════════════════════════════════════════
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
SCRIPT_DIR="$(pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
OBS_DIR="${SCRIPT_DIR}/observability"
export PATH="${SCRIPT_DIR}:${LIB_DIR}:${PATH}"
mkdir -p "${SCRIPT_DIR}/logs" "${SCRIPT_DIR}/state"

# ═══════════════════════════════════════════════════════════════
# Version (single source of truth)
# ═══════════════════════════════════════════════════════════════
readonly RUNTIME_VERSION="v9.5"
get_version() { echo "$RUNTIME_VERSION"; }

# ═══════════════════════════════════════════════════════════════
# Source libraries (load order matters)
# ═══════════════════════════════════════════════════════════════
source "${LIB_DIR}/logging.sh"
source "${LIB_DIR}/utils.sh"
source "${LIB_DIR}/runtime.sh"        # installs stage_load() etc
source "${OBS_DIR}/tracer.sh"         # trace_init, emit_event, etc.
source "${OBS_DIR}/metrics.sh"        # metrics_*

# Live UI (TTY only)
WATCH_MODE=0
[[ -t 1 ]] && source "${OBS_DIR}/live_ui.sh" 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════
# CLI flags
# ═══════════════════════════════════════════════════════════════
_show_help() {
    cat << 'HELPEOF'
Usage: pop-os-setup.sh [OPTIONS]

Options:
  --profile <name>    Profile: ai-dev|workstation|full (default: full)
  --dry-run           Validate stages without executing
  --watch             Enable live TTY progress display
  --trace-level <lvl> Trace level: debug|info|warn|error|critical (default: info)
  --list              List all stages
  --list-profiles     List available profiles
  --resume <run_id>   Resume from run_id checkpoint
  --verify            Verify integrity + exit
  --help              Show this help

Examples:
  pop-os-setup.sh                          # full profile, interactive
  pop-os-setup.sh --profile ai-dev         # AI/ML workstation
  pop-os-setup.sh --dry-run --watch         # preview with live UI
  pop-os-setup.sh --resume RUN-20260422ABC # resume interrupted run
HELPEOF
}

parse_args() {
    DRY_RUN=0
    PROFILE=""
    LIST_STAGES=0
    LIST_PROFILES=0
    RESUME_ID=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)       DRY_RUN=1 ;;
            --watch)         WATCH_MODE=1 ;;
            --profile)       PROFILE="${2:-}"; shift ;;
            --trace-level)   TRACE_LEVEL="${2:-info}"; shift ;;
            --list)          LIST_STAGES=1 ;;
            --list-profiles) LIST_PROFILES=1 ;;
            --resume)        RESUME_ID="${2:-}"; shift ;;
            --verify)        VERIFY_MODE=1 ;;
            --help)          _show_help; exit 0 ;;
            *)               err "Unknown option: $1" ;;
        esac
        shift
    done
}

# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
main() {
    log "══════════════════════════════════════════"
    log "  pop-os-setup $(get_version)"
    log "  $(uname -m) | $(detect_os)"
    log "══════════════════════════════════════════"

    # ── Init observability ──────────────────────────────────────
    local run_id
    run_id="$(date '+RUN-%Y%m%d%H%M%S')-$$"
    local trace_file="${SCRIPT_DIR}/logs/trace_${run_id}.jsonl"

    mkdir -p "$(dirname "$trace_file")"
    trace_init "$run_id" "$trace_file"
    trace_info "cli.parse" "root" "CLI parsed, starting pipeline" \
        "profile=${PROFILE:-default}" \
        "dry_run=${DRY_RUN}" \
        "watch_mode=${WATCH_MODE}" \
        "version=$(get_version)"

    metrics_pipeline_start

    # ── Pre-flight checks ──────────────────────────────────────
    if ! require_root; then
        err "Root required (use sudo)"
        trace_critical "acl.root_required" "root" "Permission denied"
        exit 1
    fi

    # ── Load profile ────────────────────────────────────────────
    if [[ -n "$RESUME_ID" ]]; then
        info "Resuming run: ${RESUME_ID}"
    fi

    if [[ -z "$PROFILE" ]]; then
        PROFILE="full"
    fi

    log "Profile: ${PROFILE}"

    # ── List modes ─────────────────────────────────────────────
    if ((LIST_STAGES)); then
        list_stages
        exit 0
    fi

    if ((LIST_PROFILES)); then
        list_profiles
        exit 0
    fi

    # ── Validate + list ─────────────────────────────────────────
    if ! stage_discovery "${SCRIPT_DIR}/stages"; then
        err "Stage discovery failed"
        exit 1
    fi

    log "Discovered $(stage_count) stages"

    if ((VERIFY_MODE)); then
        verify_stages || exit 1
        ok "Verification passed"
        exit 0
    fi

    # ── Pipeline start ──────────────────────────────────────────
    local pipeline_start_ms
    pipeline_start_ms=$(($(date +%s%3N)))
    trace_pipeline_start "${PROFILE}"
    metrics_pipeline_start

    log "Starting pipeline — Run ID: ${run_id}"
    log "Trace file: ${trace_file}"
    log ""

    # ── Live UI ────────────────────────────────────────────────
    if ((WATCH_MODE)); then
        info "Watch mode: streaming trace from ${trace_file}"
        liveui_attach "$trace_file" &
        local liveui_pid=$!
    fi

    # ── Execute stages ─────────────────────────────────────────
    local exit_code=0
    local stage_num=0
    local stage_name=""

    while IFS= read -r stage_file; do
        ((stage_num++))

        # Load + validate
        stage_load "$stage_file" || {
            warn "Skipping ${stage_file} (load failed)"
            continue
        }

        stage_name="$(stage_get_name)"

        # Pre-stage observability
        metrics_stage_begin "$stage_num" "$stage_name"
        trace_stage_start "$stage_num" "$stage_name"
        liveui_init

        log ""
        log "[STAGE ${stage_num}] $(toupper "$stage_name")"

        # ── Run stage ────────────────────────────────────────
        local stage_start_ms
        stage_start_ms=$(($(date +%s%3N)))

        if ((DRY_RUN)); then
            ok "[DRY-RUN] Would execute: ${stage_name}"
            trace_stage_skip "$stage_num" "$stage_name" "dry-run"
            continue
        fi

        local stage_output
        local stage_exit_code=0

        if stage_execute; then
            local stage_end_ms duration_ms
            stage_end_ms=$(($(date +%s%3N)))
            duration_ms=$((stage_end_ms - stage_start_ms))

            trace_stage_success "$stage_num" "$stage_name" "$duration_ms"
            metrics_stage_end "$stage_num" "$stage_name" "success"
            liveui_stage_success "$stage_num" "$(stage_count)" "$stage_name"

        else
            stage_exit_code=$?
            local stage_end_ms duration_ms
            stage_end_ms=$(($(date +%s%3N)))
            duration_ms=$((stage_end_ms - stage_start_ms))

            trace_stage_error "$stage_num" "$stage_name" "stage exited with $stage_exit_code"
            metrics_stage_end "$stage_num" "$stage_name" "failed"

            err "Stage ${stage_num} failed (exit ${stage_exit_code})"
            err "Trace: ${trace_file}"
            liveui_stage_failed "$stage_num" "$(stage_count)" "$stage_name" "exit code $stage_exit_code"

            # Rollback decision
            if confirm "Rollback last stage?"; then
                trace_rollback_trigger "$stage_num" "user-requested" "prev_checkpoint"
                metrics_rollback "$stage_num" "$stage_name"
                stage_rollback || true
            fi

            if ! confirm "Continue despite failure?"; then
                exit_code=1
                break
            fi
        fi

    done < <(stage_enumerate)

    # ── Pipeline end ────────────────────────────────────────────
    local pipeline_end_ms duration_ms
    pipeline_end_ms=$(($(date +%s%3N)))
    duration_ms=$((pipeline_end_ms - pipeline_start_ms))

    trace_pipeline_end "$exit_code" "$duration_ms"
    metrics_to_json
    liveui_summary "$exit_code" "$duration_ms"

    # ── Final report ───────────────────────────────────────────
    echo ""
    echo "══════════════════════════════════════════"
    ok   "  pop-os-setup $(get_version) — DONE"
    info "  Run ID:     ${run_id}"
    info "  Duration:   ${duration_ms}ms"
    info "  Trace:      ${trace_file}"
    echo "══════════════════════════════════════════"

    trace_info "pipeline.complete" "root" "Pipeline complete" \
        "exit_code=${exit_code}" \
        "duration_ms=${duration_ms}" \
        "event_count=${_OBS_EVENT_COUNT:-0}"

    # Kill live UI if running
    ((WATCH_MODE)) && kill $liveui_pid 2>/dev/null || true

    return $exit_code
}

# ═══════════════════════════════════════════════════════════════
parse_args "$@"
main
