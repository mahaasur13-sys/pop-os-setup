#!/bin/bash
#===============================================================================
# Stage 26 — Final Verification + Report
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_final() {
    step "FINAL VERIFICATION + REPORT" "26"

    log "Running post-install verification..."

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Pop!_OS Setup — Installation Report                 ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    echo "  System:"
    uname -a | awk '{print "  ├─ Kernel:    " $0}'
    echo "  ├─ Hostname:  $(hostname)"
    echo "  └─ Uptime:    $(uptime -p 2>/dev/null || uptime)"

    echo ""
    echo "  GPU:"
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | \
            awk -F',' '{print "  ├─ " $1 " (Driver " $2 ") | " $3}'
    else
        echo "  └─ NVIDIA: Not detected"
    fi

    echo ""
    echo "  Installed Tools:"
    local tools=("git" "docker" "python3" "nvim" "tailscale" "kubectl")
    for tool in "${tools[@]}"; do
        if command -v "$tool" &>/dev/null; then
            local ver
            ver=$($tool --version 2>/dev/null | head -1 || echo "installed")
            echo "  ├─ $tool: $ver"
        fi
    done

    echo ""
    echo "  Services:"
    local services=("docker" "k3s" "prometheus" "grafana")
    for svc in "${services[@]}"; do
        if systemctl is-active "$svc" &>/dev/null; then
            echo "  ├─ $svc: ✓ running"
        fi
    done

    echo ""
    echo "  Profile Applied: ${PROFILE:-unknown}"
    echo "  Stages Run:     1–26"
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  🎉 Pop!_OS AI/Dev Workstation Ready!                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    ok "Setup complete!"
    log "Log file: ${LOGFILE:-/tmp/pop-os-setup.log}"
}

stage26_final() { stage_final; }