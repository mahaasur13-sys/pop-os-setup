#!/bin/bash
#===============================================================================
# Stage 05 — Zsh + Oh My Zsh + Useful Plugins
#===============================================================================
# Профиль: все (workstation, ai-dev, full, cluster)
# Использует: install_oh_my_zsh_safe из lib/installer.sh
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_zsh() {
    step "ZSH + OH MY ZSH" "05"

    # Проверка флага из профиля
    if [[ "${ENABLE_ZSH:-1}" != "1" ]]; then
        ok "Zsh installation skipped (ENABLE_ZSH=0)"
        return 0
    fi

    local target_user
    target_user="$(get_target_user)"

    if [[ -z "$target_user" || "$target_user" == "root" ]]; then
        err "Could not determine target non-root user for Zsh installation"
        return 1
    fi

    log "Installing Zsh + Oh My Zsh for user: ${target_user}"

    # Проверка, установлен ли уже zsh
    if ! pkg_installed zsh; then
        log "Installing zsh package..."
        apt-get update -qq && apt-get install -y zsh || {
            err "Failed to install zsh package"
            return 1
        }
        ok "zsh package installed"
    else
        ok "zsh package already installed"
    fi

    # Основная установка Oh My Zsh через безопасную функцию
    if install_oh_my_zsh_safe; then
        # Дополнительные настройки .zshrc (опционально)
        local home
        home="$(get_user_home "$target_user")"

        if [[ -f "${home}/.zshrc" ]]; then
            append_once "${home}/.zshrc" "ZSH_CUSTOM=\${ZSH_CUSTOM:-\$HOME/.oh-my-zsh/custom}"
            append_once "${home}/.zshrc" "plugins=(git zsh-autosuggestions zsh-syntax-highlighting)"
        fi

        ok "Zsh + Oh My Zsh successfully configured for ${target_user}"
        ok "Default shell for ${target_user} is now zsh"

        # Напоминание пользователю
        if [[ "$target_user" != "$(whoami)" ]]; then
            info "Note: Run 'chsh -s /bin/zsh ${target_user}' manually if needed after reboot"
        fi
    else
        err "Failed to install Oh My Zsh"
        return 1
    fi

    return 0
}

# Для совместимости со старым вызовом
stage05_zsh() {
    stage_zsh "$@"
}