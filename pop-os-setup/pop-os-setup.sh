#!/bin/bash
#===============================================================================
# pop-os-setup.sh — Entry Controller (v4.0.0)
#===============================================================================
# Deterministic, fail-safe, manifest-driven setup pipeline.
# Usage: sudo ./pop-os-setup.sh [--profile NAME] [--dry-run] [--stage N]
#===============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR
export POP_OS_SETUP_DIR="$SCRIPT_DIR"

readonly VERSION="4.0.0"
readonly LOGDIR="/var/log/pop-os-setup"
readonly MANIFEST="${SCRIPT_DIR}/MANIFEST.json"

# ─── LOGGING ─────────────────────────────────────────────────────────────────
ensure_dir() { mkdir -p "$1" 2>/dev/null || true; }
ensure_dir "$LOGDIR"

LOGFILE="${LOGDIR}/pop-os-setup-$(date +%Y-%m-%d_%H-%M-%S).log"
exec > >(tee -a "$LOGFILE") 2>&1

# ─── BOOTSTRAP PATH RESOLUTION ───────────────────────────────────────────────
source "${SCRIPT_DIR}/lib/_path.sh"

if [[ -z "${LIBDIR:-}" ]]; then
    echo "FATAL: LIBDIR resolution failed"
    echo "PWD=$PWD BASH_SOURCE[0]=${BASH_SOURCE[0]:-}"
    exit 1
fi

# ─── CLI PARSING ──────────────────────────────────────────────────────────────
DRY_RUN=0
SELECTED_STAGE=""
PROFILE="${PROFILE:-workstation}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1 ;;
        --stage)      SELECTED_STAGE="$2"; shift ;;
        --profile)    PROFILE="$2"; shift ;;
        --version)    echo "pop-os-setup v$VERSION"; exit 0 ;;
        --help)
            echo "pop-os-setup v$VERSION"
            echo "Usage: $0 [--profile NAME] [--dry-run] [--stage N]"
            echo "Profiles: workstation, ai-dev, full"
            exit 0
            ;;
    esac
    shift
done

# ─── MANIFEST VALIDATION ──────────────────────────────────────────────────────
if [[ ! -f "$MANIFEST" ]]; then
    echo "FATAL: MANIFEST.json not found at $MANIFEST"
    exit 1
fi

command -v jq &>/dev/null || {
    echo "FATAL: jq is required (apt install jq)"
    exit 1
}

# ─── CORE LIBS ────────────────────────────────────────────────────────────────
source "${LIBDIR}/bootstrap.sh"

# ─── PROFILE LOADING ──────────────────────────────────────────────────────────
load_profile() {
    local profile_name="${1:-workstation}"
    local profile_json
    profile_json=$(jq -r ".profiles.\"${profile_name}\" // empty" "$MANIFEST")

    if [[ -z "$profile_json" ]]; then
        echo "FATAL: Unknown profile: $profile_name"
        exit 1
    fi

    # Export ENABLE_* flags
    while IFS== read -r flag value; do
        [[ -z "$flag" ]] && continue
        export "$flag"="$value"
    done < <(jq -r '.flags | to_entries | .[] | "\(.key)=\(.value)"' <<< "$profile_json")

    log "Profile applied: $profile_name"
}

load_profile "$PROFILE"

# ─── STAGE RUNNER ─────────────────────────────────────────────────────────────
run_stage() {
    local stage_file="$1"
    local stage_name
    stage_name=$(basename "$stage_file" .sh)

    echo ""
    log_sep
    step "$stage_name" ""

    if [[ ! -f "$stage_file" ]]; then
        err "Stage file not found: $stage_file"
        return 1
    fi

    source "$stage_file"

    # Call bootstrap (mandatory per stage contract)
    bootstrap_stage || {
        err "Bootstrap failed for $stage_name"
        return 1
    }

    # Detect stage function
    local func_name=""
    func_name=$(grep -m1 "^stage_[a-z_]*()" "$stage_file" 2>/dev/null | sed 's/()//; s/stage_//')

    if [[ -z "$func_name" ]]; then
        err "No stage function found in $stage_file"
        return 1
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        ok "[DRY-RUN] Would run: ${func_name}()"
        return 0
    fi

    # Execute
    "stage_${func_name}"
}

# ─── MAIN EXECUTION LOOP ─────────────────────────────────────────────────────
log "pop-os-setup v$VERSION — starting (profile: $PROFILE, dry-run: $DRY_RUN)"

if [[ -n "$SELECTED_STAGE" ]]; then
    # Single stage mode
    local stage_file
    stage_file=$(jq -r ".stages[] | select(.id == $SELECTED_STAGE) | .file" "$MANIFEST")
    if [[ -z "$stage_file" || "$stage_file" == "null" ]]; then
        err "Stage $SELECTED_STAGE not found in MANIFEST"
        exit 1
    fi
    run_stage "${SCRIPT_DIR}/${stage_file}"
else
    # Full pipeline — ordered by stage.id
    while IFS= read -r stage_file; do
        [[ -z "$stage_file" ]] && continue
        run_stage "${SCRIPT_DIR}/${stage_file}" || {
            err "Stage failed: $stage_file"
            echo "[R]etry [S]kip [A]bort: "
            read -r ans || true
            case "$ans" in
                R|r) continue ;;
                S|s) ok "Skipping..." ;;
                *)   exit 1 ;;
            esac
        }
    done < <(jq -r '.stages | sort_by(.id) | .[].file' "$MANIFEST")
fi

log_sep
ok "pop-os-setup v$VERSION — ALL DONE!"
log "Log: $LOGFILE"
