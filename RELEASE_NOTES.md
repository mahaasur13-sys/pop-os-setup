# Pop!_OS 24.04 — AI/Dev Workstation Setup

## Release Notes

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