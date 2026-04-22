#!/usr/bin/env bash
#===============================================
# pop-os-setup.sh v9.4 — Production Installer
# Observability layer: no silent execution
#===============================================

set -euo pipefail

# ─── Metadata ────────────────────────────────────────────────────────────────
readonly RUNTIME_VERSION="v9.4"
readonly SCRIPT_NAME="pop-os-setup"
readonly STATE_DIR="${STATE_DIR:-/var/lib/pop-os-setup}"
readonly LOG_DIR="${LOG_DIR:-/var/log/pop-os-setup}"

# ─── Bootstrap ────────────────────────────────────────────────────────────────
bootstrap() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    LIBDIR="${script_dir}/lib"
    STAGEDIR="${script_dir}/stages"

    # Source observability FIRST
    if [[ -f "${LIBDIR}/observability.sh" ]]; then
        source "${LIBDIR}/observability.sh"
    fi

    if [[ -f "${LIBDIR}/logging.sh" ]]; then
        source "${LIBDIR}/logging.sh"
    fi

    if [[ -f "${LIBDIR}/utils.sh" ]]; then
        source "${LIBDIR}/utils.sh"
    fi

    if [[ -f "${LIBDIR}/runtime.sh" ]]; then
        source "${LIBDIR}/runtime.sh"
    fi

    init_state_dir
    init_log_dir

    obs_init "${RUN_ID:-}"
}

# ─── Main ────────────────────────────────────────────────────────────────────
main() {
    bootstrap "$@"

    obs_emit "banner" "Starting pop-os-setup ${RUNTIME_VERSION}"

    log "════════════════════════════════════"
    log "  pop-os-setup ${RUNTIME_VERSION}"
    log "  Profile:   ${PROFILE:-full}"
    log "  Run ID:    ${RUN_ID:-unknown}"
    log "  Stage:     ${START_STAGE:-1} → ${END_STAGE:-99}"
    log "  Safe mode: ${SAFE_MODE:-0}"
    log "════════════════════════════════════"

    local stages_run=0 stages_skipped=0 stages_failed=0
    local start_ts=$(date +%s)

    for stage_num in $(seq "${START_STAGE:-1}" "${END_STAGE:-99}"); do
        # Stop at END_STAGE
        [[ $stage_num -gt ${END_STAGE:-99} ]] && break

        # Find stage file
        local stage_file
        stage_file=$(find_stage_file "$stage_num" 2>/dev/null || true)

        if [[ -z "$stage_file" || ! -f "$stage_file" ]]; then
            continue
        fi

        local stage_name
        stage_name=$(derive_stage_name "$stage_file")
        CURRENT_STAGE="$stage_name"

        obs_stage_begin "$stage_num" "$stage_name" "99"
        obs_progress "$stage_num" 26 "$stage_name"

        local stage_exit=0
        if [[ "${DRY_RUN:-0}" == "1" ]]; then
            ok "DRY-RUN: $stage_name (would execute)"
            obs_stage_end "$stage_num" "$stage_name" "skipped"
            ((stages_skipped++)) || true
        else
            if source "$stage_file" 2>&1; then
                local stage_fn="stage_${stage_num}_${stage_name}"
                if declare -f "$stage_fn" >/dev/null 2>&1; then
                    if "$stage_fn" 2>&1; then
                        ok "$stage_name: OK"
                        obs_stage_end "$stage_num" "$stage_name" "success"
                        obs_op_end "stage_${stage_num}" "ok"
                        ((stages_run++)) || true
                    else
                        err "$stage_name: FAIL"
                        obs_stage_end "$stage_num" "$stage_name" "failure"
                        obs_err "Stage $stage_num failed with exit code $?"
                        ((stages_failed++)) || true
                        handle_failure "$stage_num" "$stage_name"
                    fi
                else
                    ok "$stage_name: loaded (no main function)"
                    obs_stage_end "$stage_num" "$stage_name" "skipped"
                    ((stages_skipped++)) || true
                fi
            else
                err "$stage_name: SOURCE FAIL"
                obs_stage_end "$stage_num" "$stage_name" "failure"
                ((stages_failed++)) || true
            fi
        fi
    done

    local duration=$(( $(date +%s) - start_ts ))

    obs_summary \
        "$([ $stages_failed -eq 0 ] && echo "success" || echo "partial_failure")" \
        "$stages_run" "$stages_skipped" "$stages_failed" "$duration"

    return $((stages_failed > 0 ? 1 : 0))
}

# ─── Failure handler ─────────────────────────────────────────────────────────
handle_failure() {
    local stage_num="$1"
    local stage_name="$2"

    obs_err "Stage $stage_num ($stage_name) failed"

    if [[ "${SAFE_MODE:-0}" == "1" || "${CONTINUE_ON_ERROR:-0}" != "1" ]]; then
        obs_emit "run_aborted" "Aborting due to stage failure (safe mode)"
        exit 1
    fi

    obs_warn "Continuing despite failure (CONTINUE_ON_ERROR=1)"
}

# ─── Parse args ───────────────────────────────────────────────────────────────
parse_args() {
    DRY_RUN=0
    START_STAGE=1
    END_STAGE=99
    PROFILE="${PROFILE:-}"
    SAFE_MODE=0
    CONTINUE_ON_ERROR=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) DRY_RUN=1 ;;
            --stage) START_STAGE="$2"; shift ;;
            --end-stage) END_STAGE="$2"; shift ;;
            --profile) PROFILE="$2"; shift ;;
            --safe) SAFE_MODE=1 ;;
            --continue) CONTINUE_ON_ERROR=1 ;;
            --run-id) export RUN_ID="$2"; shift ;;
            --help|-h) usage; exit 0 ;;
            *) ;;
        esac
        shift
    done
}

usage() {
    cat << 'USAGE'
  pop-os-setup.sh [options]

  --dry-run         Preview mode (no changes)
  --stage N         Start from stage N
  --end-stage N     Stop at stage N
  --profile NAME    Profile: workstation|ai-dev|cluster|full
  --safe            Abort on any stage failure
  --continue        Keep going despite failures
  --run-id ID       Set explicit run ID
  --help            Show this help

  Observability enabled by default (no silent execution).
USAGE
}

# ─── Bootstrap & run ─────────────────────────────────────────────────────────
bootstrap "$@"
parse_args "$@"
main