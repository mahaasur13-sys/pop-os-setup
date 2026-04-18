#!/bin/bash
#===============================================================================
# Logging Library — pop-os-setup
#===============================================================================
# Functions for consistent logging across all stages
#===============================================================================

# Colors
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export MAGENTA='\033[0;35m'
export NC='\033[0m'

# Log file (set by main script)
: "${LOGFILE:=/var/log/popos-setup.log}"

#===============================================================================
# Core logging functions
#===============================================================================

log() {
    local msg="$1"
    echo -e "${BLUE}[INFO]${NC} $msg" | tee -a "$LOGFILE" 2>/dev/null || true
}

warn() {
    local msg="$1"
    echo -e "${YELLOW}[WARN]${NC} $msg" | tee -a "$LOGFILE" 2>/dev/null || true
}

err() {
    local msg="$1"
    echo -e "${RED}[ERR]${NC} $msg" | tee -a "$LOGFILE" >&2 || true
}

ok() {
    local msg="$1"
    echo -e "${GREEN}[OK]${NC} $msg" | tee -a "$LOGFILE" 2>/dev/null || true
}

step() {
    local name="$1"
    local num="${2:-}"
    if [[ -n "$num" ]]; then
        echo -e "\n${CYAN}══ STAGE $num: $name ══${NC}" | tee -a "$LOGFILE" 2>/dev/null || true
    else
        echo -e "\n${CYAN}══ $name ══${NC}" | tee -a "$LOGFILE" 2>/dev/null || true
    fi
}

info() {
    echo -e "${MAGENTA}[STEP]${NC} $1" | tee -a "$LOGFILE" 2>/dev/null || true
}

#===============================================================================
# Section header (for verbose output)
#===============================================================================

section() {
    local title="$1"
    local width=60
    local padding=$(( (width - ${#title} - 2) / 2 ))
    printf '%*s\n' "$width" '' | tr ' ' '─'
    printf "%-${width}s\n" "  $title"
    printf '%*s\n' "$width" '' | tr ' ' '─'
}

#===============================================================================
# Log command output with prefix
#===============================================================================

log_cmd() {
    local label="${1:-cmd}"
    while IFS= read -r line; do
        log "  $label: $line"
    done
}

#===============================================================================
# Capture command output to log (for verbose mode)
#===============================================================================

capture_cmd() {
    local cmd=("$@")
    local output
    output=$("${cmd[@]}" 2>&1) && return 0 || return 1
}

#===============================================================================
# Confirm action
#===============================================================================

confirm() {
    local prompt="${1:-Continue?}"
    read -rp "$prompt [y/N]: " answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

#===============================================================================
# Check if running as root
#===============================================================================

require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "This stage must be run as root (sudo)"
        return 1
    fi
    return 0
}

#===============================================================================
# Check if variable is set and non-empty
#===============================================================================

require_env() {
    local var_name="$1"
    local var_val="${!var_name}"
    if [[ -z "$var_val" ]]; then
        err "Required environment variable not set: $var_name"
        return 1
    fi
    return 0
}