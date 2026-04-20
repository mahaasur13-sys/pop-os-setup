#!/bin/bash
# lib/logging.sh — Logging functions for pop-os-setup v3.0.0

_setup_colors() {
    if command -v tput &>/dev/null 2>&1 && [[ $(tput colors 2>/dev/null) -ge 8 ]]; then
        C_RESET="$(tput sgr0)"; C_BOLD="$(tput bold)"
        C_RED="$(tput setaf 1)"; C_GREEN="$(tput setaf 2)"
        C_YELLOW="$(tput setaf 3)"; C_CYAN="$(tput setaf 6)"
    else
        C_RESET='\033[0m'; C_BOLD='\033[1m'
        C_RED='\033[31m'; C_GREEN='\033[32m'
        C_YELLOW='\033[33m'; C_CYAN='\033[36m'
    fi
}
_setup_colors

# Guard: if already sourced, skip
[[ -n "${_LOGGING_SOURCED:-}" ]] && return 0 || _LOGGING_SOURCED=1

log()   { echo -e "${C_CYAN}[$(date '+%H:%M:%S')]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
ok()    { echo -e "${C_GREEN}[OK]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
warn()  { echo -e "${C_YELLOW}[WARN]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
err()   { echo -e "${C_RED}[ERR]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
info()  { echo -e "${C_CYAN}[INFO]${C_RESET} $*" | tee -a "$LOGFILE" 2>/dev/null || true; }
step()  {
    printf '\n'
    printf '=%.0s' {1..70}; printf '\n'
    printf "  STAGE %s | %s\n" "$2" "$1"
    printf '=%.0s' {1..70}; printf '\n\n'
}
log_sep(){
    printf '=%.0s\n' {1..70}
}
