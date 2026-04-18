# Pop!_OS 24.04 — AI/Dev Workstation Setup

## Release Notes

### v1.6 — MinIO S3 Object Store (2026-04-18)

**Stage 17: MinIO S3 Object Store**

MinIO Tenant deployed via official Helm chart `minio/tenant` v1.4.0:
- Standalone mode, 1 replica, 50Gi PVC (backed by Longhorn by default)
- Console UI: `http://<node-ip>:30901` — user: `minioadmin` / pass: `minioadmin123`
- S3 API: `http://<node-ip>:30900`
- `mc` (MinIO Client) alias + examples for Longhorn backup and roma models/datasets
- Idempotent — skips if Tenant already exists

**Usage:**
```bash
sudo bash Pop_OS_AI_Dev_Setup.sh --stage 17
# or all stages:
sudo bash Pop_OS_AI_Dev_Setup.sh
```

**mc setup:**
```bash
mc alias set myminio http://localhost:30900 minioadmin minioadmin123
mc admin info myminio
mc mb myminio/roma-models
```

**Storage layer now complete:**
| Layer | Tool | Stage |
|-------|------|-------|
| Block (PVC) | Longhorn + Rook Ceph | 15, 16 |
| Object Store (S3) | MinIO | 17 |
| Backup target | MinIO bucket | — |

---

### v1.5 — Rook Ceph Storage (2026-04-18)

**Stage 16: Rook Ceph (Block + Filesystem + Object)**

Rook Ceph deployed via Helm v1.14.3 operator:
- CephCluster with 3 mons on `host` network (home-lab optimized)
- StorageClass `rook-ceph-block` (RBD, reclaimPolicy: Retain)
- StorageClass `rook-cephfs` (CephFS)
- Dashboard enabled (no SSL for localhost)
- Device filter: `nvme[0-9]n[0-9]|sd[a-z]`
- Ceph v18.2.2 (latest stable)

**Usage:**
```bash
sudo bash Pop_OS_AI_Dev_Setup.sh --stage 16
# or all stages:
sudo bash Pop_OS_AI_Dev_Setup.sh
```

**Dashboard:**
```bash
kubectl port-forward -n rook-ceph svc/rook-ceph-mgr-dashboard 7000:7000
```

**PVC example:**
```yaml
storageClassName: rook-ceph-block
resources:
  requests:
    storage: 100Gi
```

---

### v1.4 — Longhorn Storage (2026-04-18)

**Stage 15: Longhorn Storage**

Longhorn now deployed automatically via Helm with smart replica count:
- 1-2 nodes → `replicaCount=2`
- ≥3 nodes → `replicaCount=3`

Key features:
- Default `StorageClass: longhorn` (patched on install)
- Longhorn UI via NodePort `:30800`
- CSI tuning for home cluster (reduced replica counts for attacher/provisioner/resizer/snapshotter)
- Topology-based scheduling enabled
- Orphan pod cleanup every 30s
- PVC template output for `roma-execution-bridge`

**Usage:**
```bash
sudo bash Pop_OS_AI_Dev_Setup.sh
# Stages 1-15 run sequentially
# Log: /var/log/popos-setup-YYYYMMDD-HHMMSS.log
```

**Multi-node:**
```bash
# SERVER: cat /var/lib/k3s/join-token-<hostname>.txt
# AGENT:  export K3S_URL=https://<server-ip>:6443 K3S_TOKEN=<token>
#        curl -sfL https://get.k3s.io | sh -
```

---

### v1.3 — k3s Multi-Node (2026-04-08)

- Auto-detect server/agent role (`K3S_ROLE=auto|server|agent`)
- Tailscale IP used as `--node-external-ip` for cross-node networking
- Join token saved to `/var/lib/k3s/join-token-<hostname>.txt`
- GPU labels applied automatically to all nodes

---

### v1.2 — CUDA + Docker + k3s (2026-04-04)

- CUDA 12.4 + cuDNN 9 via `system76-cuda-latest` (Pop!_OS) or NVIDIA repo
- Docker CE + NVIDIA Container Toolkit (`nvidia-ctk`)
- GPU passthrough test in Docker (`nvidia/cuda:12.4.0-base`)
- k3s with `--node-label gpu=nvidia`
- NVIDIA Device Plugin `v0.14.5`
- AI Stack: PyTorch 2.2 + Transformers + Gradio + LangChain
- Monitoring: nvtop, DCGM, prometheus-node-exporter

---

### v1.1 — Full Stack (2026-04-02)

- Zsh + Oh My Zsh + autosuggestions + syntax-highlighting
- Security: UFW, fail2ban, unattended-upgrades, sysctl hardening
- KDE Plasma customization
- Tailscale VPN with authkey support
- Git-aware and idempotent per-stage

---

### v1.0 — Initial (2026-03-28)

- Pop!_OS 24.04 NVIDIA ISO → fully configured workstation
- Stages 1-9: base system, GPU, dev tools

---

## Stage Map

| # | Component |
|---|-----------|
| 1 | Preflight checks |
| 2 | System update |
| 3 | NVIDIA Driver |
| 4 | CUDA 12.4 + cuDNN |
| 5 | Docker + NVIDIA Container Toolkit |
| 6 | k3s + NVIDIA Device Plugin |
| 7 | Dev Toolchain |
| 8 | Zsh + Oh My Zsh |
| 9 | Security (UFW, fail2ban, unattended-upgrades) |
| 10 | AI Stack (PyTorch, Transformers, Gradio) |
| 11 | GPU Monitoring |
| 12 | KDE Plasma |
| 13 | Tailscale VPN |
| 14 | k3s Multi-Node |
| 15 | Longhorn Storage |
| 16 | Rook Ceph (Block + FS + Object) |
| 17 | MinIO S3 Object Store |

## Planned

| Stage | Component | Status |
|-------|-----------|--------|
| 17 | MinIO (S3 backup target) | ✅ done (v1.6) |
| 18 | Neovim + LazyVim | pending |
