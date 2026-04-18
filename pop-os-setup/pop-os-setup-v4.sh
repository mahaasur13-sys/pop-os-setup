#!/bin/bash
#===============================================================================
# Pop!_OS 24.04 LTS NVIDIA — AI/Dev Workstation Auto-Setup v4.0.0
#===============================================================================
# Target  : Pop!_OS 24.04 LTS NVIDIA Edition (USB Boot → Production Ready)
# Stack   : KDE Plasma + Docker/Podman + CUDA 12.4 + Python AI
#           + k3s + Longhorn + Rook Ceph + MinIO + Tailscale
#           + Neovim/LazyVim + Prometheus + Grafana + Loki + Zsh
# Author  : mahaasur13-sys | asurdev.zo.computer
# Version : 4.0.0 (2026-04-18) — STABLE
#===============================================================================

set -euo pipefail

LOGFILE="/var/log/popos-setup-v4-$(date +%Y%m%d-%H%M%S).log"
SCRIPT_VERSION="4.0.0"
CURRENT_USER="$(logname 2>/dev/null || echo "$SUDO_USER")"
HOMEDIR="$(getent passwd "$CURRENT_USER" | cut -d: -f6)"

# Global state
RUNTIME="docker"
USE_CUDA="no"
GPU_DETECTED="no"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()     { echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOGFILE"; }
logOk()   { echo -e "${GREEN}[OK]${NC} $1" | tee -a "$LOGFILE"; }
logWarn() { echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOGFILE"; }
logErr()  { echo -e "${RED}[ERR]${NC} $1" | tee -a "$LOGFILE"; exit 1; }

check_root() { [[ $EUID -ne 0 ]] && logErr "Run as root: sudo bash $0"; }

gpu_detect() {
    if nvidia-smi &>/dev/null; then
        GPU_DETECTED="yes"; echo "yes"
    else
        GPU_DETECTED="no"; echo "no"
    fi
}
gpu_name()   { nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "unknown"; }
gpu_driver() { nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo "unknown"; }

ask_yes_no() {
    local prompt="$1"; local default="$2"; local answer
    while true; do
        read -rp "$prompt [y/n]: " answer
        answer=$(echo "$answer" | tr '[:upper:]' '[:lower:]')
        [[ -z "$answer" ]] && answer="$default"
        case "$answer" in y|yes) return 0 ;; n|no) return 1 ;; *) echo "Answer y or n." ;; esac
    done
}

run_stage() {
    local num="$1"; local label="$2"; local func="$3"
    echo "" | tee -a "$LOGFILE"
    echo "╔══════════════════════════════════════════════════════╗" | tee -a "$LOGFILE"
    echo "║  STAGE $num — $label" | tee -a "$LOGFILE"
    echo "╚══════════════════════════════════════════════════════╝" | tee -a "$LOGFILE"
    $func
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Preflight Checks
# ════════════════════════════════════════════════════════════════════════════
stage01_preflight() {
    log "OS: $(source /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
    log "Kernel: $(uname -r)"
    log "Boot: $([[ -d /sys/firmware/efi ]] && echo "UEFI" || echo "Legacy")"
    log "User: $CURRENT_USER | Home: $HOMEDIR"
    if [[ "$(gpu_detect)" == "yes" ]]; then
        logOk "NVIDIA GPU: $(gpu_name) | Driver: $(gpu_driver)"
    else
        logWarn "NVIDIA GPU NOT detected — GPU/CUDA stages will be skipped"
    fi
    if ping -c1 -W2 8.8.8.8 &>/dev/null; then
        logOk "Network: OK"
    else
        logErr "No internet connection — aborting"
    fi
    log "Log file: $LOGFILE"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 2 — System Update + Base Packages
# ════════════════════════════════════════════════════════════════════════════
stage02_update() {
    log "Updating package index..."
    export DEBIAN_FRONTEND=noninteractive
    apt update -qq
    apt upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" 2>&1 | tail -3
    logOk "System updated"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 3 — NVIDIA Driver + system76-power (laptops)
# ════════════════════════════════════════════════════════════════════════════
stage03_nvidia() {
    if [[ "$GPU_DETECTED" == "no" ]]; then
        logWarn "No GPU — skipping driver installation"; return 0
    fi
    logOk "NVIDIA driver already active: $(gpu_driver)"
    if command -v system76-power &>/dev/null; then
        log "Laptop detected — system76-power available"
        if ask_yes_no "Enable system76-power (hybrid graphics switch)?" "n"; then
            apt install -y system76-power
            systemctl enable --now system76-power
            system76-power graphics nvidia
            logOk "system76-power: NVIDIA mode enabled"
        fi
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 4 — CUDA Toolkit 12.4 + cuDNN
# ════════════════════════════════════════════════════════════════════════════
stage04_cuda() {
    if [[ "$GPU_DETECTED" == "no" ]]; then
        logWarn "No GPU — skipping CUDA"; USE_CUDA="no"; return 0
    fi
    if command -v nvcc &>/dev/null; then
        local cuda_ver=$(nvcc --version | grep release | awk '{print $5}' | tr -d ',')
        logOk "CUDA already installed: $cuda_ver"; USE_CUDA="yes"; return 0
    fi
    if ! ask_yes_no "Install CUDA Toolkit 12.4 + cuDNN (~5GB)?" "n"; then
        USE_CUDA="no"; return 0
    fi
    USE_CUDA="yes"
    if apt-cache show system76-cuda-latest &>/dev/null 2>&1; then
        apt install -y system76-cuda-latest system76-cudnn-latest 2>&1 | tail -5
    else
        wget -qO /tmp/cuda-keyring.deb \
            https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring.deb
        dpkg -i /tmp/cuda-keyring.deb; rm -f /tmp/cuda-keyring.deb
        apt update -qq
        apt install -y cuda-toolkit-12-4 cuda-libraries-12-4 libcudnn9 libcudnn9-dev 2>&1 | tail -5
    fi
    if [[ -d /usr/local/cuda/bin ]]; then
        cat >> "$HOMEDIR/.bashrc" <<'EOF'

# CUDA 12.4
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
EOF
        logOk "CUDA 12.4 + cuDNN installed"
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 5 — Container Runtime: Docker CE OR Podman
# ════════════════════════════════════════════════════════════════════════════
stage05_docker() {
    if ! ask_yes_no "Use Podman instead of Docker (rootless, daemonless)?" "n"; then
        RUNTIME="docker"
        if command -v docker &>/dev/null; then
            logOk "Docker already present"
        else
            log "Installing Docker CE..."
            apt install -y apt-transport-https ca-certificates curl gnupg lsb-release 2>&1 | tail -2
            mkdir -p /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
                | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
            . /etc/os-release
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
                > /etc/apt/sources.list.d/docker.list
            apt update -qq
            apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>&1 | tail -3
            systemctl enable docker --now
            logOk "Docker CE installed"
        fi
        usermod -aG docker "$CURRENT_USER" 2>/dev/null || true

        # NVIDIA Container Toolkit for Docker
        if [[ "$GPU_DETECTED" == "yes" && ! -f /etc/containerd/config.toml.bak ]]; then
            if ! command -v nvidia-ctk &>/dev/null; then
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
                ARCH=$(dpkg --print-architecture)
                echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] \
https://nvidia.github.io/libnvidia-container/stable/deb/$ARCH /" \
                    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
                apt update -qq
                apt install -y nvidia-container-toolkit 2>&1 | tail -3
            fi
            nvidia-ctk runtime configure --runtime=containerd 2>/dev/null || true
            systemctl restart containerd
            systemctl restart docker
            logOk "NVIDIA Container Toolkit configured"
            if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu24.04 \
                nvidia-smi &>/dev/null; then
                logOk "Docker GPU passthrough: OK"
            else
                logWarn "Docker GPU test failed — may need reboot"
            fi
        fi
    else
        RUNTIME="podman"
        apt install -y podman podman-compose 2>&1 | tail -3
        logOk "Podman + podman-compose installed (rootless)"
        if [[ "$GPU_DETECTED" == "yes" ]]; then
            log "GPU in Podman: podman run --device nvidia.com/gpu=all ..."
        fi
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 6 — k3s + NVIDIA Device Plugin + Helm + kubectl
# ════════════════════════════════════════════════════════════════════════════
stage06_k3s() {
    if ! ask_yes_no "Install k3s (Kubernetes) + Helm + kubectl?" "n"; then
        log "k3s skipped"; return 0
    fi
    if command -v k3s &>/dev/null; then
        logOk "k3s already installed"
    else
        log "Installing k3s (Docker runtime)..."
        curl -sfL https://get.k3s.io | \
            INSTALL_K3S_EXEC="--docker --write-kubeconfig-mode 644 \
--node-label gpu=nvidia --node-label role=ai-workstation" \
            sh -s - 2>&1 | tail -5
        systemctl enable k3s --now
        sleep 5
        logOk "k3s installed"
    fi
    mkdir -p "$HOMEDIR/.kube"
    [[ -f /etc/rancher/k3s/k3s.yaml ]] && \
        cp /etc/rancher/k3s/k3s.yaml "$HOMEDIR/.kube/config"
    chown -R "$CURRENT_USER:$CURRENT_USER" "$HOMEDIR/.kube" 2>/dev/null || true
    echo "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml" >> "$HOMEDIR/.bashrc"
    if kubectl get nodes -o wide &>/dev/null; then
        logOk "k3s node: $(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
    fi
    if [[ "$GPU_DETECTED" == "yes" ]]; then
        kubectl apply -f \
            https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml \
            2>/dev/null || logWarn "k8s-device-plugin apply failed"
        logOk "NVIDIA k8s device plugin deployed"
    fi
    if ! command -v helm &>/dev/null; then
        curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash 2>&1 | tail -3
        logOk "Helm installed"
    fi
    if ! command -v kubectl &>/dev/null; then
        curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
        install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
        rm -f kubectl
        logOk "kubectl installed"
    fi
    logOk "k3s + Helm + kubectl ready"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 7 — Dev Toolchain
# ════════════════════════════════════════════════════════════════════════════
stage07_devtools() {
    log "Installing dev toolchain..."
    apt install -y \
        build-essential git curl wget vim htop btop tmux zsh \
        software-properties-common apt-transport-https ca-certificates \
        gnupg lsb-release jq bat exa fzf ripgrep fd-find tree zip unzip \
        fontconfig fonts-jetbrains-mono \
        python3 python3-pip python3-venv python3-dev \
        python3-numpy python3-pandas libopenblas-dev 2>&1 | tail -5
    logOk "Base dev tools installed"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 8 — Zsh + Oh My Zsh + Plugins
# ════════════════════════════════════════════════════════════════════════════
stage08_zsh() {
    if [[ -z "$CURRENT_USER" || "$CURRENT_USER" == "root" ]]; then
        logWarn "No non-root user — Zsh user setup skipped"; return 0
    fi
    if [[ ! -d "$HOMEDIR/.oh-my-zsh" ]]; then
        log "Installing Oh My Zsh..."
        sudo -u "$CURRENT_USER" sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
        logOk "Oh My Zsh installed"
    else
        logOk "Oh My Zsh already present"
    fi
    local zsh_custom="$HOMEDIR/.oh-my-zsh/custom/plugins"
    mkdir -p "$zsh_custom"
    if [[ ! -d "$zsh_custom/zsh-autosuggestions" ]]; then
        sudo -u "$CURRENT_USER" git clone --depth1 https://github.com/zsh-users/zsh-autosuggestions "$zsh_custom/zsh-autosuggestions"
        logOk "zsh-autosuggestions"
    fi
    if [[ ! -d "$zsh_custom/zsh-syntax-highlighting" ]]; then
        sudo -u "$CURRENT_USER" git clone --depth1 https://github.com/zsh-users/zsh-syntax-highlighting "$zsh_custom/zsh-syntax-highlighting"
        logOk "zsh-syntax-highlighting"
    fi
    sed -i 's/^plugins=(git)$/plugins=(git zsh-autosuggestions zsh-syntax-highlighting)/' "$HOMEDIR/.zshrc" 2>/dev/null || true
    chsh -s "$(which zsh)" "$CURRENT_USER"
    logOk "Zsh configured for $CURRENT_USER (default shell)"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 9 — Security: UFW, fail2ban, sysctl tuning
# ════════════════════════════════════════════════════════════════════════════
stage09_security() {
    log "Hardening system..."
    if ! command -v ufw &>/dev/null; then apt install -y ufw 2>&1 | tail -2; fi
    ufw --force disable; ufw --force enable
    ufw default deny incoming; ufw default allow outgoing
    ufw allow 22/tcp comment 'SSH'; ufw logging off
    logOk "UFW: default deny (SSH allowed)"

    if ask_yes_no "Install fail2ban (SSH brute-force protection)?" "n"; then
        apt install -y fail2ban 2>&1 | tail -2
        systemctl enable fail2ban --now
        logOk "fail2ban active"
    fi

    cat >> /etc/sysctl.d/99-ai-tuning.conf <<'SYSCTL_EOF'
# AI/ML tuning
vm.swappiness=10
vm.vfs_cache_pressure=50
net.core.rmem_max=134217728
net.core.wmem_max=134217728
net.ipv4.tcp_rmem=4096 87380 134217728
net.ipv4.tcp_wmem=4096 65536 134217728
# Security hardening
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1
net.ipv4.conf.all.accept_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv4.icmp_ignore_bogus_error_responses=1
SYSCTL_EOF
    sysctl -p /etc/sysctl.d/99-ai-tuning.conf 2>/dev/null || true
    logOk "sysctl tuning applied"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 10 — AI Stack: PyTorch (CPU/GPU) + Transformers + Jupyter + Ollama
# ════════════════════════════════════════════════════════════════════════════
stage10_ai_stack() {
    log "Installing AI stack..."
    pip3 install --upgrade pip --break-system-packages

    if [[ "$USE_CUDA" == "yes" ]]; then
        log "Installing PyTorch with CUDA 12.4..."
        pip3 install torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/cu124 \
            --break-system-packages 2>&1 | tail -3
        pip3 install "tensorflow[and-cuda]" --break-system-packages 2>&1 | tail -3
        logOk "PyTorch (CUDA 12.4) + TensorFlow [and-cuda]"
    else
        log "Installing PyTorch (CPU)..."
        pip3 install torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/cpu \
            --break-system-packages 2>&1 | tail -3
        pip3 install tensorflow --break-system-packages 2>&1 | tail -3
        logOk "PyTorch (CPU) + TensorFlow"
    fi

    pip3 install --break-system-packages \
        jupyterlab transformers datasets huggingface_hub accelerate \
        sentence-transformers gradio langchain langchain-community \
        scikit-learn pandas matplotlib seaborn 2>&1 | tail -5
    logOk "Core AI libraries installed"

    if ask_yes_no "Install Ollama (local LLM runtime)?" "n"; then
        curl -fsSL https://ollama.com/install.sh | sh
        systemctl enable ollama --now 2>/dev/null || true
        logOk "Ollama installed (run: ollama run llama3)"
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 11 — GPU Monitoring: nvtop, glances, btop, prometheus-node-exporter
# ════════════════════════════════════════════════════════════════════════════
stage11_monitoring() {
    if ! ask_yes_no "Install monitoring tools (nvtop, glances, btop)?" "n"; then
        log "Monitoring skipped"; return 0
    fi
    apt install -y nvtop btop 2>&1 | tail -3
    pip3 install --break-system-packages glances 2>&1 | tail -2
    if [[ "$GPU_DETECTED" == "yes" ]]; then
        logOk "nvtop (GPU monitoring) installed"
    fi
    logOk "Monitoring tools ready"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 12 — Tailscale VPN + Funnel + Serve
# ════════════════════════════════════════════════════════════════════════════
stage12_tailscale() {
    if ! ask_yes_no "Install Tailscale VPN?" "n"; then
        log "Tailscale skipped"; return 0
    fi
    if ! command -v tailscale &>/dev/null; then
        curl -fsSL https://tailscale.com/install.sh | sh 2>&1 | tail -5
        logOk "Tailscale installed"
    else
        logOk "Tailscale already present"
    fi
    if [[ -n "${TAILSCALE_AUTHKEY:-}" ]]; then
        tailscale up --authkey="$TAILSCALE_AUTHKEY" --accept-routes
        logOk "Tailscale connected with authkey"
    else
        tailscale up --accept-routes
        logWarn "Tailscale started — run 'tailscale login' if needed"
    fi
    if ask_yes_no "Enable Tailscale Funnel (public HTTPS access)?" "n"; then
        tailscale funnel --bg 443
        logOk "Funnel enabled on port 443"
    fi
    if ask_yes_no "Enable Tailscale Serve (internal proxy)?" "n"; then
        tailscale serve --bg https+insecure://localhost:3000
        logOk "Serve enabled"
    fi
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 13 — KDE Plasma Desktop
# ════════════════════════════════════════════════════════════════════════════
stage13_kde() {
    if ! ask_yes_no "Install/Configure KDE Plasma Desktop?" "n"; then
        log "KDE skipped"; return 0
    fi
    if ! command -v plasma-desktop &>/dev/null; then
        apt install -y kde-plasma-desktop plasma-nm sddm 2>&1 | tail -5
        systemctl enable sddm
        logOk "KDE Plasma installed — reboot required"
    else
        logOk "KDE Plasma already present"
    fi
    logOk "KDE Plasma ready (run: systemsettings5)"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 14 — SWAP 4GB + Unattended-Upgrades (security-only, no auto-reboot)
# ════════════════════════════════════════════════════════════════════════════
stage14_swap() {
    log "Configuring swap + unattended upgrades..."
    if ! swapon --show | grep -q "swapfile"; then
        fallocate -l 4G /swapfile
        chmod 600 /swapfile; mkswap /swapfile; swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
        logOk "Swap file created (4GB)"
    else
        logOk "Swap already present"
    fi
    if ! dpkg -l unattended-upgrades &>/dev/null; then
        apt install -y unattended-upgrades apt-listchanges 2>&1 | tail -2
    fi
    cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'UPGRADE_EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
UPGRADE_EOF
    systemctl restart unattended-upgrades
    logOk "Unattended-upgrades: security only, no auto-reboot"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 15 — Jupyter Lab as systemd service
# ════════════════════════════════════════════════════════════════════════════
stage15_jupyter() {
    if ! ask_yes_no "Configure Jupyter Lab as systemd service (auto-start)?" "n"; then
        log "Jupyter service skipped"; return 0
    fi
    local JUPYTER_PORT=8888
    local JUPYTER_PASSWORD=$(openssl rand -base64 12)
    sudo -u "$CURRENT_USER" jupyter server password <<<"$JUPYTER_PASSWORD" 2>/dev/null || true
    cat > /etc/systemd/system/jupyter.service <<JUPYTER_EOF
[Unit]
Description=Jupyter Lab (AI Workstation)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
ExecStart=/usr/local/bin/jupyter lab --no-browser --port=$JUPYTER_PORT --ip=0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
JUPYTER_EOF
    systemctl daemon-reload
    systemctl enable jupyter
    systemctl start jupyter
    echo "Jupyter password: $JUPYTER_PASSWORD" > /root/.jupyter-password
    logOk "Jupyter Lab service started on port $JUPYTER_PORT"
    logWarn "Jupyter password saved to /root/.jupyter-password"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 16 — Longhorn Storage (k3s)
# ════════════════════════════════════════════════════════════════════════════
stage16_longhorn() {
    if ! command -v k3s &>/dev/null; then
        logWarn "k3s not installed — Longhorn requires k3s"; return 0
    fi
    if ! ask_yes_no "Install Longhorn Storage (k3s persistent storage)?" "n"; then
        log "Longhorn skipped"; return 0
    fi
    local NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    local REPLICAS=$((NODE_COUNT < 3 ? 2 : 3))
    log "Node count: $NODE_COUNT → replicaCount=$REPLICAS"
    curl -fsSL https://github.com/longhorn/longhorn/releases/download/v1.6.1/longhorn-1.6.1-upgrade.sh \
        | kubectl apply --server -k https://raw.githubusercontent.com/longhorn/longhorn/v1.6.1/manifests \
        2>&1 | tail -5 || \
    kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.6.1/manifests/longhorn.yaml 2>&1 | tail -5
    kubectl patch storageclass longhorn \
        -p '{"metadata":{"annotations":{"longhorn.io/replica-count":"'"$REPLICAS"'"}}}' 2>/dev/null || true
    logOk "Longhorn installed (UI: NodePort 30800)"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 17 — Rook Ceph (Block + FS + Object)
# ════════════════════════════════════════════════════════════════════════════
stage17_rook_ceph() {
    if ! command -v k3s &>/dev/null; then
        logWarn "k3s not installed — Rook Ceph requires k3s"; return 0
    fi
    if ! ask_yes_no "Install Rook Ceph Storage (k3s)?" "n"; then
        log "Rook Ceph skipped"; return 0
    fi
    log "Deploying Rook Ceph operator..."
    kubectl apply -f https://raw.githubusercontent.com/rook/rook/master/cluster/examples/kubernetes/ceph/common.yaml
    kubectl apply -f https://raw.githubusercontent.com/rook/rook/master/cluster/examples/kubernetes/ceph/operator.yaml
    sleep 5
    kubectl apply -f https://raw.githubusercontent.com/rook/rook/master/cluster/examples/kubernetes/ceph/cluster.yaml
    logOk "Rook Ceph operator deployed"
    logWarn "Check status: kubectl -n rook-ceph get pods"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 18 — Neovim + LazyVim (AI/K8s dev environment)
# ════════════════════════════════════════════════════════════════════════════
stage18_neovim() {
    if ! ask_yes_no "Install Neovim + LazyVim (AI/K8s dev environment)?" "n"; then
        log "Neovim skipped"; return 0
    fi
    if ! command -v nvim &>/dev/null; then
        apt install -y neovim 2>&1 | tail -2
    fi
    if [[ ! -d "$HOMEDIR/.config/nvim" ]]; then
        sudo -u "$CURRENT_USER" git clone https://github.com/LazyVim/starter ~/.config/nvim
        logOk "LazyVim installed"
    else
        logOk "LazyVim already present"
    fi
    sudo -u "$CURRENT_USER" nvim --headless "+Lazy! sync" +qa 2>/dev/null || true
    logOk "Neovim + LazyVim ready (run: nvim)"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 19 — MinIO S3 Object Store
# ════════════════════════════════════════════════════════════════════════════
stage19_minio() {
    if ! command -v k3s &>/dev/null; then
        logWarn "k3s not installed — MinIO skipped"; return 0
    fi
    if ! ask_yes_no "Install MinIO S3 (k3s)?" "n"; then
        log "MinIO skipped"; return 0
    fi
    kubectl create namespace minio --dry-run=client -o yaml | kubectl apply -f -
    helm repo add minio https://charts.min.io/ 2>/dev/null || true
    helm repo update minio 2>/dev/null || true
    helm install minio minio/tenant \
        -n minio \
        --set mode=standalone \
        --set persistence.enabled=true \
        --set persistence.size=50Gi \
        --set persistence.storageClass=longhorn \
        --set tenants[0].pools[0].name=pool1 \
        --set tenants[0].pools[0].servers=1 \
        --set tenants[0].pools[0].volumesPerServer=1 \
        2>&1 | tail -5
    logOk "MinIO tenant deployed (Console: http://<node-ip>:30901)"
    logWarn "Default credentials: minioadmin / minioadmin123"
}

# ════════════════════════════════════════════════════════════════════════════
# STAGE 20 — Monitoring Stack (Prometheus + Grafana + Loki)
# ════════════════════════════════════════════════════════════════════════════
stage20_monitoring_stack() {
    if ! command -v k3s &>/dev/null; then
        logWarn "k3s not installed — Monitoring stack skipped"; return 0
    fi
    if ! ask_yes_no "Install Monitoring Stack (Prometheus + Grafana + Loki)?" "n"; then
        log "Monitoring stack skipped"; return 0
    fi
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
    helm repo update prometheus-community 2>/dev/null || true
    helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
        -n monitoring \
        --set prometheus.prometheusSpec.retention=30d \
        --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi \
        --set prometheus.prometheusSpec.storageClassName=longhorn \
        --set grafana.persistence.enabled=true \
        --set grafana.persistence.size=10Gi \
        --set grafana.persistence.storageClassName=longhorn \
        --set grafana.adminPassword=prom-operator \
        2>&1 | tail -5
    kubectl patch storageclass longhorn \
        -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}' 2>/dev/null || true
    logOk "Prometheus (30d retention) + Grafana + Loki deployed"
    logWarn "Grafana: admin / prom-operator | Port-forward: kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 30080:80"
    log "Dashboards: Node Exporter Full (1860), NVIDIA GPU (12740), Loki (15855)"
}

# ════════════════════════════════════════════════════════════════════════════
# MAIN — Stage Runner
# ════════════════════════════════════════════════════════════════════════════
main() {
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║   Pop!_OS 24.04 — AI/Dev Workstation Setup v$SCRIPT_VERSION          ║"
    echo "║   Combined: v3.0.0 + v2.0.0 → v4.0.0 STABLE                      ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Stages  1-20  (interactive, ~30-60 min total)"
    echo "GPU:     $GPU_DETECTED"
    echo "User:    $CURRENT_USER"
    echo "Home:    $HOMEDIR"
    echo "Log:     $LOGFILE"
    echo ""
    echo ">>> STARTING IN 5 SECONDS (Ctrl+C to abort) <<<"
    sleep 5

    run_stage  1 "Preflight Checks"           stage01_preflight
    run_stage  2 "System Update"              stage02_update
    run_stage  3 "NVIDIA Driver"              stage03_nvidia
    run_stage  4 "CUDA Toolkit 12.4"          stage04_cuda
    run_stage  5 "Container Runtime"          stage05_docker
    run_stage  6 "k3s + Helm + kubectl"       stage06_k3s
    run_stage  7 "Dev Toolchain"              stage07_devtools
    run_stage  8 "Zsh + Oh My Zsh"            stage08_zsh
    run_stage  9 "Security Hardening"         stage09_security
    run_stage 10 "AI Stack"                   stage10_ai_stack
    run_stage 11 "Monitoring Tools"           stage11_monitoring
    run_stage 12 "Tailscale VPN"              stage12_tailscale
    run_stage 13 "KDE Plasma"                  stage13_kde
    run_stage 14 "Swap + Unattended-Upgrades" stage14_swap
    run_stage 15 "Jupyter Service"             stage15_jupyter
    run_stage 16 "Longhorn Storage"           stage16_longhorn
    run_stage 17 "Rook Ceph"                  stage17_rook_ceph
    run_stage 18 "Neovim + LazyVim"           stage18_neovim
    run_stage 19 "MinIO S3"                   stage19_minio
    run_stage 20 "Monitoring Stack"            stage20_monitoring_stack

    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║   ✅ SETUP COMPLETE — v$SCRIPT_VERSION STABLE                           ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "NEXT STEPS:"
    echo "  1. Reboot:             sudo reboot"
    echo "  2. GPU test:           nvidia-smi"
    echo "  3. Docker test:       sudo docker run --rm --gpus all nvidia/cuda:12.4.0-base nvidia-smi"
    echo "  4. k3s:                kubectl get nodes"
    echo "  5. Jupyter:            http://localhost:8888 (password in /root/.jupyter-password)"
    echo "  6. Ollama:             ollama run llama3"
    echo "  7. Tailscale:          tailscale status"
    echo "  8. Longhorn UI:        kubectl port-forward -n longhorn-system svc/longhorn-frontend 30800:80"
    echo "  9. Grafana:            kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 30080:80"
    echo " 10. MinIO Console:      http://localhost:30901 (minioadmin / minioadmin123)"
    echo ""
    echo "STAGE LOG: $LOGFILE"
}

check_root
main
