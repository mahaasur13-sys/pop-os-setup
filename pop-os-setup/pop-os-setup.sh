#!/bin/bash
#=======================================================================
# pop-os-setup.sh — v4.1 Entry Controller
#=======================================================================
# DAG-based orchestrator with state persistence
# Single source of truth: MANIFEST.json
#=======================================================================

set -euo pipefail

readonly SCRIPT_VERSION="4.1.0"
readonly SCRIPT_NAME="pop-os-setup"
readonly LOGDIR="${LOGDIR:-/var/log/${SCRIPT_NAME}}"
readonly STATE_DIR="${STATE_DIR:-/var/lib/${SCRIPT_NAME}}"
readonly STATE_FILE="${STATE_DIR}/state.json"

# ─── LOGGING ────────────────────────────────────────────────────────────────
_log() {
    local level="$1"; shift
    echo "[$level] [$(date '+%H:%M:%S')] $*" >&2
    [[ -d "$LOGDIR" ]] && echo "[$level] [$(date '+%H:%M:%S')] $*" >> "${LOGDIR}/$(date '+%Y-%m-%d').log"
}
ok()   { _log "OK" "$@"; }
info() { _log "INFO" "$@"; }
warn() { _log "WARN" "$@"; }
err()  { _log "ERROR" "$@"; }
step() { _log "STAGE" "=$2= $1"; }

# ─── USAGE ───────────────────────────────────────────────────────────────────
usage() {
    cat << USAGE_EOF
Usage: sudo ${SCRIPT_NAME}.sh [OPTIONS]

Options:
  --profile <name>   Profile to run (default: workstation)
  --dry-run          Show execution plan without running
  --list-stages      List all stages from MANIFEST
  --list-profiles    List available profiles
  --resume           Resume from previous state
  --retry <stage>    Re-run specific stage
  --reset            Reset all state (start fresh)
  --version          Show version
  --help             Show this help
USAGE_EOF
}

# ─── CLI PARSER ──────────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile)   export PROFILE="$2"; shift 2 ;;
            --dry-run)   export DRY_RUN=1 ;;
            --resume)    export RESUME=1 ;;
            --reset)     export RESET_STATE=1 ;;
            --retry)     export RETRY_STAGE="$2"; shift 2 ;;
            --list-stages)  list_stages; exit 0 ;;
            --list-profiles) list_profiles; exit 0 ;;
            --version)  echo "${SCRIPT_VERSION}"; exit 0 ;;
            --help)     usage; exit 0 ;;
            *)          usage; exit 1 ;;
        esac
        shift
    done
}

# ─── BOOTSTRAP ─────────────────────────────────────────────────────────────
bootstrap() {
    if [[ -z "${BASEDIR:-}" ]]; then
        BASEDIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
        export BASEDIR
    fi

    source "${BASEDIR}/lib/_path.sh" || { err "lib/_path.sh not found"; exit 1; }
    source "${LIBDIR}/_dag.sh"       || { err "lib/_dag.sh not found"; exit 1; }
    source "${LIBDIR}/_state.sh"     || { err "lib/_state.sh not found"; exit 1; }
    source "${LIBDIR}/logging.sh"     2>/dev/null || true
    source "${LIBDIR}/utils.sh"      2>/dev/null || true
}

# ─── PROFILE LOADER ──────────────────────────────────────────────────────────
load_profile() {
    local profile="${PROFILE:-${1:-workstation}}"
    local profile_file="${BASEDIR}/profiles/${profile}.sh"

    if [[ ! -f "$profile_file" ]]; then
        err "Profile not found: $profile_file"
        return 1
    fi

    info "Loading profile: $profile"
    source "$profile_file"
    export PROFILE="$profile"
}

# ─── MAIN ────────────────────────────────────────────────────────────────────
main() {
    mkdir -p "$LOGDIR" 2>/dev/null || true
    info "pop-os-setup v${SCRIPT_VERSION} starting"

    bootstrap || exit 1

    if [[ -z "${PROFILE:-}" ]]; then
        PROFILE="workstation"
    fi

    load_profile || exit 1

    [[ "${RESET_STATE:-}" == "1" ]] && {
        rm -f "$STATE_FILE"
        ok "State reset complete"
        exit 0
    }

    [[ "${DRY_RUN:-}" == "1" ]] && {
        load_state 2>/dev/null || true
        load_manifest || exit 1
        build_dag "$PROFILE" || exit 1
        ok "DRY RUN — profile: $PROFILE"
        for stage in $(get_topo_order); do
            echo "  $stage  [$(get_state "$stage" || echo 'pending')]"
        done
        exit 0
    }

    load_state || true

    load_manifest || {
        err "Failed to load MANIFEST.json"
        exit 1
    }

    build_dag "$PROFILE" || {
        err "DAG build failed (cycle?)"
        exit 1
    }

    local skipped=0 executed=0 failed=0
    for stage in $(get_topo_order); do
        local status
        status="$(get_state "$stage")"

        if [[ "$status" == "$LC_DONE" ]] || [[ "$status" == "$LC_SKIPPED" ]]; then
            ((skipped++))
            continue
        fi

        step "$(echo "${_DAG_NODES[$stage]}" | jq -r '.name')" "$stage"

        if run_stage "$stage"; then
            ((executed++))
        else
            ((failed++))
            warn "Stage $stage failed"
        fi
    done

    echo ""
    echo "============================================"
    echo "  pop-os-setup v${SCRIPT_VERSION} — DONE"
    echo "  Executed: $executed  Skipped: $skipped  Failed: $failed"
    echo "============================================"
}

parse_args "$@"
main
