#!/bin/bash
#===============================================================================
# Profile: workstation — AI/Dev single-machine workstation
#===============================================================================
# Recommended for: developers, AI practitioners, single-user systems
# Enabled: Docker, AI stack, KDE, Zsh, security hardening, monitoring
# Disabled: SSH (local only), CUDA (use NVIDIA ISO), Tailscale, K8s, Slurm
#===============================================================================

apply_profile_workstation() {
    log "Applying profile: workstation (AI/Dev single-machine)"

    export ENABLE_SSH=0
    export ENABLE_DOCKER=1
    export ENABLE_CUDA=0
    export ENABLE_AI=1
    export ENABLE_HARDEN=1
    export ENABLE_KDE=1
    export ENABLE_ZSH=1
    export ENABLE_TAILSCALE=0
    export ENABLE_K8S=0
    export ENABLE_SLURM=0
    export ENABLE_MONITORING=1

    log "Profile: workstation → SSH=0 Docker=1 CUDA=0 AI=1 Hardening=1 KDE=1 Zsh=1 Tailscale=0 K8s=0 Slurm=0"
}