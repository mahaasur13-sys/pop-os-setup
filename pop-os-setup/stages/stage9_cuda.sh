#!/bin/bash
#===============================================================================
# Stage 9 — CUDA Toolkit
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_cuda() {
    step "CUDA TOOLKIT" "9"

    if [[ "${ENABLE_CUDA:-0}" != "1" ]]; then
        ok "CUDA skipped (ENABLE_CUDA != 1)"
        return 0
    fi

    if ! has_nvidia; then
        warn "No NVIDIA GPU detected — skipping CUDA"
        return 0
    fi

    if command -v nvcc &>/dev/null; then
        ok "CUDA already installed: $(nvcc --version | grep release | awk '{print $5}')"
        return 0
    fi

    log "Adding NVIDIA CUDA repository..."
    wget -q https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring.deb
    dpkg -i cuda-keyring.deb
    rm -f cuda-keyring.deb
    apt update -qq

    log "Installing CUDA (this may take a while)..."
    apt install -y cuda 2>&1 | tail -5

    export PATH=/usr/local/cuda/bin:$PATH
    export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

    if command -v nvcc &>/dev/null; then
        local cuda_ver
        cuda_ver=$(nvcc --version | grep release | awk '{print $5}')
        ok "CUDA $cuda_ver installed"
    else
        warn "CUDA installed but nvcc not in PATH — reboot required"
    fi
}

# Stub for back-compat
stage8_cuda() { stage_cuda; }