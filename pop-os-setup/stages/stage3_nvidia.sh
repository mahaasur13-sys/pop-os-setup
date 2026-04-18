#!/bin/bash
#===============================================================================
# Stage 3 — NVIDIA Stack
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_nvidia() {
    step "NVIDIA STACK" "3"

    if has_nvidia; then
        ok "NVIDIA already active: $(nvidia_info)"
        return 0
    fi

    if has_system76; then
        log "Using System76 proprietary driver..."
        apt install -y system76-driver-nvidia 2>&1 | tail -3
        ok "System76 NVIDIA driver installed"
    else
        log "Installing NVIDIA driver..."
        apt install -y nvidia-driver-550 2>&1 | tail -5
        ok "NVIDIA driver installed — reboot required"
    fi

    if has_system76_power; then
        local mode="${NVIDIA_GRAPHICS_MODE:-hybrid}"
        log "Setting graphics mode: $mode"
        system76-power graphics "$mode"
        ok "Graphics mode: $mode"
    fi
}