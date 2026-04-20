#!/bin/bash
#===============================================================================
# Stage 17 — Docker Compose v2 + Portainer
#===============================================================================
# Профиль: workstation, ai-dev, full
# Использует: install_docker_compose_safe() и install_portainer_safe() из lib/installer.sh
# Генерирует случайный пароль для Portainer
#===============================================================================

# Защита от повторного sourcing
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_docker_compose() {
    step "DOCKER COMPOSE v2 + PORTAINER" "17"

    # Проверка флага из профиля
    if [[ "${ENABLE_DOCKER:-0}" != "1" ]]; then
        ok "Docker Compose & Portainer skipped (ENABLE_DOCKER=0)"
        return 0
    fi

    # Проверка, что Docker установлен
    if ! command_exists docker; then
        err "Docker is not installed. Please run stage 07 first."
        return 1
    fi

    # 1. Установка Docker Compose v2
    log "Installing Docker Compose v2..."
    if install_docker_compose_safe; then
        ok "Docker Compose v2 installed successfully"
    else
        err "Failed to install Docker Compose"
        return 1
    fi

    # 2. Установка и запуск Portainer
    log "Setting up Portainer..."

    # Генерируем случайный пароль, если не задан через переменную окружения
    local portainer_password="${PORTAINER_ADMIN_PASSWORD:-$(generate_random_password 20)}"

    if install_portainer_safe "$portainer_password"; then
        ok "Portainer installed and started on http://localhost:9000"
        # Сохраняем пароль в удобном месте
        local pw_file="${HOME}/.config/pop-os-setup/.portainer_password"
        mkdir -p "${HOME}/.config/pop-os-setup"
        echo "$portainer_password" > "$pw_file"
        chmod 600 "$pw_file"

        ok "Portainer admin password has been generated and saved to:"
        ok "   ${pw_file}"
        info "You can view the password later with: cat ${pw_file}"
    else
        err "Failed to install Portainer"
        return 1
    fi

    # Финальная проверка
    if docker ps --format '{{.Names}}' | grep -q "^portainer$"; then
        ok "Portainer container is running"
    else
        warn "Portainer container is not running. Check with: docker ps"
    fi

    # Полезные команды
    info "Useful commands:"
    info "   docker compose version"
    info "   docker ps | grep portainer"
    info "   cat ~/.config/pop-os-setup/.portainer_password"

    return 0
}

# Для совместимости со старым вызовом
stage17_docker_compose() {
    stage_docker_compose "$@"
}
