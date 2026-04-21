#!/bin/bash
#===============================================================================
# pop-os-setup.sh — v5.0.0 Execution Engine Entry Point
# Deterministic stateful DAG orchestration with replayable execution model
#===============================================================================

set -euo pipefail

# ─── METADATA ─────────────────────────────────────────────────────────────────
readonly SCRIPT_VERSION="5.0.0"
readonly SCRIPT_NAME="pop-os-setup"
readonly LOGDIR="${LOGDIR:-/var/log/${SCRIPT_NAME}}"

# ─── DIR SETUP ───────────────────────────────────────────────────────────────
if [[ -L "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
readonly SCRIPT_DIR

# ─── PATHS ───────────────────────────────────────────────────────────────────
LIBDIR="${SCRIPT_DIR}/lib"
ENGDIR="${SCRIPT_DIR}/engine"
STAGES_DIR="${SCRIPT_DIR}/stages"
STATE_DIR="${STATE_DIR:-/var/lib/${SCRIPT_NAME}}"
MANIFEST_PATH="${MANIFEST_PATH:-${SCRIPT_DIR}/MANIFEST.json}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"

export SCRIPT_DIR LIBDIR ENGDIR STAGES_DIR STATE_DIR MANIFEST_PATH RUN_ID

# ─── BOOTSTRAP ───────────────────────────────────────────────────────────────
mkdir -p "$LOGDIR" "$STATE_DIR" 2>/dev/null || true
chmod 755 "$LOGDIR" "$STATE_DIR" 2>/dev/null || true

# ─── LOGGING ───────────────────────────────────────────────────────────────
LOGFILE="${LOGDIR}/${SCRIPT_NAME}-${RUN_ID}.log"
exec > >(tee -a "$LOGFILE") 2>&1

log()    { echo "[$(date +%H:%M:%S)] [INFO] $1"; }
info()   { echo "[$(date +%H:%M:%S)] [INFO] $1"; }
ok()     { echo "[$(date +%H:%M:%S)] [OK] $1"; }
warn()   { echo "[$(date +%H:%M:%S)] [WARN] $1"; }
err()    { echo "[$(date +%H:%M:%S)] [ERR] $1"; }
step()   { echo ""; echo "  Stage $2: $(to_upper "$1")"; echo "=============================="; }
to_upper(){ printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }

# ─── INCLUDE ENGINE ─────────────────────────────────────────────────────────
for lib in "${LIBDIR}"/_*.sh "${ENGDIR}"/*.sh; do
    [[ -f "$lib" ]] || continue
    source "$lib"
done 2>/dev/null || true

# ─── PARSE ARGUMENTS ─────────────────────────────────────────────────────────
PROFILE="${PROFILE:-workstation}"
RUN_MODE="${RUN_MODE:-full}"
DRY_RUN="${DRY_RUN:-0}"
REPLAY_FROM="${REPLAY_FROM:-}"
REPLAY_FAILED="${REPLAY_FAILED:-0}"
REPLAY_DIFF="${REPLAY_DIFF:-0}"
SKIP_UNCHANGED="${SKIP_UNCHANGED:-0}"

show_help() {
    cat << 'EOF'
pop-os-setup.sh v5.0.0 — Deterministic Infrastructure Orchestration

Usage: sudo ./pop-os-setup.sh [OPTIONS]

Options:
  --profile <name>      Profile: workstation|ai-dev|cluster|full (default: workstation)
  --dry-run             Validate + show execution plan, do not execute
  --replay-from <node>  Replay from given node (e.g. stage12_docker)
  --replay-failed       Replay all failed nodes
  --replay-diff-only    Replay only nodes with changed stage files (SHA256 diff)
  --skip-unchanged      Skip stages whose file hash hasn't changed
  --list-stages         Show all stages in current profile
  --list-profiles       Show all available profiles
  --show-state          Show current state.json
  --show-plan           Show compiled execution-plan.json
  --lock                Lock MANIFEST (prevent stage file changes)
  --unlock              Remove MANIFEST lock
  -h, --help            Show this help

Examples:
  sudo ./pop-os-setup.sh --dry-run --profile ai-dev
  sudo ./pop-os-setup.sh --profile workstation
  sudo ./pop-os-setup.sh --replay-failed
  sudo ./pop-os-setup.sh --replay-from stage12_docker
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile)    PROFILE="$2"; shift 2 ;;
            --dry-run)     DRY_RUN=1; shift ;;
            --replay-from) REPLAY_FROM="$2"; shift 2 ;;
            --replay-failed) REPLAY_FAILED=1; shift ;;
            --replay-diff-only) REPLAY_DIFF=1; shift ;;
            --skip-unchanged) SKIP_UNCHANGED=1; shift ;;
            --list-stages|--list-profiles|--show-state|--show-plan|--lock|--unlock)
                INTERACTIVE_CMD="$1"; shift ;;
            -h|--help) show_help; exit 0 ;;
            *) shift ;;
        esac
    done
}

# ─── MAIN ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "=============================================="
    echo "  pop-os-setup v${SCRIPT_VERSION} — Execution Engine"
    echo "  Profile: ${PROFILE} | Run: ${RUN_ID}"
    echo "=============================================="
    echo ""

    # Lock/unlock
    if [[ "${INTERACTIVE_CMD:-}" == "--lock" ]]; then
        lock_manifest; ok "Done"; exit 0; fi
    if [[ "${INTERACTIVE_CMD:-}" == "--unlock" ]]; then
        rm -f "${STATE_DIR}/.manifest.lock" 2>/dev/null; ok "Lock removed"; exit 0; fi

    # Read-only commands
    if [[ "${INTERACTIVE_CMD:-}" == "--show-state" ]]; then
        cat "${STATE_DIR}/state.json" 2>/dev/null || { err "No state.json found"; exit 1; }; exit 0; fi
    if [[ "${INTERACTIVE_CMD:-}" == "--show-plan" ]]; then
        cat "${STATE_DIR}/execution-plan.json" 2>/dev/null || { err "No plan found — run --dry-run first"; exit 1; }; exit 0; fi
    if [[ "${INTERACTIVE_CMD:-}" == "--list-stages" ]]; then
        compile_manifest > /dev/null 2>&1; cat "${STATE_DIR}/execution-plan.json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'Profile: {d[\"profile_filter\"]}')
print(f'Stages: {d[\"total_stages\"]} / Levels: {d[\"total_levels\"]}')
print()
for i,level in enumerate(d['graph']['levels']):
    parallel = 'parallel' if len(level)>1 else 'sequential'
    print(f'Level {i+1} [{parallel}]:')
    for n in level:
        print(f'  - {n[\"id\"]}: {n[\"name\"]}')
"; exit 0; fi

    # 1. Validate manifest
    log "Step 1/5: Validating MANIFEST.json..."
    validate_manifest || { err "Manifest validation failed"; exit 1; }

    # 2. Compile execution plan
    log "Step 2/5: Compiling execution plan..."
    compile_manifest || { err "Compilation failed"; exit 1; }

    # 3. Initialize state
    log "Step 3/5: Initializing state..."
    init_state || { err "State init failed"; exit 1; }

    # 4. Replay handlers
    if [[ -n "$REPLAY_FROM" ]]; then
        log "Replay mode: from=$REPLAY_FROM"
        replay_from "$REPLAY_FROM" || { err "Replay failed"; exit 1; }
    elif [[ "$REPLAY_FAILED" == "1" ]]; then
        log "Replay mode: failed nodes"
        replay_failed || { err "Replay failed"; exit 1; }
    elif [[ "$REPLAY_DIFF" == "1" ]]; then
        log "Replay mode: diff-only"
        replay_diff_only || { err "Diff replay failed"; exit 1; }
    fi

    # 5. Dry-run
    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY-RUN mode — execution plan:"
        python3 -c "
import json
d=json.load(open('${STATE_DIR}/execution-plan.json'))
print(f'  Total: {d[\"total_stages\"]} stages, {d[\"total_levels\"]} levels')
print(f'  Manifest SHA256: {d[\"manifest_sha\"][:16]}...')
print(f'  Profile: {d[\"profile_filter\"]}')
print()
for i,level in enumerate(d['graph']['levels']):
    p = 'parallel' if len(level)>1 else 'sequential'
    print(f'Level {i+1} [{p}]:')
    for n in level: print(f'  [{n[\"id\"]}] {n[\"name\"]}')
"
        ok "Dry-run complete — no changes made"
        exit 0
    fi

    # 6. Execute
    log "Step 4/5: Executing DAG..."
    execute_plan
    local exec_rc=$?

    log "Step 5/5: Finalizing..."
    finalize_state
    local final_rc=$?

    if [[ $exec_rc -eq 0 ]]; then
        echo ""
        echo "=============================================="
        ok "pop-os-setup v${SCRIPT_VERSION} — ALL DONE!"
        echo "=============================================="
        echo "  Run ID: ${RUN_ID}"
        echo "  Log:    ${LOGFILE}"
        echo ""
    else
        echo ""
        echo "=============================================="
        err "pop-os-setup v${SCRIPT_VERSION} — FAILED"
        echo "=============================================="
        echo "  Check log: ${LOGFILE}"
        echo ""
        exit 1
    fi
}

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
parse_args "$@"
main