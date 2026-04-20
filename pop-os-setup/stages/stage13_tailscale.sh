#!/bin/bash
#===============================================================================
# Stage 13 — Tailscale VPN + Cluster Mesh
#===============================================================================
# Profile: full, cluster
# Uses: install_tailscale_safe() from lib/installer.sh
#===============================================================================

[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
    STAGEDIR="${SCRIPT_DIR}/stages"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_tailscale() {
    step "TAILSCALE VPN" "13"

    if [[ "${ENABLE_TAILSCALE:-0}" != "1" ]]; then
        ok "Tailscale installation skipped (ENABLE_TAILSCALE=0)"
        return 0
    fi

    # Already installed?
    if command_exists tailscale; then
        local ver
        ver=$(tailscale version 2>/dev/null | head -n1 || echo "installed")
        ok "Tailscale already installed: $ver"
        return 2
    fi

    log "Installing Tailscale VPN (secure method)..."

    # IP forwarding for subnet router
    local sysctl_conf="/etc/sysctl.d/99-tailscale.conf"
    if [[ ! -f "$sysctl_conf" ]]; then
        log "Enabling IP forwarding for subnet routing..."
        {
            echo "net.ipv4.ip_forward = 1"
            echo "net.ipv6.conf.all.forwarding = 1"
        } > "$sysctl_conf"
        sysctl -p "$sysctl_conf" 2>/dev/null || true
        ok "IP forwarding enabled"
    else
        ok "IP forwarding already configured"
    fi

    # Secure installation via lib/installer.sh
    if install_tailscale_safe; then
        ok "Tailscale binary installed"

        # Enable and start service
        systemctl enable tailscaled 2>/dev/null || true
        systemctl start tailscaled 2>/dev/null || true

        if systemctl is-active --quiet tailscaled; then
            ok "tailscaled service running"
        else
            warn "tailscaled service not active — run 'sudo systemctl start tailscaled'"
        fi

        # Authenticate
        if [[ -n "${TAILSCALE_AUTHKEY:-}" ]]; then
            log "Authenticating with TAILSCALE_AUTHKEY..."
            if tailscale up --authkey="${TAILSCALE_AUTHKEY}" --accept-dns=false 2>&1 | grep -qiE "success|connected"; then
                ok "Tailscale authenticated and connected"
            else
                warn "Authentication may have failed — check manually: sudo tailscale up"
            fi
        else
            info "Tailscale installed but not authenticated"
            info "  → Run: sudo tailscale up"
            info "  → Or set TAILSCALE_AUTHKEY env var to skip interactive login"
        fi

        # Funnel (expose port 443 via Tailscale, no firewall holes)
        if command -v tailscale &>/dev/null && tailscale status --self &>/dev/null; then
            tailscale funnel 443 &>/dev/null || true
            ok "Tailscale Funnel enabled (port 443)"
        fi

        ok "Tailscale VPN configured"
        return 0
    else
        err "Tailscale installation failed"
        return 1
    fi
}

# Compatibility alias
stage13_tailscale() { stage_tailscale "$@"; }
