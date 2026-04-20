#!/bin/bash
#===============================================================================
# Stage 10 — System Hardening
#===============================================================================
# Профиль: все (workstation, ai-dev, full, cluster)
# Выполняет: UFW firewall, fail2ban, sysctl hardening, unattended-upgrades
# Использует: step, ok, warn, err, info, log, log_sep из lib/logging.sh
#             backup_file, append_once, ensure_dir, pkg_installed,
#             command_exists, get_target_user, apply_sysctl из lib/utils.sh
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
# Основная stage-функция
# ----------------------------------------------------------------------------
stage_hardening() {
    step "SYSTEM HARDENING" "10"

    if [[ "${ENABLE_HARDEN:-1}" != "1" ]]; then
        ok "System hardening skipped (ENABLE_HARDEN=0)"
        return 0
    fi

    log "Starting comprehensive system hardening..."

    # ─── 1. UFW Firewall ─────────────────────────────────────────────────────
    if command_exists ufw; then
        log "Configuring UFW firewall..."

        backup_file "/etc/ufw/user.rules"

        ufw --force reset >/dev/null 2>&1 || true
        ufw default deny incoming >/dev/null 2>&1
        ufw default allow outgoing >/dev/null 2>&1

        # Разрешаем SSH только из доверенных сетей
        if [[ "${ENABLE_SSH:-0}" == "1" ]]; then
            ufw allow from 192.168.10.0/24 to any port 22 proto tcp >/dev/null 2>&1 || true
            ufw allow from 10.0.0.0/8 to any port 22 proto tcp >/dev/null 2>&1 || true  # Tailscale
        fi

        ufw --force enable >/dev/null 2>&1 && \
            ok "UFW enabled (default policy: deny incoming)" || \
            warn "Failed to enable UFW"
    else
        warn "ufw command not found. Skipping firewall configuration."
    fi

    # ─── 2. fail2ban ──────────────────────────────────────────────────────────
    log "Setting up fail2ban..."

    if pkg_installed fail2ban || apt-get install -y fail2ban >/dev/null 2>&1; then
        backup_file "/etc/fail2ban/jail.local"

        cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 10m
findtime  = 10m
maxretry  = 5
ignoreip  = 127.0.0.1/8 ::1 192.168.10.0/24 10.0.0.0/8

[sshd]
enabled   = true
port      = ssh
maxretry  = 3
bantime   = 30m
findtime  = 15m
EOF

        systemctl restart fail2ban >/dev/null 2>&1 && \
            ok "fail2ban configured and restarted" || \
            warn "fail2ban service restart failed"
    else
        warn "Failed to install fail2ban"
    fi

    # ─── 3. Sysctl Hardening ──────────────────────────────────────────────────
    log "Applying kernel and network hardening (sysctl)..."

    backup_file "/etc/sysctl.d/99-pop-os-setup-hardening.conf"

    cat > /etc/sysctl.d/99-pop-os-setup-hardening.conf << 'EOF'
# pop-os-setup v3.0.0 — Kernel and network hardening

# Kernel hardening
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.unprivileged_bpf_disabled = 1
kernel.yama.ptrace_scope = 2

# Network hardening
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Additional network hardening
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
EOF

    if sysctl --system >/dev/null 2>&1; then
        ok "Sysctl hardening applied"
    else
        warn "sysctl --system returned errors (some settings may not apply)"
    fi

    # ─── 4. Unattended Upgrades ───────────────────────────────────────────────
    log "Enabling unattended security upgrades..."

    if pkg_installed unattended-upgrades; then
        sed -i 's|//Unattended-Upgrade::Allowed-Origins|Unattended-Upgrade::Allowed-Origins|' \
            /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null || true

        cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

        ok "Unattended-upgrades enabled (security updates)"
    else
        warn "unattended-upgrades package not available"
    fi

    # ─── 5. Финальный отчёт ───────────────────────────────────────────────────
    log_sep
    ok "System hardening completed"
    info "Applied:"
    log "   - UFW firewall (default deny incoming)"
    log "   - fail2ban (sshd jail, 10min ban)"
    log "   - sysctl kernel hardening"
    log "   - unattended security upgrades"

    return 0
}

# Для совместимости со старым вызовом
stage10_hardening() {
    stage_hardening "$@"
}