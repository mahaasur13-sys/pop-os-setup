#!/bin/bash
#===============================================================================
# Stage 15 — Slurm Workload Manager — Home cluster GPU scheduler
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_slurm() {
    step "SLURM WORKLOAD MANAGER" "15"

    if [[ "${ENABLE_SLURM:-0}" != "1" ]]; then
        ok "Slurm skipped"
        return 0
    fi

    log "Slurm is typically installed via infra/ansible on control node."
    log "On compute nodes, only munge and slurm-client packages needed."
    warn "Full Slurm cluster deployment is managed by home-cluster-iac"

    if command -v sinfo &>/dev/null; then
        ok "Slurm client tools present"
        return 0
    fi

    log "Installing Slurm client packages..."
    pkg_installed munge || sudo apt install -y munge
    pkg_installed slurm-client || sudo apt install -y slurm-client 2>/dev/null || \
        sudo apt install -y slurmd 2>/dev/null || true

    ok "Slurm client configured"
    log "Note: Configure slurm.conf for your cluster before use"
}

stage15_slurm() { stage_slurm; }