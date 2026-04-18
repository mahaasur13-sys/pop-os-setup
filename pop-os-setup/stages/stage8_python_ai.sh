#!/bin/bash
#===============================================================================
# Stage 8 — Python + AI Stack
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_python_ai() {
    step "PYTHON + AI STACK" "8"

    log "Installing Python base packages..."
    apt install -y python3 python3-pip python3-venv python3-dev \
        python3-numpy python3-scipy python3-matplotlib python3-pandas

    upgrade_pip

    if [[ "${ENABLE_AI:-0}" != "1" ]]; then
        ok "Python base installed (AI stack skipped)"
        return 0
    fi

    log "Installing PyTorch (CPU)..."
    pip3 install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -5

    log "Installing TensorFlow..."
    pip3 install tensorflow 2>&1 | tail -3

    log "Installing Jupyter..."
    pip3 install jupyterlab notebook 2>&1 | tail -3

    log "Installing transformers + accelerate..."
    pip3 install transformers accelerate 2>&1 | tail -3

    ok "AI stack installed (PyTorch + TensorFlow + Jupyter + Transformers)"
}

# Stub for back-compat
stage7_python_ai() { stage_python_ai; }