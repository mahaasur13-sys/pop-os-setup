#!/bin/bash
#===============================================================================
# Stage 7 — Docker
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_docker() {
    step "DOCKER" "7"

    if command -v docker &>/dev/null; then
        ok "Docker already installed: $(docker --version)"
        if docker ps &>/dev/null; then
            ok "Docker daemon running"
        else
            warn "Docker installed but not running — restarting..."
            restart_docker
        fi
        return 0
    fi

    log "Installing Docker..."
    apt install -y docker.io docker-compose-v2 2>&1 | tail -3

    local user="${CURRENT_USER:-$(get_current_user)}"
    usermod -aG docker "$user"

    enable_service docker
    restart_docker

    if docker ps &>/dev/null; then
        ok "Docker installed and running"
    else
        err "Docker installation failed"
        return 1
    fi
}

# Stub for back-compat
stage6_docker() { stage_docker; }