#!/bin/bash
#===============================================================================
# Stage 17 — Docker Compose + Portainer UI
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_docker_compose() {
    step "DOCKER COMPOSE + PORTAINER" "17"

    if [[ "${ENABLE_DOCKER:-0}" != "1" ]]; then
        ok "Docker skipped"
        return 0
    fi

    # Docker Compose v2
    if command -v docker &>/dev/null; then
        if command -v docker compose &>/dev/null; then
            ok "Docker Compose v2 available"
        else
            log "Installing Docker Compose..."
            sudo apt install -y docker-compose-v2 2>/dev/null || \
            sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
                -o /usr/local/bin/docker-compose && \
            sudo chmod +x /usr/local/bin/docker-compose
        fi
    fi

    # Portainer (Docker management UI)
    if command -v docker &>/dev/null && [[ -n "${DOCKER_HOST:-}" ]] || docker info &>/dev/null; then
        log "Deploying Portainer..."
        docker volume create portainer_data 2>/dev/null || true
        docker run -d --name portainer \
            --restart unless-stopped \
            -p 9000:9000 \
            -p 8000:8000 \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v portainer_data:/data \
            portainer/portainer-ce:latest 2>/dev/null || true
        ok "Portainer: http://localhost:9000"
    fi

    ok "Docker Compose + Portainer configured"
}

stage17_docker_compose() { stage_docker_compose; }