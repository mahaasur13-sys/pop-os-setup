# Pop!_OS 24.04 LTS NVIDIA — AI/Dev Workstation Auto-Setup

> **Scripts:** `pop-os-setup-v5.sh` (stable) | `pop-os-setup.sh` (legacy v3)

**Version:** 5.0.0 (2026-04-18) | **Target:** Pop!_OS 24.04 LTS NVIDIA Edition

---

## Navigation

- [Quick Start](#-quick-start)
- [Profiles](#-profiles)
- [Stages](#-stages-126)
- [Post-Install Verification](#-post-install-verification)
- [Troubleshooting](#-troubleshooting)

---

## 🚀 Quick Start

### 1. Download

```bash
curl -fsSL https://raw.githubusercontent.com/mahaasur13-sys/pop-os-setup/main/pop-os-setup-v5.sh -o pop-os-setup-v5.sh
chmod +x pop-os-setup-v5.sh
```

### 2. Run

```bash
# Full profile (default — workstation + cluster + AI-dev)
sudo bash pop-os-setup-v5.sh

# Interactive profile selection
sudo PROFILE=ai-dev bash pop-os-setup-v5.sh

# Workstation only (KDE + Docker + dev tools)
sudo PROFILE=workstation bash pop-os-setup-v5.sh
```

### 3. Verify

```bash
# After script completes
nvidia-smi
kubectl get nodes
docker ps
tailscale status
```

---

## 📦 Profiles

| Profile | Description | When to use |
|---------|-------------|-------------|
| `workstation` | KDE + Docker + Zsh + Python + Neovim | Single machine, dev workstation |
| `cluster` | k3s + Longhorn + networking | Multi-node home lab |
| `ai-dev` | CUDA + Ollama + Jupyter + PyTorch | AI/ML development |
| `full` *(default)* | All of the above | Maximum capability |

### Profile Selection

```bash
# Via environment variable
sudo PROFILE=workstation bash pop-os-setup-v5.sh

# Via interactive prompt (no PROFILE set)
# Script will ask: workstation / cluster / ai-dev / full
```

---

## 📐 Stages 1–26

| Stage | Name | Notes |
|-------|------|-------|
| 1 | Preflight checks | OS, GPU, network detection |
| 2 | System update | apt upgrade |
| 3 | NVIDIA driver | Skipped if no GPU |
| 4 | system76-power | Optional (laptops) |
| 5 | Display Manager | SDDM + KDE Plasma |
| 6 | Dev toolchain | build-essential, git, curl, Python |
| 7 | Container runtime | Docker + Compose v2 |
| 8 | Zsh + Oh My Zsh | Interactive shell |
| 9 | Neovim + LazyVim | Configured IDE |
| 10 | Tailscale | VPN mesh |
| 11 | Firewall | UFW ( deny incoming, allow outgoing) |
| 12 | Python AI stack | pip install numpy pandas torch jupyter |
| 13 | Ollama | Local LLM inference |
| 14 | kubectl + Helm | k8s tooling |
| 15 | k3s | Lightweight Kubernetes |
| 16 | Longhorn | Distributed block storage |
| 17 | MetalLB | Bare-metal load balancing |
| 18 | Cilium CNI | eBPF networking |
| 19 | Rook Ceph | Distributed storage |
| 20 | MinIO | S3-compatible object storage |
| 21 | Monitoring | Prometheus + Grafana + Loki |
| 22 | Backup (Velero) | k8s disaster recovery |
| 23 | Security hardening | fail2ban, UFW rules, auditd |
| 24 | Recovery image | USB rescue partition |
| 25 | Final verification | Full health check |
| 26 | Cleanup | apt autoremove, temp files |

---

## ✅ Post-Install Verification

Run these commands to confirm the system is operational:

### GPU

```bash
nvidia-smi
# Expected: table showing GPU name, driver version, CUDA version

nvidia-smi --query-gpu=name,driver_version,utilization.gpu --format=csv
```

### Container Runtime

```bash
docker ps
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

### Kubernetes

```bash
kubectl get nodes
# Expected: one or more nodes showing Ready

kubectl get pods -A
# Expected: all pods Running

kubectl top nodes
# Expected: CPU/memory usage
```

### Tailscale VPN

```bash
tailscale status
# Expected: shows this node + peered nodes

tailscale ping <node-name>
# Expected: ping reply
```

### Ceph Storage

```bash
kubectl get storageclass
# Expected: ceph-blockpool or similar

kubectl ceph status
# Expected: cluster health: HEALTH_OK
```

### Monitoring Stack

```bash
kubectl get pods -n monitoring
# Expected: prometheus, grafana, loki all Running

curl -s localhost:3000/login | head -5
# Grafana should respond
```

### Backup Verification

```bash
velero backup get
# Expected: shows backups with Completed status

kubectl get backups -A
```

---

## 🔧 Troubleshooting

### Script fails at Stage 1 (Preflight)

```bash
# Check network
ping -c 3 8.8.8.8

# Check GPU visibility
ls /dev/nvidia*

# Check OS version
cat /etc/os-release | grep PRETTY_NAME
```

### NVIDIA driver not loaded

```bash
# Check kernel module
lsmod | grep nvidia

# Reload module
sudo modprobe nvidia
sudo nvidia-smi

# If still failing
sudo apt install --reinstall nvidia-driver-550
sudo reboot
```

### k3s install fails

```bash
# Check swap
swapon --show
# If swap is 0, create one:
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Check ports
sudo ss -tlnp | grep -E '6443|2379|2380'
```

### Longhorn not provisioning

```bash
kubectl get pods -n longhorn-system
# If Longhorn manager is CrashLoopBackOff:
kubectl describe pod -n longhorn-system manager-xxx

# Check mtab
cat /proc/mounts | grep -E 'nfs|cifs|fuse'
```

### Tailscale not connecting

```bash
tailscale status --verbose
# Check ACL: https://login.tailscale.com/admin/acls
tailscale up --reset
```

### Velero backup stuck

```bash
kubectl get pod -n velero
velero backup describe <backup-name> --details
velero restore describe <restore-name> --details
```

### Recovery (total)

```bash
# Re-run script from stage X (replace X with stage number)
# Script is idempotent — safe to re-run from any stage

# Or run single stage directly
sudo bash pop-os-setup-v5.sh --stage 12

# Force reinstall (remove config first)
sudo rm -rf ~/.config/plasma* ~/.config/kwin*
```

---

## 📁 File Structure

```
pop-os-setup/
├── pop-os-setup-v5.sh   # Main script (stable, v5.0.0)
├── README.md            # This file
└── Pop_OS_KDE_NVIDIA_Guide.md  # Manual installation guide
```

---

## 🔐 Security Notes

- Script enables UFW with \`deny incoming\` / \`allow outgoing\`
- fail2ban installed with SSH jail
- AppArmor enforced
- Tailscale uses WireGuard (AES-256-GCM)
- Disk encryption recommended (enable during OS install)
- SSH keys + sudo access only (no password-less root)

---

## ⚠️ Failure Conditions — When to Abort

| Condition | Action |
|-----------|--------|
| \`nvidia-smi\` fails after Stage 3 | Abort, check GPU |
| No network after Stage 1 | Abort, check DHCP/NIC |
| k3s fails to join | Check firewall ports 6443, 2379-2380 |
| Ceph health: \`HEALTH_ERR\` | Do not proceed, fix first |
| Disk encryption unlock fails | Requires reinstall |

---

## 📚 Related Docs

| Document | Purpose |
|----------|---------|
| \`Pop_OS_KDE_NVIDIA_Guide.md\` | Step-by-step manual install (no script) |
| \`home-cluster-iac/README.md\` | Home lab Terraform + Ansible |
| \`AstroFinSentinelV5/README.md\` | AI trading system |

---

*Generated 2026-04-18 — mahaasur13-sys / asurdev.zo.computer*
