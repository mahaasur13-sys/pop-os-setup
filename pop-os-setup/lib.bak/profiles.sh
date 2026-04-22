#!/bin/bash
#===============================================================================
# Profiles Library — pop-os-setup
#===============================================================================
# Deployment profile definitions
# Each profile sets ENABLE_* variables consumed by stages
#===============================================================================

#--- Profile Definitions ------------------------------------------------------
# Format: ENABLE_<FEATURE>=0|1
# Stages check these variables to decide what to install

#===============================================================================
# Profile: workstation (AI/Dev workstation, single machine)
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

    log "Profile: workstation → SSH=0 Docker=1 CUDA=0 AI=1 Hardening=1 KDE=1 Zsh=1"
}

#===============================================================================
# Profile: cluster (home-cluster node, Slurm/Ray/K8s)
#===============================================================================
apply_profile_cluster() {
    log "Applying profile: cluster (home-cluster compute node)"

    export ENABLE_SSH=1
    export ENABLE_DOCKER=1
    export ENABLE_CUDA=1
    export ENABLE_AI=1
    export ENABLE_HARDEN=1
    export ENABLE_KDE=0
    export ENABLE_ZSH=1
    export ENABLE_TAILSCALE=1
    export ENABLE_K8S=1
    export ENABLE_SLURM=1
    export ENABLE_MONITORING=1

    log "Profile: cluster → SSH=1 Docker=1 CUDA=1 AI=1 Hardening=1 Tailscale=1 K8s=1 Slurm=1"
}

#===============================================================================
# Profile: ai-dev (AI researcher, GPU-heavy, Jupyter + CUDA)
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

#===============================================================================
# Profile: full (all components — maximum installation)
#===============================================================================
apply_profile_full() {
    log "Applying profile: full (all components)"

    export ENABLE_SSH=1
    export ENABLE_DOCKER=1
    export ENABLE_CUDA=1
    export ENABLE_AI=1
    export ENABLE_HARDEN=1
    export ENABLE_KDE=1
    export ENABLE_ZSH=1
    export ENABLE_TAILSCALE=1
    export ENABLE_K8S=1
    export ENABLE_SLURM=1
    export ENABLE_MONITORING=1

    log "Profile: full → all enabled"
}

#===============================================================================
# Profile dispatcher
#===============================================================================
apply_profile() {
    local profile="${1:-workstation}"
    case "$profile" in
        workstation) apply_profile_workstation ;;
        cluster)    apply_profile_cluster    ;;
        ai-dev)     apply_profile_ai_dev     ;;
        full)       apply_profile_full       ;;
        *)
            err "Unknown profile: $profile"
            err "Available: workstation, cluster, ai-dev, full"
            return 1
            ;;
    esac
    log "Profile '$profile' applied"
}

#===============================================================================
# Print available profiles
#===============================================================================
list_profiles() {
    echo "Available deployment profiles:"
    echo "  workstation  — AI/Dev single-machine (default)"
    echo "  cluster      — home-cluster compute node (K8s+Slurm+Ray)"
    echo "  ai-dev       — AI researcher (CUDA + Jupyter + PyTorch)"
    echo "  full         — all components maximum installation"
}