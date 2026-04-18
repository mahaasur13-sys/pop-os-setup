#!/bin/bash
#===============================================================================
# Stage 2 — System Update
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_update() {
    step "SYSTEM UPDATE" "2"

    log "Updating apt package index..."
    apt update -qq

    log "Upgrading installed packages..."
    apt upgrade -y -qq 2>&1 | tail -5

    ok "System packages updated"
}