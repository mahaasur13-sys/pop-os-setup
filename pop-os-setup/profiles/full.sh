#!/bin/bash
#===============================================================================
# Profile: full — All components enabled
#===============================================================================
# Recommended for: power users, home lab, cluster node
# Enabled: SSH, Docker, CUDA, AI stack, KDE, Zsh, Tailscale,
#          Kubernetes (k3s), Slurm, Monitoring, GPU monitoring,
#          Security hardening, Power tuning, Neovim, Backup
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

# Alias for dispatcher
apply_profile_full_fn() { apply_profile_full; }