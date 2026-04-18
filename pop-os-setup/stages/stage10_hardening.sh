#!/bin/bash
#===============================================================================
# Stage 10 — Security Hardening
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_hardening() {
    step "SECURITY HARDENING" "10"

    if [[ "${ENABLE_HARDEN:-0}" != "1" ]]; then
        ok "Security hardening skipped"
        return 0
    fi

    # UFW Firewall
    log "Configuring UFW firewall..."
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp comment 'SSH'
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    ufw --force enable
    enable_service ufw
    ok "UFW active: $(ufw status | head -3 | tail -1)"

    # fail2ban
    log "Installing and configuring fail2ban..."
    apt install -y fail2ban 2>&1 | tail -3
    enable_service fail2ban
    ok "fail2ban enabled"

    # Sysctl hardening
    log "Applying kernel hardening..."
    apply_sysctl "net.ipv4.icmp_echo_ignore_broadcasts" "1"
    apply_sysctl "net.ipv4.tcp_syncookies" "1"
    apply_sysctl "kernel.panic" "10"

    ok "Security hardening applied"
}

# Stub
stage9_hardening() { stage_hardening; }