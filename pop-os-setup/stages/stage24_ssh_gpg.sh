#!/bin/bash
#===============================================================================
# Stage 24 — SSH Keys + GPG + YubiKey Configuration
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_ssh_gpg() {
    step "SSH KEYS + GPG + YUBIKEY" "24"

    if [[ "${ENABLE_SSH:-0}" != "1" ]]; then
        ok "SSH configuration skipped"
        return 0
    fi

    # SSH key generation
    local ssh_dir="${HOME}/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    if [[ ! -f "${ssh_dir}/id_ed25519" ]]; then
        log "Generating ED25519 SSH key..."
        ssh-keygen -t ed25519 -C "$(hostname)-$(date +%Y%m%d)" -f "${ssh_dir}/id_ed25519" -N "" 2>/dev/null || true
        ok "SSH key: ${ssh_dir}/id_ed25519"
    fi

    # SSH config
    cat > "${ssh_dir}/config" << 'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519
    AddKeysToAgent yes

Host gitlab.com
    HostName gitlab.com
    User git
    IdentityFile ~/.ssh/id_ed25519

Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
EOF

    # GPG smart card (YubiKey)
    if command -v gpg &>/dev/null; then
        if gpg --card-status 2>/dev/null | grep -q "Yubikey"; then
            log "YubiKey detected — enabling GPG agent..."
            export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket 2>/dev/null)
            ok "GPG/YubiKey agent configured"
        fi
    fi

    chmod 600 "${ssh_dir}/config" "${ssh_dir}/id_ed25519" 2>/dev/null || true
    ok "SSH + GPG configured"
}

stage24_ssh_gpg() { stage_ssh_gpg; }