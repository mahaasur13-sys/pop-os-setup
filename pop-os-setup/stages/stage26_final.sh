#!/bin/bash
#===============================================================================
# Stage 26 — Final Verification & Report
#===============================================================================
# Профиль: все (workstation, ai-dev, full, cluster)
# Выводит красивый итоговый отчёт после завершения установки
# Использует: step, ok, warn, err, info, log, log_sep из lib/logging.sh
#             get_target_user, has_nvidia, command_exists, is_service_active из lib/utils.sh
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

_STAGE_SOURCED=yes

stage_final() {
    step "FINAL VERIFICATION & REPORT" "26"

    log_sep
    ok "pop-os-setup v3.0.0 — installation complete!"
    log_sep
    info "Pop!_OS 24.04 NVIDIA — Automated Setup & Hardening"
    log ""

    # ─── 1. System Information ─────────────────────────────────────────────
    info "System Information:"
    log "   Hostname      : $(hostname)"
    log "   Kernel        : $(uname -r)"
    log "   OS            : $(detect_os 2>/dev/null || echo 'Linux')"
    log "   User          : $(get_target_user) (logged in: $(whoami))"
    log "   Profile       : ${PROFILE:-default}"
    log "   Completed at  : $(date '+%Y-%m-%d %H:%M:%S %Z')"

    # ─── 2. Installed Components ────────────────────────────────────────────
    log_sep
    info "Installed Components:"

    command_exists zsh       && ok "Zsh + Oh My Zsh"        || warn "Zsh"
    command_exists nvim     && ok "Neovim (latest)"         || warn "Neovim"
    command_exists docker    && ok "Docker + Compose"       || warn "Docker"
    command_exists k3s      && ok "k3s Kubernetes"         || warn "k3s"
    command_exists tailscale && ok "Tailscale VPN"          || warn "Tailscale"
    has_nvidia               && ok "NVIDIA Drivers + CUDA"  || warn "NVIDIA / CUDA"

    if command_exists ufw; then
        local ufw_st
        ufw_st=$(ufw status 2>/dev/null | head -1 || echo "unknown")
        ok "UFW Firewall (${ufw_st})"
    else
        warn "UFW Firewall"
    fi

    command_exists fail2ban && ok "fail2ban" || warn "fail2ban"

    # ─── 3. Service Status ─────────────────────────────────────────────────
    log_sep
    info "Service Status:"

    is_service_active docker      && ok "Docker"      || warn "Docker daemon"
    is_service_active fail2ban    && ok "fail2ban"    || warn "fail2ban"
    is_service_active tailscaled  && ok "Tailscale"   || warn "Tailscale daemon"
    is_service_active k3s         && ok "k3s"         || warn "k3s"

    # ─── 4. Running Containers (если есть) ─────────────────────────────────
    if command_exists docker && docker ps &>/dev/null 2>&1; then
        log_sep
        info "Running Containers:"
        docker ps --format "   • {{.Names}} ({{.Image}}) : {{.Status}}" 2>/dev/null || true
    fi

    # ─── 5. Credentials & URLs ──────────────────────────────────────────────
    local creds_dir="${HOME}/.config/pop-os-setup"
    if [[ -d "$creds_dir" ]]; then
        log_sep
        info "Credentials & URLs:"

        # Portainer
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^portainer$"; then
            log "   Portainer     : http://localhost:9000"
            if [[ -f "${creds_dir}/.portainer_password" ]]; then
                log "   Portainer Pass: saved in ${creds_dir}/.portainer_password"
            fi
        fi

        # Grafana
        if [[ -f "${creds_dir}/.grafana_password" ]]; then
            log "   Grafana Pass  : saved in ${creds_dir}/.grafana_password"
        fi

        # SSH passphrase
        if [[ -f "${creds_dir}/.ssh_passphrase" ]]; then
            log "   SSH passphrase: saved in ${creds_dir}/.ssh_passphrase"
            info "   Run: ssh-add ~/.ssh/id_ed25519 (enter passphrase when asked)"
        fi
    fi

    # ─── 6. Useful Commands ──────────────────────────────────────────────────
    log_sep
    info "Useful Commands:"
    log "   nvim                  → Launch Neovim"
    log "   tailscale status      → Check Tailscale VPN"
    log "   docker ps             → Running containers"
    log "   kubectl get nodes     → k3s cluster nodes"
    log "   ufw status            → Firewall rules"
    log "   fail2ban-client status sshd → fail2ban SSH jail"
    log "   journalctl -u fail2ban -n 20 → fail2ban logs"

    # ─── 7. Recommendations ─────────────────────────────────────────────────
    log_sep
    info "Recommendations:"
    log "   1. Reboot the system to apply all changes"
    log "   2. Review generated credentials in ~/.config/pop-os-setup/"
    log "   3. Run 'make check' to verify stages"
    log "   4. Add SSH public key to GitHub: cat ~/.ssh/id_ed25519.pub"
    log "   5. Configure Tailscale auth key if not connected"
    log "   6. Consider enabling stage 25 backup (Timeshift)"

    # ─── 8. Next Steps ──────────────────────────────────────────────────────
    log_sep
    ok "Setup completed successfully!"
    log "Thank you for using pop-os-setup v3.0.0"
    log_sep

    return 0
}

# Для совместимости со старым вызовом
stage26_final() {
    stage_final "$@"
}
