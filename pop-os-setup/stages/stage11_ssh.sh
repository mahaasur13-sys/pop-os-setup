#!/bin/bash
#===============================================================================
# Stage 11 — SSH Server
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_ssh() {
    step "SSH SERVER" "11"

    if [[ "${ENABLE_SSH:-0}" != "1" ]]; then
        ok "SSH server skipped"
        return 0
    fi

    if command -v sshd &>/dev/null; then
        ok "SSH server already installed"
    else
        log "Installing OpenSSH server..."
        apt install -y openssh-server 2>&1 | tail -3
    fi

    enable_service ssh
    ok "SSH server enabled"
    log "Config: /etc/ssh/sshd_config (consider key-based auth)"
}

stage10_ssh() { stage_ssh; }