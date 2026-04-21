#!/bin/bash
#===============================================================================
# Stage 17 — Docker Compose + Portainer (v4.0.0)
#===============================================================================
# Профиль: workstation, ai-dev, full
# Контракт: requires docker_ready, provides compose_ready + portainer_ready
#===============================================================================

[[ "${_STAGE_SOURCED:-}" == "yes" ]] && return 0
_STAGE_SOURCED=yes

# ─── STAGE FUNCTION ──────────────────────────────────────────────────────────
stage_docker_compose() {
    step "DOCKER COMPOSE + PORTAINER" "17"

    # 1. Check flag FIRST (idempotent)
    if ! skip_if_disabled "DOCKER_COMPOSE"; then
        return 0
    fi

    # 2. Load installer (only now — after flag check)
    if ! load_installer docker; then
        err "Failed to load docker installer module"
        return 1
    fi

    # 3. Idempotency check
    if is_installed "docker" && docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose v2 already installed — skipping"
        return 0
    fi

    # 4. Install Docker Engine (if needed)
    install_docker_if_needed || {
        err "Docker installation failed"
        return 1
    }

    # 5. Install Docker Compose v2
    install_docker_compose_if_needed || {
        err "Docker Compose installation failed"
        return 1
    }

    # 6. Docker post-install: add user to docker group
    local target_user
    target_user="$(get_target_user 2>/dev/null || echo 'root')"

    if [[ "$target_user" != "root" ]] && ! groups "$target_user" 2>/dev/null | grep -qw docker; then
        usermod -aG docker "$target_user" 2>/dev/null || true
        ok "User ${target_user} added to docker group"
    fi

    # 7. Install Portainer (optional)
    if [[ "${ENABLE_PORTAINER:-0}" == "1" ]]; then
        install_portainer_if_needed || true
    fi

    # 8. Verify
    if docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose $(docker compose version | awk '{print $3}') ready"
    else
        err "Docker Compose verification failed"
        return 1
    fi

    ok "Docker Compose stage complete"
    return 0
}

# ─── INSTALLER HELPERS (inline, no external dependencies) ────────────────────

install_portainer_if_needed() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^portainer$"; then
        ok "Portainer already running"
        return 2
    fi

    log "Installing Portainer..."

    docker volume create portainer_data &>/dev/null 2>&1 || true

    if docker run -d \
        --name portainer \
        --restart=unless-stopped \
        -p 9000:9000 \
        -p 8000:8000 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v portainer_data:/data \
        portainer/portainer-ce:latest 2>/dev/null; then
        ok "Portainer installed: http://localhost:9000"
    else
        warn "Portainer installation failed (continuing)"
        return 1
    fi

    return 0
}

stage17_docker_compose() { stage_docker_compose "$@"; }
