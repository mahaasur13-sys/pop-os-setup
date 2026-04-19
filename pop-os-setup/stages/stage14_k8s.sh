#!/bin/bash
#===============================================================================
# Stage 14 — Kubernetes (k3s) — Home cluster compute node
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_k8s() {
    step "KUBERNETES (k3s)" "14"

    if [[ "${ENABLE_K8S:-0}" != "1" ]]; then
        ok "Kubernetes skipped"
        return 0
    fi

    if command -v k3s &>/dev/null; then
        ok "k3s already installed: $(k3s --version 2>/dev/null | head -1)"
        return 0
    fi

    log "Installing k3s (single-node)..."
    export K3S_KUBECONFIG_MODE="644"
    export INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644"

    curl -sfL https://get.k3s.io | sh - 2>&1 | tail -10

    if command -v k3s &>/dev/null; then
        mkdir -p ~/.kube
        cp /etc/rancher/k3s/k3s.yaml ~/.kube/config 2>/dev/null || true
        chmod 600 ~/.kube/config
        log "k3s installed. Kubeconfig: ~/.kube/config"
        ok "Kubernetes cluster ready"
    else
        err "k3s installation failed"
        return 1
    fi

    # Enable basic monitoring
    log "Deploying k3s metrics server..."
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null || true

    ok "Kubernetes configured"
}

stage14_k8s() { stage_k8s; }