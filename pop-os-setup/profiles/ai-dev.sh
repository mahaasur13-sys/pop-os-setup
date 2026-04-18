#!/bin/bash
#===============================================================================
# Profile: ai-dev — AI researcher / ML engineer workstation
#===============================================================================
# Recommended for: ML researchers, data scientists, GPU-heavy workloads
# Enabled: Docker, CUDA, AI stack (PyTorch + TensorRT + Jupyter), KDE, Zsh,
#          security hardening, monitoring
# Disabled: SSH (local only), Tailscale, K8s, Slurm
#===============================================================================

apply_profile_ai_dev() {
    log "Applying profile: ai-dev (AI researcher / ML engineer)"

    export ENABLE_SSH=0
    export ENABLE_DOCKER=1
    export ENABLE_CUDA=1
    export ENABLE_AI=1
    export ENABLE_HARDEN=1
    export ENABLE_KDE=1
    export ENABLE_ZSH=1
    export ENABLE_TAILSCALE=0
    export ENABLE_K8S=0
    export ENABLE_SLURM=0
    export ENABLE_MONITORING=1

    log "Profile: ai-dev → SSH=0 Docker=1 CUDA=1 AI=1 Hardening=1 KDE=1 Zsh=1"
}