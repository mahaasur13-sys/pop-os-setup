#!/usr/bin/env bash
#===============================================
# pop-os-setup.sh v9.2 — Production Boot Entry
#===============================================
# Modes: --list | --validate | --dry-run | --resume | --rollback | --full
# SAFE_MODE blocks execution on validation/runtime failure.
# All paths resolved via lib/runtime.sh
#===============================================

set -euo pipefail
shopt -s inherit_errexit 2>/dev/null || true

# Load runtime (provides all paths, state, logging, trap)
# NOTE: We don't source the whole runtime.sh for dry-run
# because it auto-runs bootstrap(). Instead, we inline
# the path resolution so --validate works without a full bootstrap.
if [[ -f "${BASH_SOURCE[0]%/*}/lib/runtime.sh" ]]; then
    source "${BASH_SOURCE[0]%/*}/lib/runtime.sh"
else
    echo "FATAL: lib/runtime.sh not found" >&2
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════

usage() {
    cat << 'EOF'
Usage: sudo ./pop-os-setup.sh [MODE] [OPTIONS]

Modes:
  --list          Show all stages and current status
  --validate      Pre-flight validation (syntax + deps + DAG)
  --dry-run       Preview execution without changes
  --resume        Resume from last failed stage
  --rollback      Rollback last failed stage
  --full          Run full pipeline (default)

Options:
  --profile NAME   Use profile (workstation|ai-dev|full|cluster)
  --policy POL     Recovery policy: abort|skip|retry (default: abort)
  --verbose        Enable verbose output
  --run-id ID      Custom run identifier
  -h, --help       Show this help

Examples:
  sudo ./pop-os-setup.sh                    # Full run
  sudo ./pop-os-setup.sh --dry-run          # Preview
  sudo ./pop-os-setup.sh --resume           # Recover
  sudo ./pop-os-setup.sh --validate         # Check system
EOF
    exit 0
}

parse_args() {
    MODE="${MODE:-full}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --list)       MODE=list ;;
            --validate)   MODE=validate ;;
            --dry-run)    MODE=dry-run ;;
            --resume)     MODE=resume ;;
            --rollback)   MODE=rollback ;;
            --full)       MODE=full ;;
            --profile)    PROFILE="$2"; shift ;;
            --policy)     RECOVERY_POLICY="$2"; shift ;;
            --verbose)    VERBOSE=1 ;;
            --run-id)     RUN_ID="$2"; shift ;;
            -h|--help)    usage ;;
            *)            err "Unknown argument: $1"; usage ;;
        esac
        shift
    done
}

# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

main() {
    log "═══════════════════════════════════════════"
    log "  pop-os-setup ${RUNTIME_VERSION} — Production Installer"
    log "═══════════════════════════════════════════"
    log "  Mode:     $MODE"
    log "  Run ID:   $RUN_ID"
    log "  Profile:  ${PROFILE:-default}"
    log "  Policy:   $RECOVERY_POLICY"
    log "  Safe:     ${SAFE_MODE:-0}"
    log "  Dry:      ${DRY_RUN:-0}"
    log "═══════════════════════════════════════════"

    case "$MODE" in
        list)
            source "${ENGINEDIR}/runner.sh" 2>/dev/null || true
            list_stages
            ;;

        validate)
            if validate_all && validate_dag; then
                ok "System validation: PASSED"
                exit 0
            else
                err "System validation: FAILED"
                err "SAFE_MODE enabled — only safe operations allowed"
                set_safe_mode
                exit 1
            fi
            ;;

        dry-run)
            export DRY_RUN=1
            source "${ENGINEDIR}/runner.sh" 2>/dev/null || true
            dry_run_all
            ;;

        resume)
            source "${ENGINEDIR}/runner.sh"
            resume_pipeline
            ;;

        rollback)
            source "${ENGINEDIR}/runner.sh"
            rollback_last "$(find "${STATE_DIR}" -name '*.state' -newer "${STATE_DIR}"/*.checkpoint 2>/dev/null | head -1 | xargs -I{} basename {} .state || echo '')"
            ;;

        full)
            # Acquire lock first
            if ! acquire_lock; then
                err "Another instance is running. Remove lock: sudo rm $LOCK_FILE"
                exit 1
            fi

            # Runtime validation
            if ! validate_all; then
                err "Pre-flight validation failed"
                set_safe_mode
                release_lock
                err "SAFE_MODE enabled — use --list, --validate, --dry-run only"
                exit 1
            fi

            # Load runner
            source "${ENGINEDIR}/runner.sh"

            # Run pipeline
            if run_pipeline; then
                log "═══════════════════════════════════════════"
                log "  ✅ ALL DONE — pop-os-setup ${RUNTIME_VERSION}"
                log "═══════════════════════════════════════════"
                release_lock
                exit 0
            else
                err "Pipeline failed — run with --resume to recover"
                err "SAFE_MODE enabled — use --list, --validate, --dry-run only"
                release_lock
                exit 1
            fi
            ;;
    esac
}

# Trap cleanup
trap 'release_lock 2>/dev/null || true' EXIT INT TERM

# ═══════════════════════════════════════════════════════════
# BOOT
# ═══════════════════════════════════════════════════════════

MODE="full"
PROFILE="${PROFILE:-}"
parse_args "$@"
main