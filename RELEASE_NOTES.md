# Pop!_OS 24.04 — AI/Dev Workstation Setup

## Release Notes

### v1.0.0 — ROMA Execution Bridge Production Release (2026-04-18)

> **Status: PRODUCTION** | Git tag [`v1.0.0`](https://github.com/mahaasur13-sys/roma-execution-bridge/releases/tag/v1.0.0) | Helm chart `roma-execution-bridge-1.0.0.tgz`

**Artifacts:**
- Git tag: `v1.0.0` → [github.com/mahaasur13-sys/roma-execution-bridge/releases/tag/v1.0.0](https://github.com/mahaasur13-sys/roma-execution-bridge/releases/tag/v1.0.0)
- Helm chart: `release-artifacts/roma-execution-bridge-1.0.0.tgz` (21 KB, includes Bitnami common dependency)
- Integration test: `scripts/integration-test.sh` (mock validation, exit 0)

**What is ROMA Execution Bridge:**
Closed-loop compute economy control plane for Kubernetes. GPU scheduling, Raft consensus, event sourcing, Stripe billing, multi-tenant SaaS with Kong API gateway, Vault secrets, cert-manager TLS, and RomaTenant CRD auto-provisioning.

**Sprint 2 changes since last release:**
- Vault + SealedSecrets secret management
- Kong API Gateway (rate limiting, tenant routing, branding injection)
- Stripe webhook (async via Redis Stream, tenant sync)
- cert-manager + Let's Encrypt TLS on all ingress
- RomaTenant CRD + kopf operator (auto-provisioning)
- Integration test suite (`scripts/integration-test.sh`)

**Install:**
```bash
# From Helm chart:
helm install roma oci://ghcr.io/mahaasur13-sys/charts/roma-execution-bridge \
  --version 1.0.0 -n roma-system --create-namespace

# Or from local tarball:
helm install roma ./release-artifacts/roma-execution-bridge-1.0.0.tgz \
  -n roma-system --create-namespace
```

**Quick test:**
```bash
make k8s-deploy-home      # Deploy to k3s
make integration-test     # Run mock integration test
```

---

### v4.0.0 — Combined Stable (2026-04-18)

> **Status: STABLE** | Merged `v3.0.0` + `v2.0.0` → single unified script  
> File: `pop-os-setup-v4.sh` (673 lines, bash syntax ✅ verified)

**Changelog vs v3.0.0 + v2.0.0:**
- ✅ Stages 1–20 in single script (was split across two files)
- ✅ All 20 stages covered: base → GPU → AI → k8s → storage → monitoring
- ✅ `RUNTIME` global (docker/podman), `USE_CUDA`/`GPU_DETECTED` flags
- ✅ Longhorn Stage 16 (v1.6.1, smart replica count from node count)
- ✅ Rook Ceph Stage 17 (v1.14.x, common + operator + cluster)
- ✅ MinIO Stage 19 (tenant v1.4.0, 50Gi, longhorn storageClass)
- ✅ Prometheus + Grafana + Loki Stage 20 (kube-prometheus-stack v6.x, 30d retention, 50Gi PVC)
- ✅ Neovim + LazyVim Stage 18
- ✅ Tailscale Funnel + Serve (Stage 12)
- ✅ Jupyter systemd service (Stage 15)
- ✅ Idempotent: skips already-installed components
- ✅ `bash -n pop-os-setup-v4.sh` → ✅ Syntax OK

**Quick Start:**
```bash
# Full run (~30-60 min):
sudo bash pop-os-setup-v4.sh

# Syntax check:
bash -n pop-os-setup-v4.sh

# Single stage (by env var):
SKIP_STAGES="1,2,3" sudo bash pop-os-setup-v4.sh
```

**Stage Map (20 stages):**

| # | Component | Type |
|---|-----------|------|
| 1 | Preflight checks | ✅ Auto |
| 2 | System update | ✅ Auto |
| 3 | NVIDIA Driver + system76-power | ✅ Auto (GPU) |
| 4 | CUDA Toolkit 12.4 + cuDNN | 🔄 Interactive (GPU) |
| 5 | Docker CE **или** Podman (choose) | 🔄 Interactive |
| 6 | k3s + Helm + kubectl + NVIDIA device plugin | 🔄 Interactive |
| 7 | Dev Toolchain | ✅ Auto |
| 8 | Zsh + Oh My Zsh + plugins | ✅ Auto |
| 9 | Security: UFW, fail2ban, sysctl tuning | 🔄 Interactive |
| 10 | AI Stack: PyTorch (CPU↔GPU), TensorFlow, Jupyter, Ollama | 🔄 Interactive |
| 11 | Monitoring: nvtop, glances, btop | 🔄 Interactive |
| 12 | Tailscale VPN + Funnel + Serve | 🔄 Interactive |
| 13 | KDE Plasma Desktop | 🔄 Interactive |
| 14 | SWAP 4GB + Unattended-Upgrades (security-only, no auto-reboot) | ✅ Auto |
| 15 | Jupyter Lab as systemd service | 🔄 Interactive |
| 16 | Longhorn Storage (k3s) | 🔄 Interactive |
| 17 | Rook Ceph (Block + FS + Object) | 🔄 Interactive |
| 18 | Neovim + LazyVim (AI/K8s) | 🔄 Interactive |
| 19 | MinIO S3 Object Store (k3s) | 🔄 Interactive |
| 20 | Prometheus + Grafana + Loki (k3s) | 🔄 Interactive |

**Conditional logic:**
```
GPU detected = yes + CUDA chosen → PyTorch cu124 + TensorFlow [and-cuda]
GPU detected = no               → PyTorch CPU + TensorFlow (CPU)
k3s not installed                → Stages 16–20 (storage/monitoring) skipped
```

**Failure conditions → abort:**
- No internet on Stage 1
- GPU not detected (CUDA stages auto-skipped, not aborted)

---

### v3.0.0 — AI/Dev Workstation v3 (2026-04-18)

**🎯 Status: STABLE — Production Ready**

> Исправленная версия v2.0. Устранены конфликты PyTorch/CUDA, добавлены Docker/Podman выбор, условные stage, интерактивные диалоги.

**Что исправлено vs v2.0:**

- ✅ PyTorch CPU ↔ GPU: условная установка по результату `nvidia-smi`
- ✅ Docker ↔ Podman: интерактивный выбор на Stage 6
- ✅ CUDA: только если GPU обнаружен, иначе пропускается
- ✅ fail2ban: только если пользователь подтвердит (SSH-доступ извне)
- ✅ unattended-upgrades: security-only, `Automatic-Reboot "false"` (не убьёт training в 3 AM)
- ✅ sysctl: явные параметры (`vm.swappiness`, `tcp_rmem/wmem` для больших моделей)
- ✅ system76-power: опционально (для ноутбуков с гибридной графикой)
- ✅ Stages 12–15: теперь не пропущены (k3s, мониторинг, Jupyter)

**Quick Start:**
```bash
# Full run (all stages, ~20-40 min):
sudo bash pop-os-setup.sh

# With Tailscale authkey (automation):
TAILSCALE_AUTHKEY=tskey-xxxx sudo bash pop-os-setup.sh

# Syntax check only:
bash -n pop-os-setup.sh
```

**Stage Map:**

| # | Component | Type |
|---|-----------|------|
| 1 | Preflight & System Update | ✅ Auto |
| 2 | NVIDIA Driver + system76-power | ✅ Auto (GPU) |
| 3 | Dev Toolchain (git, htop, tmux, neovim...) | ✅ Auto |
| 4 | Zsh + Oh My Zsh + plugins | ✅ Auto |
| 5 | KDE Plasma Desktop | ✅ Auto |
| 6 | Docker **или** Podman (choose) | 🔄 Interactive |
| 7 | CUDA Toolkit 12.4 + cuDNN | 🔄 Interactive (GPU) |
| 8 | AI Stack: PyTorch (CPU/GPU), TF, Jupyter, HF, Ollama | 🔄 Interactive |
| 9 | Security: UFW, fail2ban, sysctl tuning | 🔄 Interactive |
| 10 | SSH Server | ✅ Auto |
| 11 | SWAP 4GB + Unattended-Upgrades (security only) | ✅ Auto |
| 12 | Tailscale VPN + Funnel + Serve | 🔄 Interactive |
| 13 | k3s + Helm + kubectl | 🔄 Interactive |
| 14 | Monitoring: nvtop, glances, btop | 🔄 Interactive |
| 15 | Jupyter Lab as systemd service | 🔄 Interactive |

**Conditional logic ( ключевое ):**
```
GPU detected = yes + CUDA chosen → PyTorch cu124 + TensorFlow [and-cuda]
GPU detected = no               → PyTorch CPU + TensorFlow (CPU)
GPU not detected               → Stage 7 (CUDA) skipped entirely
```

---

### v1.9 — Stage 20: Monitoring Stack (Prometheus + Grafana + Loki) (2026-04-18)

**Stage 20: Monitoring Stack**

- **Prometheus** (kube-prometheus-stack v6.x)
  - 30d retention
  - 50Gi PVC (Longhorn)
  - Stateful storage for WAL

- **Grafana** (embedded in kube-prometheus-stack)
  - 10Gi PVC (Longhorn)
  - Default user: `admin` / `prom-operator`
  - Dashboards: Node Exporter Full (1860), NVIDIA GPU (12740), Loki (15855)

- **Loki** (Grafana Loki v3.x)
  - 30Gi PVC (Longhorn)
  - Replaces Prometheus for log aggregation (hot storage)

- **Node Exporter** (already deployed in Stage 11)
  - Patched with tolerations for control-plane nodes

**Usage:**
```bash
# Single stage:
sudo bash Pop_OS_AI_Dev_Setup.sh --stage 20

# All stages:
sudo bash Pop_OS_AI_Dev_Setup.sh

# Port-forward:
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 30090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 30080:80 &
```

**Grafana password:**
```bash
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

**Import dashboards:**
| ID | Dashboard |
|----|-----------|
| 1860 | Node Exporter Full |
| 12740 | NVIDIA GPU |
| 15855 | Loki |

---

### v1.8 — Stage 19: Tailscale Network Isolation + Cluster VPN Mesh (2026-04-18)

**Stage 19: Tailscale VPN + Cluster Mesh**

- Tailscale installed via official install script
- IP forwarding enabled (`/etc/sysctl.d/99-tailscale.conf`)
- Funnel on port 443 for inbound traffic through Tailscale
- Tailscale Serve routing local HTTPS services
- Authkey support (`TAILSCALE_AUTHKEY` env var) for non-interactive join
- Mesh-ready: other nodes join via `curl -fsSL https://tailscale.com/install.sh | sh - && sudo tailscale up`

**Usage:**
```bash
# Interactive (manual auth):
sudo bash Pop_OS_AI_Dev_Setup.sh --stage 19

# With authkey (automation):
TAILSCALE_AUTHKEY=tskey-auth-xxxx sudo bash Pop_OS_AI_Dev_Setup.sh --stage 19
```

**Post-install:**
```bash
tailscale status
sudo tailscale funnel 443
sudo tailscale serve https+insecure://localhost:3000
sudo tailscale up --authkey=<key>
```

---

### v1.7 — Stage 18: Neovim + LazyVim Full AI/K8s (2026-04-18)

Full AI/K8s development environment via LazyVim starter:

- Neovim 0.10+ via system package manager
- LazyVim as base config (Lazy.nvim plugin manager)
- LSP servers: `pyright`, `lua_ls`, `yamlls`, `helm_ls`, `terraform_ls`, `gopls`, `dockerls`, `jsonls`, `marksman`
- Treesitter: `python`, `lua`, `yaml`, `hcl`, `dockerfile`, `bash`, `json`, `toml`, `markdown`
- Plugins: `telescope.nvim`, `which-key.nvim`, `gitsigns.nvim`, `nvim-dap`, `venv-selector.nvim`, `lazygit.nvim`, `copilot.lua`
- Theme: Catppuccin Mocha

**Usage:**
```bash
sudo bash Pop_OS_AI_Dev_Setup.sh --stage 18
nvim +Lazy! sync
```

---

### v1.6 — Stage 17: MinIO S3 Object Store (2026-04-18)

MinIO Tenant via official Helm chart `minio/tenant` v1.4.0:
- Standalone, 1 replica, 50Gi PVC (Longhorn)
- Console UI: `http://<node-ip>:30901` — user: `minioadmin` / pass: `minioadmin123`
- S3 API: `http://<node-ip>:30900`
- `mc` alias setup + backup examples for Longhorn and roma models/datasets

---

### v1.5 — Stage 16: Rook Ceph (Block + FS + Object) (2026-04-18)

Rook Ceph via Helm v1.14.3 operator:
- CephCluster with 3 mons on `host` network
- StorageClass `rook-ceph-block` (RBD, Retain)
- StorageClass `rook-cephfs` (CephFS)
- Dashboard enabled (port 7000)
- Ceph v18.2.2

---

### v1.4 — Stage 15: Longhorn Storage (2026-04-18)

Longhorn via Helm with smart replica count:
- 1-2 nodes → `replicaCount=2`, ≥3 nodes → `replicaCount=3`
- Default `StorageClass: longhorn`
- Longhorn UI via NodePort `:30800`
- CSI tuning for home cluster

---

### v1.3 — Stage 6-14: k3s Multi-Node + Tailscale + GPU (2026-04-08)

- Auto-detect server/agent role (`K3S_ROLE=auto|server|agent`)
- Tailscale IP as `--node-external-ip`
- Join token saved to `/var/lib/k3s/join-token-<hostname>.txt`
- GPU labels on all nodes
- CUDA 12.4 + Docker + NVIDIA Container Toolkit

---

### v1.2 — Stage 1-5: Base System + GPU + Dev (2026-04-04)

- Zsh + Oh My Zsh + autosuggestions + syntax-highlighting
- Security: UFW, fail2ban, unattended-upgrades, sysctl hardening
- KDE Plasma customization
- AI Stack: PyTorch 2.2 + Transformers + Gradio + LangChain
- GPU Monitoring: nvtop, DCGM, prometheus-node-exporter

---

## Stage Map

| # | Component | Status |
|---|-----------|--------|
| 1 | Preflight checks | ✅ |
| 2 | System update | ✅ |
| 3 | NVIDIA Driver | ✅ |
| 4 | CUDA 12.4 + cuDNN | ✅ |
| 5 | Docker + NVIDIA Container Toolkit | ✅ |
| 6 | k3s + NVIDIA Device Plugin | ✅ |
| 7 | Dev Toolchain | ✅ |
| 8 | Zsh + Oh My Zsh | ✅ |
| 9 | Security (UFW, fail2ban) | ✅ |
| 10 | AI Stack (PyTorch, Transformers) | ✅ |
| 11 | GPU Monitoring | ✅ |
| 12 | KDE Plasma | ✅ |
| 13 | Tailscale VPN | ✅ |
| 14 | k3s Multi-Node | ✅ |
| 15 | Longhorn Storage | ✅ |
| 16 | Rook Ceph | ✅ |
| 17 | MinIO S3 | ✅ |
| 18 | Neovim + LazyVim | ✅ |
| 19 | Tailscale VPN Mesh | ✅ |
| 20 | Monitoring (Prometheus + Grafana + Loki) | ✅ |

## Planned / TODO

| Stage | Component | Status |
|-------|-----------|--------|
| 21 | CUDA Toolkit (full) | 🟡 |
| 22 | ROS2 Stack | 🟡 |
| 23 | k3s Kubernetes (full) | 🟡 |
| 24 | Zsh + Oh My Zsh tuning | 🟡 |
| 25 | KDE Full Customization | 🟡 |
| 26 | AI Workstation (vLLM, Ollama) | 🟡 |