#!/bin/bash
#===============================================================================
# Stage 09 — CUDA Toolkit + cuDNN
#===============================================================================
# Профиль: ai-dev, full
# Требует: NVIDIA GPU + stage03_nvidia.sh
# Использует: safe_download() из lib/installer.sh
#===============================================================================

[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_cuda() {
    step "CUDA TOOLKIT + cuDNN" "09"

    if [[ "${ENABLE_CUDA:-0}" != "1" ]]; then
        ok "CUDA installation skipped (ENABLE_CUDA=0)"
        return 0
    fi

    if ! has_nvidia; then
        err "No NVIDIA GPU detected or NVIDIA drivers not installed"
        err "Please run stage 03 (NVIDIA drivers) first"
        return 1
    fi

    if command_exists nvcc; then
        local version
        version=$(nvcc --version 2>/dev/null | grep -o 'release [0-9.]*' | awk '{print $2}')
        ok "CUDA already installed (version ${version:-unknown})"
        return 2
    fi

    log "Starting CUDA Toolkit installation..."

    local tmpdir="${INSTALLER_TMPDIR:-/tmp/pop-os-install}/cuda"
    mkdir -p "$tmpdir"

    # 1. Загрузка и верификация CUDA keyring
    log "Installing NVIDIA CUDA keyring..."

    local keyring_url="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb"
    local keyring_deb="${tmpdir}/cuda-keyring.deb"

    if ! safe_download "$keyring_url" "$keyring_deb"; then
        err "Failed to download CUDA keyring"
        return 1
    fi

    # 2. Установка keyring
    dpkg -i "$keyring_deb" || {
        err "Failed to install CUDA keyring package"
        return 1
    }
    ok "CUDA keyring installed successfully"

    # 3. Обновление пакетного индекса
    log "Updating package index..."
    apt-get update -qq || {
        warn "apt-get update partially failed (may be normal on fresh install)"
    }

    # 4. Установка CUDA toolkit
    log "Installing CUDA toolkit (10-20 min)..."

    apt-get install -y --no-install-recommends \
        cuda-toolkit-12-4 \
        libcudnn8 \
        libcudnn8-dev || {
            err "Failed to install CUDA toolkit packages"
            return 1
        }

    # 5. Настройка PATH и LD_LIBRARY_PATH
    log "Configuring CUDA environment variables..."

    local cuda_env="/etc/profile.d/cuda.sh"
    cat > "$cuda_env" << 'EOF'
export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}
export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
EOF
    chmod 644 "$cuda_env"

    # 6. Верификация
    if command_exists nvcc; then
        local cuda_ver
        cuda_ver=$(nvcc --version | grep -o 'release [0-9.]*' | awk '{print $2}')
        ok "CUDA ${cuda_ver} installed"
        ok "nvcc: $(command -v nvcc)"
    else
        err "CUDA installed but nvcc not in PATH — reboot required"
        return 1
    fi

    info "Reboot recommended after CUDA installation for full driver reload"
    return 0
}

# Совместимость
stage09_cuda() { stage_cuda "$@"; }
