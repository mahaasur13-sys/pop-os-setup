#!/bin/bash
#===============================================================================
# Stage 16 — System76 Power Management + GPU Tuning
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_power() {
    step "SYSTEM76 POWER + GPU TUNING" "16"

    if ! command -v system76-power &>/dev/null; then
        log "system76-power not available (non-System76 hardware)"
        ok "Skipped (not System76)"
        return 0
    fi

    log "Checking GPU power mode..."
    local gpu_mode
    gpu_mode=$(system76-power graphics 2>/dev/null || echo "unknown")
    ok "Current GPU mode: $gpu_mode"

    # Performance profile
    log "Setting performance mode..."
    system76-power graphics nvidia 2>/dev/null || true
    system76-power profile performance 2>/dev/null || true

    # NVIDIA settings
    if command -v nvidia-smi &>/dev/null; then
        log "Applying NVIDIA GPU tuning..."
        nvidia-smi -pm 1 2>/dev/null || true          # Persistence mode
        nvidia-smi -pl 250 2>/dev/null || true        # Power limit (adjust for your GPU)
        nvidia-smi --auto-boost-default=1 2>/dev/null || true
        ok "NVIDIA GPU tuned"
    fi

    ok "Power management configured"
}

stage16_power() { stage_power; }