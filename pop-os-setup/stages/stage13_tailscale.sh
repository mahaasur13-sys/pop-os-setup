#!/bin/bash
#===============================================================================
# Stage 13 — Tailscale VPN + Cluster Mesh
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_tailscale() {
    step "TAILSCALE VPN + CLUSTER MESH" "13"

    if [[ "${ENABLE_TAILSCALE:-0}" != "1" ]]; then
        ok "Tailscale skipped"
        return 0
    fi

    if command -v tailscale &>/dev/null; then
        ok "Tailscale already installed: $(tailscale version 2>/dev/null | head -1)"
    else
        log "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh - 2>&1 | tail -5
    fi

    if ! tailscale status &>/dev/null; then
        if [[ -n "${TAILSCALE_AUTHKEY:-}" ]]; then
            log "Authenticating with authkey..."
            tailscale up --authkey="$TAILSCALE_AUTHKEY" --accept-dns=false 2>&1 | tail -3
        else
            warn "Tailscale not logged in. Run: sudo tailscale up"
            warn "Set TAILSCALE_AUTHKEY env var to skip interactive login"
        fi
    else
        ok "Tailscale already authenticated"
    fi

    # IP forwarding
    if [[ ! -f /etc/sysctl.d/99-tailscale.conf ]]; then
        echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-tailscale.conf
        echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.d/99-tailscale.conf
        sysctl -p /etc/sysctl.d/99-tailscale.conf 2>/dev/null || true
        ok "IP forwarding enabled"
    fi

    # Funnel (expose port 443 without opening firewall)
    if tailscale status --self &>/dev/null; then
        tailscale funnel 443 &>/dev/null || true
        ok "Tailscale Funnel enabled (port 443)"
    fi

    ok "Tailscale VPN mesh configured"
}

stage13_tailscale() { stage_tailscale; }