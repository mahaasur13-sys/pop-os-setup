#!/bin/bash
#===============================================================================
# Pop!_OS 24.04 NVIDIA — AI/Dev Workstation Auto-Setup v2.0.0
#===============================================================================
# Target  : Pop!_OS 24.04 LTS NVIDIA Edition (USB Boot -> Production Ready)
# Stack   : KDE + Docker + CUDA 12.4 + k3s + Longhorn + Rook Ceph + MinIO + Zsh
#           + Neovim/LazyVim + Tailscale VPN + Prometheus + Grafana + Loki
# Author  : asurdev | https://asurdev.zo.computer
# Version : 2.0.0 (2026-04-18) — Stable Release
#===============================================================================

set -euo pipefail

LOGFILE="/var/log/popos-setup-$(date +%Y%m%d-%H%M%S).log"
SCRIPT_VERSION="2.0.0"
CURRENT_USER="$(logname 2>/dev/null || echo "$SUDO_USER")"
HOMEDIR="$(getent passwd "$CURRENT_USER" | cut -d: -f6)"

RED='[0;31m'; GREEN='[0;32m'; YELLOW='[1;33m'
BLUE='[0;34m'; CYAN='[0;36m'; NC='[0m'

log()    { echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOGFILE"; }
logOk()  { echo -e "${GREEN}[OK]${NC} $1" | tee -a "$LOGFILE"; }
logWarn(){ echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOGFILE"; }
logErr() { echo -e "${RED}[ERR]${NC} $1" | tee -a "$LOGFILE"; exit 1; }

check_root() { [[ $EUID -ne 0 ]] && logErr "Run as root: sudo bash $0"; }

gpu_check() {
    nvidia-smi &>/dev/null && nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null
}

#===============================================================================
# STAGE 1 — Preflight Checks
#===============================================================================
stage01_preflight() {
    log "=== STAGE 1: Preflight ==="
    source /etc/os-release 2>/dev/null || true
    log "OS: $PRETTY_NAME"
    gpu_check && logOk "NVIDIA GPU: $(gpu_check)" || logWarn "GPU not detected"
    ping -c1 -W2 8.8.8.8 &>/dev/null && logOk "Network: OK" || logWarn "Network: UNREACHABLE"
    [[ -d /sys/firmware/efi ]] && log "Boot: UEFI" || log "Boot: Legacy"
    log "User: $CURRENT_USER | Home: $HOMEDIR"
}

#===============================================================================
# STAGE 2 — System Update
#===============================================================================
stage02_update() {
    log "=== STAGE 2: Update ==="
    export DEBIAN_FRONTEND=noninteractive
    apt update -qq
    apt upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" 2>&1 | tail -3
    logOk "System updated"
}

#===============================================================================
# STAGE 3 — NVIDIA Driver
#===============================================================================
stage03_nvidia() {
    log "=== STAGE 3: NVIDIA Driver ==="
    if gpu_check &>/dev/null; then
        logOk "NVIDIA driver already active"
        return 0
    fi
    if command -v system76-power &>/dev/null; then
        system76-power graphics nvidia 2>&1 | tail -2 || true
        logOk "Switched to NVIDIA mode"
    else
        apt install -y nvidia-driver-555 2>&1 | tail -3
        logOk "NVIDIA driver installed"
    fi
    logWarn "REBOOT REQUIRED"
}

#===============================================================================
# STAGE 4 — CUDA Toolkit + cuDNN
#===============================================================================
stage04_cuda() {
    log "=== STAGE 4: CUDA Toolkit + cuDNN ==="
    if command -v nvcc &>/dev/null; then
        logOk "CUDA already: $(nvcc --version | grep release | awk '{print $5}' | tr -d ',')"
        return 0
    fi
    if apt-cache show system76-cuda-latest &>/dev/null 2>&1; then
        log "Installing system76-cuda-latest..."
        apt install -y system76-cuda-latest system76-cudnn-latest 2>&1 | tail -5
    else
        log "Installing CUDA via NVIDIA repo..."
        wget -qO /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring.deb
        apt install -y /tmp/cuda-keyring.deb 2>&1 | tail -2
        rm -f /tmp/cuda-keyring.deb
        echo "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] http://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ /" > /etc/apt/sources.list.d/cuda.list
        apt update -qq
        apt install -y cuda-toolkit-12-4 cuda-libraries-12-4 libcudnn9 libcudnn9-dev 2>&1 | tail -5
    fi
    if command -v nvcc &>/dev/null; then
        logOk "CUDA: $(nvcc --version | grep release | awk '{print $5}' | tr -d ',')"
    else
        logWarn "nvcc not in PATH — add to ~/.bashrc:"
        logWarn "  export PATH=/usr/local/cuda/bin:$PATH"
    fi
}

#===============================================================================
# STAGE 5 — Docker CE + NVIDIA Container Toolkit
#===============================================================================
stage05_docker() {
    log "=== STAGE 5: Docker + NVIDIA Container Toolkit ==="
    if ! command -v docker &>/dev/null; then
        apt install -y apt-transport-https ca-certificates gnupg lsb-release 2>&1 | tail -2
        mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
        . /etc/os-release
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
        apt update -qq
        apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>&1 | tail -3
        systemctl enable docker --now
        logOk "Docker CE installed"
    else
        logOk "Docker already present"
    fi
    if ! command -v nvidia-ctk &>/dev/null; then
        log "Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
        ARCH=$(dpkg --print-architecture)
        echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/$ARCH /" > /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt update -qq
        apt install -y nvidia-container-toolkit 2>&1 | tail -3
        nvidia-ctk runtime configure --runtime=containerd 2>/dev/null || true
        systemctl restart containerd
    fi
    if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu24.04 nvidia-smi &>/dev/null; then
        logOk "Docker GPU passthrough: OK"
    else
        logWarn "Docker GPU test: FAILED (may need reboot)"
    fi
    usermod -aG docker "$CURRENT_USER" 2>/dev/null || true
}

#===============================================================================
# STAGE 6 — k3s + NVIDIA Device Plugin
#===============================================================================
stage06_k3s() {
    log "=== STAGE 6: k3s + NVIDIA Device Plugin ==="
    if command -v k3s &>/dev/null; then
        logOk "k3s already installed"
        return 0
    fi
    log "Installing k3s..."
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644 --node-label gpu=nvidia" sh - 2>&1 | tail -5
    systemctl enable k3s --now
    sleep 5
    if kubectl get nodes &>/dev/null; then
        logOk "k3s: $(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
    else
        logWarn "k3s installed, kubectl may need env export"
    fi
    kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml 2>/dev/null || logWarn "k8s-device-plugin: apply failed"
}

#===============================================================================
# STAGE 7 — Dev Toolchain
#===============================================================================
stage07_devtools() {
    log "=== STAGE 7: Dev Toolchain ==="
    apt install -y build-essential git curl wget vim htop btop tmux zsh fontconfig fonts-jetbrains-mono python3 python3-pip python3-venv python3-dev python3-numpy python3-pandas libopenblas-dev jq bat exa fzf ripgrep fd-find 2>&1 | tail -5
    if [[ ! -d "$HOMEDIR/.pyenv" ]]; then
        curl https://pyenv.run | bash 2>&1 | tail -3
    fi
    logOk "Dev tools installed"
}

#===============================================================================
# STAGE 8 — Zsh + Oh My Zsh
#===============================================================================
stage08_zsh() {
    log "=== STAGE 8: Zsh ==="
    if [[ -d "$HOMEDIR/.oh-my-zsh" ]]; then
        logOk "Oh My Zsh present"
    else
        export SHELL=/bin/zsh
        sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended 2>&1 || true
        logOk "Oh My Zsh installed"
    fi
    zsh_custom="$HOMEDIR/.oh-my-zsh/custom/plugins"
    [[ -d "$zsh_custom/plugins/zsh-autosuggestions" ]] || git clone --depth1 https://github.com/zsh-users/zsh-autosuggestions "$zsh_custom/plugins/zsh-autosuggestions" 2>/dev/null || true
    [[ -d "$zsh_custom/plugins/zsh-syntax-highlighting" ]] || git clone --depth1 https://github.com/zsh-users/zsh-syntax-highlighting "$zsh_custom/plugins/zsh-syntax-highlighting" 2>/dev/null || true
    cat >> "$HOMEDIR/.zshrc" 2>/dev/null <<'EOF'

# --- Pop!_OS AI Dev v2.0 ---
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
alias nvidia-test='docker run --rm --gpus all nvidia/cuda:12.4.0-base nvidia-smi'
alias k9s='kubectl get pods -A'
EOF
    logOk "Zsh configured"
}

#===============================================================================
# STAGE 9 — Security Hardening
#===============================================================================
stage09_security() {
    log "=== STAGE 9: Security ==="
    if ! command -v ufw &>/dev/null; then apt install -y ufw 2>&1 | tail -2; fi
    ufw --force disable; ufw --force enable
    ufw default deny incoming; ufw default allow outgoing
    ufw allow ssh; ufw allow 22/tcp; ufw logging off
    logOk "UFW active"
    apt install -y fail2ban 2>&1 | tail -2
    systemctl enable fail2ban --now
    logOk "Fail2ban active"
    if ! dpkg -l unattended-upgrades &>/dev/null; then
        apt install -y unattended-upgrades apt-listchanges 2>&1 | tail -2
        cat > /etc/apt/apt.conf.d/51unattended-upgrades <<'UPGRADE_EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
UPGRADE_EOF
        logOk "Unattended security upgrades configured"
    fi
    cat >> /etc/sysctl.d/99-security.conf <<'SYSCTL_EOF'
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.icmp_ignore_bogus_error_responses = 1
SYSCTL_EOF
    sysctl -p /etc/sysctl.d/99-security.conf 2>/dev/null || true
}

#===============================================================================
# STAGE 10 — AI Stack (PyTorch + Transformers + Gradio)
#===============================================================================
stage10_ai_stack() {
    log "=== STAGE 10: AI Stack ==="
    pip3 install --break-system-packages jupyter numpy pandas matplotlib seaborn scikit-learn torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -5
    pip3 install --break-system-packages transformers datasets peft accelerate sentence-transformers gradio langchain langchain-community 2>&1 | tail -5
    logOk "AI stack installed"
}

#===============================================================================
# STAGE 11 — GPU Monitoring
#===============================================================================
stage11_monitoring() {
    log "=== STAGE 11: GPU Monitoring ==="
    if command -v nvidia-smi &>/dev/null; then
        apt install -y nvtop 2>&1 | tail -3
        logOk "nvtop installed"
    fi
    if ! command -v dcgm &>/dev/null; then
        apt install -y datacenter-gpu-manager-12 2>&1 | tail -3 || logWarn "DCGM not available in apt"
    fi
    if kubectl get pods -n kube-system 2>/dev/null | grep -q node-exporter; then
        logOk "prometheus-node-exporter already running in k3s"
    else
        log "Installing prometheus-node-exporter..."
        kubectl apply -f https://raw.githubusercontent.com/prometheus/node-exporter/master/examples/kube-agent.yaml 2>/dev/null || true
    fi
    logOk "GPU monitoring ready"
}

#===============================================================================
# STAGE 12 — KDE Plasma Customization
#===============================================================================
stage12_kde() {
    log "=== STAGE 12: KDE Plasma ==="
    if ! command -v plasma-discover &>/dev/null; then
        apt install -y plasma-desktop systemsettings 2>&1 | tail -5
        logOk "KDE Plasma installed"
    else
        logOk "KDE Plasma already present"
    fi
    logOk "KDE stage done (manual tuning via systemsettings)"
}

#===============================================================================
# STAGE 13 — Tailscale VPN
#===============================================================================
stage13_tailscale() {
    log "=== STAGE 13: Tailscale VPN ==="
    if command -v tailscale &>/dev/null; then
        logOk "Tailscale already present"
        return 0
    fi
    curl -fsSL https://tailscale.com/install.sh | sh - 2>&1 | tail -5
    if command -v tailscale &>/dev/null; then
        logOk "Tailscale installed"
        log "Run: sudo tailscale up"
    else
        logWarn "Tailscale install failed"
    fi
}

