#!/bin/bash
#===============================================================================
# Stage 24 — SSH Keys + GPG + YubiKey Configuration
#===============================================================================
# Профиль: workstation, ai-dev, full
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

_STAGE_SOURCED=yes

# ----------------------------------------------------------------------------
# Внутренняя функция: генерация SSH ключа с passphrase
# ----------------------------------------------------------------------------
_generate_ssh_key() {
    local key_path="$1"
    local passphrase="$2"

    log "Generating ED25519 SSH key: ${key_path}"

    # ssh-keygen требует passphrase через stdin или -N (не через pipe)
    # Используем expect-подобный подход через /dev/stdin
    printf '%s\n%s\n' "$passphrase" "$passphrase" | \
        ssh-keygen -t ed25519 \
            -C "$(hostname)-$(date +%Y%m%d)" \
            -f "$key_path" \
            -o -a 100 \
            2>/dev/null

    if [[ -f "${key_path}" ]]; then
        chmod 600 "${key_path}"
        chmod 644 "${key_path}.pub"
        ok "SSH key created: ${key_path}"
        return 0
    else
        err "Failed to generate SSH key"
        return 1
    fi
}

# ----------------------------------------------------------------------------
# Внутренняя функция: настройка SSH config (добавляет блоки, не перезаписывает)
# ----------------------------------------------------------------------------
_configure_ssh_config() {
    local ssh_config="$1"

    # Создаём backup если существует
    [[ -f "$ssh_config" ]] && backup_file "$ssh_config"

    # Github block
    append_once "$ssh_config" "Host github.com" || true
    append_once "$ssh_config" "    HostName github.com" || true
    append_once "$ssh_config" "    User git" || true
    append_once "$ssh_config" "    IdentityFile ~/.ssh/id_ed25519" || true
    append_once "$ssh_config" "    AddKeysToAgent yes" || true
    append_once "$ssh_config" "    IdentitiesOnly yes" || true

    # Gitlab block
    append_once "$ssh_config" "Host gitlab.com" || true
    append_once "$ssh_config" "    HostName gitlab.com" || true
    append_once "$ssh_config" "    User git" || true
    append_once "$ssh_config" "    IdentityFile ~/.ssh/id_ed25519" || true

    # Global defaults
    append_once "$ssh_config" "Host *" || true
    append_once "$ssh_config" "    ServerAliveInterval 60" || true
    append_once "$ssh_config" "    ServerAliveCountMax 3" || true
    append_once "$ssh_config" "    TCPKeepAlive yes" || true

    chmod 600 "$ssh_config"
}

# ----------------------------------------------------------------------------
# Основная stage-функция
# ----------------------------------------------------------------------------
stage_ssh_gpg() {
    step "SSH KEYS + GPG + YUBIKEY" "24"

    # Проверка флага из профиля
    if [[ "${ENABLE_SSH:-0}" != "1" ]]; then
        ok "SSH configuration skipped (ENABLE_SSH=0)"
        return 0
    fi

    # Определяем целевого пользователя
    local target_user
    target_user="$(get_target_user)"

    if [[ -z "$target_user" || "$target_user" == "root" ]]; then
        err "Cannot determine target non-root user for SSH configuration"
        return 1
    fi

    local home
    home="$(get_user_home "$target_user")"

    if [[ -z "$home" || "$home" == "/" ]]; then
        err "Invalid home directory for user: ${target_user}"
        return 1
    fi

    log "Configuring SSH + GPG for user: ${target_user}"

    local ssh_dir="${home}/.ssh"
    local ssh_config="${ssh_dir}/config"
    local key_path="${ssh_dir}/id_ed25519"

    # Создаём .ssh с правильными правами
    ensure_dir "$ssh_dir"
    chmod 700 "$ssh_dir"
    chown "${target_user}:${target_user}" "$ssh_dir"

    # ─── SSH Key ────────────────────────────────────────────────────────────
    if [[ ! -f "$key_path" ]]; then
        if [[ -z "${SSH_PASSPHRASE:-}" ]]; then
            warn "SSH_PASSPHRASE not set — generating random secure passphrase"
            local passphrase
            passphrase="$(generate_random_password 32)"
            export SSH_PASSPHRASE="$passphrase"
            info "Passphrase saved to SSH_PASSPHRASE env var"
        else
            passphrase="$SSH_PASSPHRASE"
        fi

        if ! _generate_ssh_key "$key_path" "$passphrase"; then
            err "SSH key generation failed"
            return 1
        fi

        # Сохраняем passphrase для пользователя
        local pass_file="${home}/.config/pop-os-setup/.ssh_passphrase"
        ensure_dir "$(dirname "$pass_file")"
        echo "$passphrase" > "$pass_file"
        chmod 600 "$pass_file"
        chown "${target_user}:${target_user}" "$pass_file"
        ok "SSH passphrase stored securely in ${pass_file}"
    else
        ok "SSH key already exists: ${key_path}"
    fi

    # Устанавливаем владельца на ключи
    chown "${target_user}:${target_user}" "${key_path}" "${key_path}.pub" 2>/dev/null || true

    # ─── SSH Config ──────────────────────────────────────────────────────────
    _configure_ssh_config "$ssh_config"
    chown "${target_user}:${target_user}" "$ssh_config" 2>/dev/null || true
    ok "SSH config updated: ${ssh_config}"

    # ─── SSH Agent ──────────────────────────────────────────────────────────
    # Добавляем ключ в agent при логине пользователя
    local bashrc="${home}/.bashrc"
    local ssh_add_line="[[ -z \"\$SSH_AUTH_SOCK\" ]] && ssh-add ~/.ssh/id_ed25519 2>/dev/null || true"

    if [[ -f "$bashrc" ]]; then
        append_once "$bashrc" "# SSH agent — add key on login" || true
        append_once "$bashrc" "$ssh_add_line" || true
    fi

    # ─── GPG + YubiKey ───────────────────────────────────────────────────────
    if command -v gpg &>/dev/null; then
        local card_info
        card_info=$(gpg --card-status 2>/dev/null || echo "")

        if echo "$card_info" | grep -qi "yubikey\|yko"; then
            log "YubiKey detected — configuring GPG agent for SSH"

            local gpg_agent_conf="${home}/.gnupg/gpg-agent.conf"
            ensure_dir "${home}/.gnupg"
            chmod 700 "${home}/.gnupg"

            append_once "$gpg_agent_conf" "enable-ssh-support" || true
            append_once "$gpg_agent_conf" "pinentry-program /usr/bin/pinentry-gtk-2" || true
            append_once "$gpg_agent_conf" "default-cache-ttl 3600" || true

            export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket 2>/dev/null || echo "")
            ok "GPG/YubiKey SSH agent configured"
            ok "SSH_AUTH_SOCK=${SSH_AUTH_SOCK}"
        else
            ok "No YubiKey detected — GPG card not present"
        fi
    else
        warn "GPG not installed — skipping YubiKey configuration"
    fi

    # ─── Публичный ключ ──────────────────────────────────────────────────────
    if [[ -f "${key_path}.pub" ]]; then
        local pub_key
        pub_key=$(cat "${key_path}.pub" 2>/dev/null)
        ok "Public key (add to GitHub/GitLab):"
        echo ""
        echo "  ${pub_key}"
        echo ""
    fi

    ok "SSH + GPG stage complete for ${target_user}"
    return 0
}

# Совместимость со старым вызовом
stage24_ssh_gpg() {
    stage_ssh_gpg "$@"
}
