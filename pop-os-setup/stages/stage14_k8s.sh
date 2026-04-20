#!/bin/bash
#===============================================================================
# Stage 14 — k3s Kubernetes (Single Node)
#===============================================================================
# Профиль: full, cluster
# Использует: install_k3s_safe() из lib/installer.sh
# Устанавливает k3s без pipe-to-shell
#===============================================================================

# Защита от повторного sourcing
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_k8s() {
    step "K3S KUBERNETES (Single Node)" "14"

    if [[ "${ENABLE_K8S:-0}" != "1" ]]; then
        ok "k3s installation skipped (ENABLE_K8S=0)"
        return 0
    fi

    # Проверка Docker (k3s может работать и без него, но мы рекомендуем)
    if ! command_exists docker; then
        warn "Docker is not installed. k3s can run without it, but some features may be limited."
    fi

    # Проверка, установлен ли уже k3s
    if command_exists k3s; then
        ok "k3s already installed: $(k3s --version | head -n1)"
        return 2
    fi

    log "Starting secure k3s installation..."

    # Используем безопасную функцию из lib/installer.sh
    if install_k3s_safe; then
        ok "k3s installed successfully"

        # Ждём запуска
        log "Waiting for k3s to start..."
        sleep 8

        # Проверка статуса
        if systemctl is-active --quiet k3s; then
            ok "k3s service is active"
        else
            warn "k3s service is not active. Check status with: systemctl status k3s"
        fi

        # Настройка kubeconfig для текущего пользователя
        local target_user
        target_user="$(get_target_user)"
        local user_home
        user_home="$(get_user_home "$target_user")"

        if [[ -f "/etc/rancher/k3s/k3s.yaml" ]]; then
            mkdir -p "${user_home}/.kube"
            cp /etc/rancher/k3s/k3s.yaml "${user_home}/.kube/config"
            chown -R "$target_user:$target_user" "${user_home}/.kube"
            chmod 600 "${user_home}/.kube/config"
            ok "kubeconfig copied to ${user_home}/.kube/config"
            info "You can now use kubectl with: export KUBECONFIG=~/.kube/config"
        fi

        # Полезные команды
        info "Useful commands:"
        info "   kubectl get nodes"
        info "   kubectl get pods -A"
        info "   k3s kubectl get all -A"
        info "   systemctl status k3s"
        return 0
    else
        err "k3s installation failed"
        return 1
    fi
}

# Для совместимости со старым вызовом
stage14_k8s() {
    stage_k8s "$@"
}
