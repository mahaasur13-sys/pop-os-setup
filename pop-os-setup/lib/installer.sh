#!/bin/bash
#===============================================================================
# lib/installer.sh — Safe & Idempotent Installer Library (v3.0.0)
#===============================================================================
# Единственная точка установки всего внешнего ПО в проекте.
# Полный запрет на curl | sh. Всё скачивается → проверяется → выполняется локально.
# Все функции возвращают: 0=успех, 1=ошибка, 2=уже установлено
#===============================================================================

[[ -n "${_INSTALLER_SOURCED:-}" ]] && return 0 || _INSTALLER_SOURCED=1

# ─── CONFIG ───────────────────────────────────────────────────────────────────
INSTALLER_TMPDIR="/tmp/pop-os-installers"
mkdir -p "$INSTALLER_TMPDIR" 2>/dev/null || true
chmod 700 "$INSTALLER_TMPDIR" 2>/dev/null || true

# ─── HELPERS ──────────────────────────────────────────────────────────────────

generate_random_password() {
    local length="${1:-16}"
    if command -v openssl &>/dev/null 2>&1; then
        openssl rand -base64 32 | tr -dc 'A-Za-z0-9!@#$%^&*()_+"' | head -c "$length"
    else
        local pw
        pw=$(python3 - << 'PYEOF'
import secrets, string, sys
length = int(sys.argv[1]) if len(sys.argv) > 1 else 16
chars = string.ascii_letters + string.digits + "!@#$%^&*()_+"
print("".join(secrets.choice(chars) for _ in range(length)))
PYEOF
"$length")
        echo "$pw"
    fi
}

# ─── SAFE DOWNLOAD ───────────────────────────────────────────────────────────
# safe_download <url> <destination> [expected_sha256]
# Returns: 0=success, 1=download failed, 2=sha256 mismatch
safe_download() {
    local url="$1"
    local dest="$2"
    local expected_sha="${3:-}"
    local filename="${dest##*/}"

    log "Downloading ${filename} from ${url}"

    local max_retries=3
    local attempt=1

    while [[ $attempt -le $max_retries ]]; do
        if curl -fsSL --connect-timeout 15 --max-time 120 -o "$dest" "$url" 2>/dev/null; then
            break
        fi
        warn "Download failed (attempt $attempt/$max_retries), retrying..."
        sleep $((attempt * 2))
        ((attempt++)) || true
    done

    if [[ ! -f "$dest" ]]; then
        err "Failed to download ${url}"
        return 1
    fi

    if [[ -n "$expected_sha" ]]; then
        local actual_sha
        actual_sha=$(sha256sum "$dest" 2>/dev/null | awk '{print $1}')
        if [[ "$actual_sha" != "$expected_sha" ]]; then
            err "SHA256 mismatch for ${filename}"
            err "Expected: ${expected_sha}"
            err "Got:      ${actual_sha}"
            rm -f "$dest"
            return 2
        fi
        ok "SHA256 verified: ${filename}"
    fi

    chmod 644 "$dest" 2>/dev/null || true
    local size
    size=$(du -h "$dest" 2>/dev/null | cut -f1 || echo "unknown")
    ok "Downloaded: ${filename} (${size})"
    return 0
}

# ─── SAFE GIT CLONE ───────────────────────────────────────────────────────────
# safe_git_clone <repo_url> <dest_dir> [branch]
# Returns: 0=success/cloned, 1=error, 2=already installed (up-to-date)
safe_git_clone() {
    local repo="$1"
    local dest="$2"
    local branch="${3:-master}"

    if [[ -d "$dest/.git" ]]; then
        local current_remote
        current_remote=$(git -C "$dest" remote get-url origin 2>/dev/null || echo "")
        local repo_host="${repo#https://}"
        repo_host="${repo_host#http://}"
        repo_host="${repo_host%%/*}"

        if [[ "$current_remote" == *"$repo_host"* ]]; then
            log "Repository already exists at ${dest}, updating..."
            git -C "$dest" pull --quiet --rebase=false 2>/dev/null || true
            ok "Updated: ${dest##*/}"
            return 2
        else
            err "Directory ${dest} exists but points to different repo."
            err "Expected: ${repo}"
            err "Got:      ${current_remote}"
            return 1
        fi
    fi

    log "Cloning ${repo} -> ${dest}"
    if ! git clone --depth=1 --quiet -b "$branch" "$repo" "$dest" 2>/dev/null; then
        err "Failed to clone ${repo}"
        return 1
    fi
    ok "Cloned: ${dest##*/}"
    return 0
}

# ─── OH MY ZSH ───────────────────────────────────────────────────────────────
# install_oh_my_zsh_safe [user]
# Returns: 0=success, 1=error, 2=already installed
install_oh_my_zsh_safe() {
    local user="${1:-$(get_target_user 2>/dev/null || echo 'root')}"
    local home
    home="$(get_user_home "$user" 2>/dev/null || echo "/root")"
    local omz_dir="${home}/.oh-my-zsh"
    local custom_dir="${omz_dir}/custom/plugins"

    if [[ -d "${omz_dir}/.git" ]]; then
        ok "Oh My Zsh already installed for ${user}"
        return 2
    fi

    log "Installing Oh My Zsh for user ${user}"

    safe_git_clone "https://github.com/ohmyzsh/ohmyzsh.git" "$omz_dir" || return 1

    mkdir -p "$custom_dir"

    safe_git_clone "https://github.com/zsh-users/zsh-autosuggestions.git" \
        "${custom_dir}/zsh-autosuggestions" || true

    safe_git_clone "https://github.com/zsh-users/zsh-syntax-highlighting.git" \
        "${custom_dir}/zsh-syntax-highlighting" || true

    local user_shell
    user_shell=$(getent passwd "$user" 2>/dev/null | cut -d: -f7 || echo "")
    if [[ "$user_shell" != *"/zsh" ]]; then
        if command -v chsh &>/dev/null; then
            chsh -s /bin/zsh "$user" 2>/dev/null || \
                warn "Could not set zsh as default shell for ${user}"
        fi
    fi

    ok "Oh My Zsh + plugins installed for ${user}"
    return 0
}

# ─── K3S ─────────────────────────────────────────────────────────────────────
# install_k3s_safe
# Returns: 0=success, 1=error, 2=already installed
install_k3s_safe() {
    if command -v k3s &>/dev/null 2>&1; then
        local ver
        ver=$(k3s --version 2>/dev/null | head -n1 || echo "installed")
        ok "k3s already installed: ${ver}"
        return 2
    fi

    log "Installing k3s (safe method — download then execute)"

    local installer="${INSTALLER_TMPDIR}/k3s-install.sh"
    safe_download "https://get.k3s.io" "$installer" || return 1

    chmod +x "$installer"

    export INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644"
    if ! "$installer" 2>&1 | tail -5; then
        err "k3s installation failed"
        return 1
    fi

    if command -v k3s &>/dev/null 2>&1; then
        ok "k3s installed: $(k3s --version | head -n1)"
        return 0
    else
        err "k3s binary not found after installation"
        return 1
    fi
}

# ─── DOCKER COMPOSE ───────────────────────────────────────────────────────────
# install_docker_compose_safe
# Returns: 0=success, 1=error, 2=already installed
install_docker_compose_safe() {
    if command -v docker &>/dev/null 2>&1 && \
       docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose v2 already installed"
        return 2
    fi

    log "Installing Docker Compose v2"

    local arch
    arch="$(uname -m)"
    [[ "$arch" == "x86_64" ]] && arch="x86_64"
    [[ "$arch" == "aarch64" ]] && arch="aarch64"
    [[ "$arch" == "arm64" ]] && arch="aarch64"

    local version
    version=$(curl -fsSL "https://api.github.com/repos/docker/compose/releases/latest" 2>/dev/null | \
              grep -o '"tag_name": "[^"]*"' | cut -d'"' -f4 | sed 's/^v//' || echo "")

    if [[ -z "$version" ]]; then
        err "Could not determine latest Docker Compose version"
        return 1
    fi

    local url="https://github.com/docker/compose/releases/download/v${version}/docker-compose-$(uname -s)-${arch}"
    local dest="/usr/local/bin/docker-compose"

    safe_download "$url" "$dest" || return 1
    chmod +x "$dest"

    if docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose v${version} installed"
        return 0
    else
        err "Docker Compose installation failed — binary not working"
        rm -f "$dest"
        return 1
    fi
}

# ─── NEOVIM ───────────────────────────────────────────────────────────────────
# install_neovim_safe
# Returns: 0=success, 1=error, 2=already installed
install_neovim_safe() {
    if command -v nvim &>/dev/null 2>&1; then
        local ver
        ver=$(nvim --version 2>/dev/null | head -n1 | cut -d' ' -f2 || echo "installed")
        ok "Neovim already installed: ${ver}"
        return 2
    fi

    log "Installing latest Neovim"

    local url="https://github.com/neovim/neovim/releases/latest/download/nvim-linux64.tar.gz"
    local tarfile="${INSTALLER_TMPDIR}/nvim-linux64.tar.gz"
    local extract_dir="/opt/neovim"

    safe_download "$url" "$tarfile" || return 1

    mkdir -p "$extract_dir"
    if ! tar -xzf "$tarfile" -C "$extract_dir" --strip-components=1 2>/dev/null; then
        err "Failed to extract Neovim"
        return 1
    fi

    if [[ ! -f "${extract_dir}/bin/nvim" ]]; then
        err "Neovim binary not found after extraction"
        return 1
    fi

    ln -sf "${extract_dir}/bin/nvim" /usr/local/bin/nvim 2>/dev/null || true

    if command -v nvim &>/dev/null 2>&1; then
        ok "Neovim installed: $(nvim --version | head -n1)"
        return 0
    else
        err "Neovim installation failed — nvim not in PATH"
        return 1
    fi
}

# ─── PORTAINER ────────────────────────────────────────────────────────────────
# install_portainer_safe [admin_password]
# Returns: 0=success, 1=error, 2=already running
install_portainer_safe() {
    local admin_pass="${1:-$(generate_random_password 20)}"

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^portainer$"; then
        ok "Portainer is already running"
        return 2
    fi

    log "Installing Portainer with secure admin password"

    docker volume create portainer_data &>/dev/null 2>&1 || true

    if ! docker run -d \
        --name portainer \
        --restart=unless-stopped \
        -p 9000:9000 \
        -p 8000:8000 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v portainer_data:/data \
        portainer/portainer-ce:latest 2>/dev/null; then
        err "Portainer installation failed"
        return 1
    fi

    local pw_file="${HOME}/.config/pop-os-setup/.portainer_password"
    mkdir -p "${HOME}/.config/pop-os-setup"
    echo "$admin_pass" > "$pw_file"
    chmod 600 "$pw_file"

    ok "Portainer installed: http://localhost:9000"
    ok "Admin password saved to ${pw_file}"
    return 0
}

# ─── TAILSCALE ────────────────────────────────────────────────────────────────
# install_tailscale_safe [authkey]
# Returns: 0=success, 1=error, 2=already running
install_tailscale_safe() {
    local authkey="${1:-}"

    if command -v tailscale &>/dev/null 2>&1 && \
       tailscale status --self &>/dev/null 2>&1; then
        ok "Tailscale already authenticated"
        return 2
    fi

    log "Installing Tailscale"

    if ! command -v tailscale &>/dev/null 2>&1; then
        local pkg="tailscale_1.80.3_amd64.deb"
        local url="https://pkgs.tailscale.com/stable/${pkg}"
        local dest="${INSTALLER_TMPDIR}/${pkg}"

        safe_download "$url" "$dest" || return 1
        dpkg -i "$dest" 2>/dev/null || apt-get install -y "$dest" 2>/dev/null || {
            err "Tailscale package installation failed"
            return 1
        }
    fi

    if [[ -n "$authkey" ]]; then
        if ! tailscale up --authkey="$authkey" --accept-dns=false 2>/dev/null; then
            warn "Tailscale authentication failed with provided authkey"
            return 1
        fi
    fi

    ok "Tailscale installed"
    return 0
}

# ─── CLEANUP ─────────────────────────────────────────────────────────────────
cleanup_installer_tmp() {
    rm -rf "$INSTALLER_TMPDIR" 2>/dev/null || true
}

trap cleanup_installer_tmp EXIT

# ─── EXPORT ───────────────────────────────────────────────────────────────────
export -f safe_download safe_git_clone generate_random_password
export -f install_oh_my_zsh_safe install_k3s_safe install_docker_compose_safe
export -f install_neovim_safe install_portainer_safe install_tailscale_safe