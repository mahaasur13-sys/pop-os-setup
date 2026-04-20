#!/bin/bash
#===============================================================================
# pop-os-setup.sh — Pop!_OS 24.04 Auto-Configuration (v3.0.0)
# One entry-point, 26 dynamic stages, security-first design.
#===============================================================================

set -euo pipefail

# ─── METADATA ─────────────────────────────────────────────────────────────────
readonly SCRIPT_VERSION="3.0.0"
readonly SCRIPT_NAME="pop-os-setup"
readonly LOGDIR="/var/log/${SCRIPT_NAME}"

# ─── DIR SETUP ────────────────────────────────────────────────────────────────
if [[ -L "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
readonly SCRIPT_DIR
readonly LIBDIR="${SCRIPT_DIR}/lib"
readonly STAGEDIR="${SCRIPT_DIR}/stages"
readonly PROFILESDIR="${SCRIPT_DIR}/profiles"

# ─── LOG FILE ─────────────────────────────────────────────────────────────────
mkdir -p "$LOGDIR" 2>/dev/null || true
readonly LOGFILE="${LOGDIR}/${SCRIPT_NAME}-$(date +%Y-%m-%d_%H-%M-%S).log"

# ─── COLORS ───────────────────────────────────────────────────────────────────
if command -v tput &>/dev/null 2>&1 && [[ $(tput colors 2>/dev/null) -ge 8 ]]; then
    C_RESET="$(tput sgr0)"; C_BOLD="$(tput bold)"
    C_RED="$(tput setaf 1)"; C_GREEN="$(tput setaf 2)"
    C_YELLOW="$(tput setaf 3)"; C_CYAN="$(tput setaf 6)"
else
    C_RESET='\033[0m'; C_BOLD='\033[1m'
    C_RED='\033[31m'; C_GREEN='\033[32m'
    C_YELLOW='\033[33m'; C_CYAN='\033[36m'
fi

# ─── OUTPUT ───────────────────────────────────────────────────────────────────
info()   { echo -e "${C_CYAN}[INFO]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
log()    { echo -e "${C_CYAN}[$(date '+%H:%M:%S')]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
ok()     { echo -e "${C_GREEN}[OK]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
warn()   { echo -e "${C_YELLOW}[WARN]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
err()    { echo -e "${C_RED}[ERR]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }

step() {
    printf '\n'
    printf '=%.0s' {1..70}; printf '\n'
    printf "  STAGE %s | %s\n" "$2" "$1"
    printf '=%.0s' {1..70}; printf '\n\n'
}

log_sep(){ printf '=%.0s\n' {1..70} | tee -a "$LOGFILE" 2>/dev/null || true; }

# ─── HELP ─────────────────────────────────────────────────────────────────────
show_help() {
    cat << 'HELP'
pop-os-setup v3.0.0 — Pop!_OS 24.04 Auto-Configuration

USAGE
    sudo ./pop-os-setup.sh [OPTIONS]
    sudo PROFILE=<name> ./pop-os-setup.sh

OPTIONS
    --dry-run              Preview stages without making changes
    --profile <name>      Select: workstation|ai-dev|full|cluster
    --stage <NN>           Run only stage NN (01-26)
    --skip-stage <N,N>     Skip stages by number
    --help                 Show this help

EXAMPLES
    sudo ./pop-os-setup.sh
    sudo PROFILE=ai-dev ./pop-os-setup.sh
    sudo ./pop-os-setup.sh --dry-run
    sudo ./pop-os-setup.sh --skip-stage 6,13
    sudo ./pop-os-setup.sh --stage 09
HELP
}

# ─── DEFAULTS ─────────────────────────────────────────────────────────────────
DRY_RUN=false
SINGLE_STAGE=""
SKIP_STAGES=()
PROFILE="${PROFILE:-workstation}"

# ─── PARSE ────────────────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                info "Mode: DRY RUN — no changes will be made"
                shift
                ;;
            --profile)
                PROFILE="$2"; shift 2
                ;;
            --stage)
                if ! [[ "$2" =~ ^[0-9]{1,2}$ ]] || (( "$2" < 1 || "$2" > 26 )); then
                    err "Invalid stage: $2 (must be 01-26)"; exit 1
                fi
                SINGLE_STAGE="$(printf '%02d' "$((10#$2))")"; shift 2
                ;;
            --skip-stage)
                IFS=',' read -ra SKIP_STAGES <<< "$2"
                for i in "${!SKIP_STAGES[@]}"; do
                    SKIP_STAGES[i]="$(printf '%02d' "$((10#${SKIP_STAGES[i]}))")"
                done
                shift 2
                ;;
            --help|-h)
                show_help; exit 0
                ;;
            *)
                err "Unknown option: $1"; show_help; exit 1
                ;;
        esac
    done
}

# ─── CORE ─────────────────────────────────────────────────────────────────────
require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "This script must be run as root (use sudo)"; exit 1
    fi
}

validate_environment() {
    [[ -d "$LIBDIR" ]]       || { err "lib/ directory not found"; exit 1; }
    [[ -d "$STAGEDIR" ]]     || { err "stages/ directory not found"; exit 1; }
    [[ -d "$PROFILESDIR" ]]  || { err "profiles/ directory not found"; exit 1; }
}

load_libraries() {
    info "Loading libraries..."
    for lib in "$LIBDIR"/logging.sh "$LIBDIR"/utils.sh "$LIBDIR"/profiles.sh "$LIBDIR"/installer.sh; do
        [[ -f "$lib" ]] || continue
        # shellcheck disable=SC1090
        source "$lib"
        ok "Loaded: $(basename "$lib")"
    done
}

# ─── STAGE DISCOVERY ─────────────────────────────────────────────────────────
discover_stages() {
    declare -gA STAGES_MAP
    for file in "$STAGEDIR"/stage[0-9]*.sh; do
        [[ -f "$file" ]] || continue
        local basename="${file##*/}"
        # stage01_preflight.sh -> num=01, name=preflight
        if [[ "$basename" =~ ^stage([0-9]+)_(.+)\.sh$ ]]; then
            local _stagenum="$(printf '%02d' "$((10#${BASH_REMATCH[1]}))")"
            STAGES_MAP["$_stagenum"]="${BASH_REMATCH[2]}"
        fi
    done
    STAGE_NUMS=($(for k in "${!STAGES_MAP[@]}"; do echo "$k"; done | sort -n))
    TOTAL_STAGES=${#STAGE_NUMS[@]}
    log "Discovered ${TOTAL_STAGES} stages"
}

# ─── EXEC ─────────────────────────────────────────────────────────────────────
should_skip() {
    local num="$1"
    for s in "${SKIP_STAGES[@]}"; do
        [[ "$s" == "$num" ]] && return 0
    done
    [[ -n "$SINGLE_STAGE" && "$SINGLE_STAGE" != "$num" ]] && return 0
    return 1
}

run_stage() {
    local num="$1"
    local name="${STAGES_MAP[$num]}"
    local file="${STAGEDIR}/stage${num}_${name}.sh"

    if should_skip "$num"; then
        info "Stage ${num} (${name//_/ }) — skipped"
        return 0
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would run: Stage ${num} — ${name//_/ }"
        return 0
    fi

    step "${name//_/ }" "$num"

    # shellcheck disable=SC1090
    source "$file"

    local func="stage_${name}"
    if ! declare -f "$func" &>/dev/null 2>&1; then
        err "Function '${func}' not found in $(basename "$file")"
        return 1
    fi

    if "$func"; then
        ok "Stage ${num} completed"
    else
        err "Stage ${num} failed"
        handle_failure "$num"
        return 1
    fi
}

handle_failure() {
    echo -en "\n${C_YELLOW}Stage $1 failed. [R]etry [S]kip [A]bort [A]: ${C_RESET}"
    read -n1 -t 10 reply || reply="A"; echo
    case "$reply" in
        R|r) log "Retrying..."; run_stage "$1" ;;
        S|s) warn "Skipping stage $1..." ;;
        *)   err "Aborted."; exit 3 ;;
    esac
}

# ─── MAIN ─────────────────────────────────────────────────────────────────────
main() {
    require_root
    parse_args "$@"

    log_sep
    log "pop-os-setup v${SCRIPT_VERSION} — Pop!_OS 24.04"
    log "Started:  $(date)"
    log "Log:      $LOGFILE"
    log "Profile:  $PROFILE"
    log_sep


    validate_environment
    load_libraries
    discover_stages
    load_profile "$PROFILE"

    info "Running ${TOTAL_STAGES} stages (profile: ${PROFILE})..."
    for num in "${STAGE_NUMS[@]}"; do
        run_stage "$num" || exit 3
    done

    log_sep
    ok "pop-os-setup v${SCRIPT_VERSION} — ALL DONE!"
    log "Log: ${LOGFILE}"
    log_sep
}

main "$@"
