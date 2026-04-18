# Pop!_OS 24.04 — AI/Dev Workstation Auto-Setup

> One-command setup for a production-ready AI/developer workstation on Pop!_OS 24.04 LTS (NVIDIA Edition).

## Features

- **26 automated stages** — from USB boot to fully configured system
- **4 profiles**: `workstation`, `cluster`, `ai-dev`, `full`
- **NVIDIA GPU** — proprietary driver, CUDA 12.4, cuDNN
- **AI Stack** — PyTorch, TensorFlow, Jupyter Lab, Ollama, vLLM
- **k3s Kubernetes** — single/multi-node with Longhorn, Rook Ceph, ArgoCD
- **Developer tools** — Zsh + Oh My Zsh, Neovim + LazyVim, Docker/Podman
- **Monitoring** — Prometheus, Grafana, Loki, nvtop, btop
- **Security hardening** — UFW, fail2ban, unattended-upgrades, sysctl tuning

## Quick Start

```bash
# Full run (all 26 stages):
sudo bash pop-os-setup-v5.sh

# AI/Dev workstation only (no k8s/storage):
sudo PROFILE=ai-dev bash pop-os-setup-v5.sh

# Syntax check:
bash -n pop-os-setup-v5.sh
```

## Profiles

| Profile | Stages | Use Case |
|---------|--------|----------|
| `workstation` | 1–3, 7–15, 18 | Base dev + AI (no k8s/storage) |
| `cluster` | 1–3, 6–8, 14, 16–20 | k3s + storage + monitoring |
| `ai-dev` | 1–15, 18 | Dev + AI + GPU (no storage) |
| `full` | 1–26 | Everything |

## Stage Map

| # | Component | Profile |
|---|-----------|---------|
| 1 | Preflight checks | core |
| 2 | System update | core |
| 3 | NVIDIA Driver + system76-power | core |
| 4 | CUDA Toolkit 12.4 + cuDNN | workstation/ai-dev/full |
| 5 | Docker CE OR Podman | workstation/ai-dev/full |
| 6 | k3s + Helm + kubectl + NVIDIA device plugin | cluster/full |
| 7 | Dev Toolchain | core |
| 8 | Zsh + Oh My Zsh + plugins | core |
| 9 | Security: UFW, fail2ban, sysctl | workstation/ai-dev/full |
| 10 | AI Stack: PyTorch, TensorFlow, Jupyter, Ollama | workstation/ai-dev/full |
| 11 | Monitoring: nvtop, glances, btop | workstation/ai-dev/full |
| 12 | Tailscale VPN + Funnel + Serve | workstation/ai-dev/full |
| 13 | KDE Plasma Desktop | workstation/ai-dev/full |
| 14 | SWAP 4GB + Unattended-Upgrades | core |
| 15 | Jupyter Lab as systemd service | workstation/ai-dev/full |
| 16 | Longhorn Storage | cluster/full |
| 17 | Rook Ceph (Block + FS + Object) | cluster/full |
| 18 | Neovim + LazyVim | workstation/ai-dev/full |
| 19 | MinIO S3 Object Store | cluster/full |
| 20 | Prometheus + Grafana + Loki | cluster/full |
| 21 | CUDA Full Stack (Nsight, nvprof, cuBLAS) | full |
| 22 | ROS2 Humble (Gazebo, colcon) | full |
| 23 | k3s Full (Ingress NGINX, MetalLB, cert-manager, ArgoCD) | full |
| 24 | Zsh Tuning (Starship, AI/K8s aliases) | full |
| 25 | KDE Full Customization (latte-dock, Breeze Dark) | full |
| 26 | AI Workstation (vLLM, Text Generation WebUI, Ollama) | full |

## Conditional Logic

```
GPU detected = no  → Stages 3, 4, 21 (CUDA) auto-skipped
k3s not installed   → Stages 16–20, 23 (storage/monitoring) auto-skipped
PROFILE=workstation → stages 1–3, 7–15, 18 (no k8s, no storage)
PROFILE=cluster     → stages 1–3, 6–8, 14, 16–20 (dev tools minimal)
PROFILE=ai-dev      → stages 1–15, 18 (dev + AI, no storage)
PROFILE=full        → all 26 stages
```

## Requirements

- Pop!_OS 24.04 LTS (NVIDIA ISO)
- UEFI boot, Secure Boot can be disabled
- Minimum 50GB disk, 16GB RAM recommended
- NVIDIA GPU (GeForce/Quadro/RTX)
- Internet connection (Ethernet recommended for k8s stages)

## Documentation

- `Pop_OS_KDE_NVIDIA_Guide.md` — detailed step-by-step guide
- `RELEASE_NOTES.md` — full version history and changelog

## License

MIT
