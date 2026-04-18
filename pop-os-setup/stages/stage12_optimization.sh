#!/bin/bash
#===============================================================================
# Stage 12 — System Optimization
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_optimization() {
    step "SYSTEM OPTIMIZATION" "12"

    # Swap tuning
    if [[ ! -f /etc/sysctl.d/99-swappiness.conf ]]; then
        echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
        sysctl -p /etc/sysctl.d/99-swappiness.conf 2>/dev/null || true
        ok "Swappiness set to 10"
    else
        ok "Swappiness already tuned"
    fi

    # Automatic updates
    if ! command -v unattended-upgrades &>/dev/null; then
        log "Installing unattended-upgrades..."
        apt install -y unattended-upgrades 2>&1 | tail -3
    fi
    dpkg-reconfigure -plow unattended-upgrades 2>/dev/null || true
    ok "Unattended upgrades configured"

    # ZRAM (optional, for machines with limited RAM)
    if command -v zramctl &>/dev/null && ! systemctl list-unit-files | grep -q zram; then
        log "Note: ZRAM available but not enabled by default"
    fi

    ok "System optimization complete"
}

stage11_optimization() { stage_optimization; }