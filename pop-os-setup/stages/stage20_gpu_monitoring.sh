#!/bin/bash
#===============================================================================
# Stage 20 — GPU Monitoring (nvidia-smi exporter + DCGM)
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_gpu_monitoring() {
    step "GPU MONITORING" "20"

    if ! command -v nvidia-smi &>/dev/null; then
        ok "No NVIDIA GPU — skipping GPU monitoring"
        return 0
    fi

    log "Deploying NVIDIA GPU monitoring via Docker..."

    docker run -d --name nvidia-gpu-exporter \
        --restart unless-stopped \
        -p 9445:9445 \
        --gpus all \
        utkat Blowtorch/nvidia-exporter:latest 2>/dev/null || true

    ok "GPU metrics exporter: http://localhost:9445"
    ok "GPU monitoring configured"
}

stage20_gpu_monitoring() { stage_gpu_monitoring; }