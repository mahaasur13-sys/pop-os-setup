#!/bin/bash
#===============================================================================
# Stage 1 — Pre-Flight Checks
#===============================================================================
# Validates environment before any installation begins
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_preflight() {
    step "PRE-FLIGHT CHECKS" "1"

    require_root || exit 1

    log "Script version: $SCRIPT_VERSION"
    log "User: $(get_current_user) | Home: $HOMEDIR"
    log "Log file: $LOGFILE"

    # Detect OS
    local os
    os=$(detect_os)
    log "Detected OS: $os"
    if ! is_pop_os; then
        warn "Not Pop!_OS — continuing anyway..."
    fi

    # Check for required commands
    local required_cmds="apt curl wget git"
    for cmd in $required_cmds; do
        if ! command -v "$cmd" &>/dev/null; then
            err "Missing required command: $cmd"
            exit 1
        fi
    done
    ok "Required commands present"

    # Check network
    if wait_for_network 10; then
        ok "Network connectivity confirmed"
    else
        warn "No internet connectivity — some stages may fail"
    fi

    # Check disk space (minimum 20GB)
    local available
    available=$(df -BG / | awk 'NR==2 {print $4}' | tr -d 'G')
    if (( available < 20 )); then
        err "Insufficient disk space: ${available}GB (minimum 20GB required)"
        exit 1
    fi
    ok "Disk space: ${available}GB available"

    # Check existing NVIDIA
    if has_nvidia; then
        ok "NVIDIA detected: $(nvidia_info)"
    else
        warn "No NVIDIA GPU detected — GPU stages will be skipped"
    fi

    ok "Pre-flight checks passed"
}