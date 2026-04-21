#!/bin/bash
#===============================================================================
# lib/installer/docker.sh — Docker installer module (v4.0.0)
#===============================================================================

[[ -n "${_INSTALLER_DOCKER_SOURCED:-}" ]] && return 0

source "${LIBDIR}/installer/_shared.sh"
_INSTALLER_DOCKER_SOURCED=1

# ─── DOCKER ENGINE ──────────────────────────────────────────────────────────
# install_docker_if_needed
# Idempotent: checks docker --version first
install_docker_if_needed() {
    if command -v docker &>/dev/null && docker --version &>/dev/null; then
        ok "Docker already installed: $(docker --version | cut -d' ' -f3 | tr -d ',')"
        return 2  # already done
    fi

    log "Installing Docker Engine..."

    local pkg=(
        apt-transport-https
        ca-certificates
        curl
        gnupg
        lsb-release
    )
    for p in "${pkg[@]}"; do
        apt-get install -y "$p" &>/dev/null || true
    done

    # Add Docker GPG key (idempotent)
    install -m 0755 -d /etc/apt/keyrings 2>/dev/null || true
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg 2>/dev/null \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null || true
    chmod a+r /etc/apt/keyrings/docker.gpg 2>/dev/null || true

    local arch="$(uname -m)"
    [[ "$arch" == "x86_64" ]] && arch="amd64"
    [[ "$arch" == "aarch64" ]] && arch="arm64"

    local codename
    codename=$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-focal}")

    echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $codename stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null || {
        # Fallback: install from distro packages
        apt-get install -y docker.io docker-compose 2>/dev/null || {
            err "Docker installation failed"
            return 1
        }
    }

    # Enable and start
    systemctl enable docker 2>/dev/null || true
    systemctl start docker 2>/dev/null || true

    ok "Docker installed: $(docker --version | cut -d' ' -f3 | tr -d ',')"
    return 0
}

# ─── DOCKER COMPOSE v2 ──────────────────────────────────────────────────────
# install_docker_compose_if_needed
# No GitHub API parsing — uses compose-plugin (bundled with docker-ce)
install_docker_compose_if_needed() {
    # docker compose v2 is part of docker-compose-plugin package
    # Check via plugin first
    if docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose v2 already installed"
        return 2
    fi

    # Fallback: standalone binary (pinned URL, no API call)
    log "Installing Docker Compose v2 standalone..."

    local arch="$(uname -m)"
    [[ "$arch" == "x86_64" ]] && arch="x86_64"
    [[ "$arch" == "aarch64" ]] && arch="aarch64"
    [[ "$arch" == "armv7l" ]] && arch="armv7"

    # Pin to known stable version — update manually when needed
    local version="v2.24.0"
    local url="https://github.com/docker/compose/releases/download/${version}/docker-compose-linux-${arch}"
    local dest="/usr/local/bin/docker-compose"

    safe_download "$url" "$dest" || return 1
    chmod +x "$dest"

    if ! docker compose version &>/dev/null 2>&1; then
        err "Docker Compose installation failed"
        rm -f "$dest"
        return 1
    fi

    ok "Docker Compose ${version} installed"
    return 0
}

export -f install_docker_if_needed install_docker_compose_if_needed
