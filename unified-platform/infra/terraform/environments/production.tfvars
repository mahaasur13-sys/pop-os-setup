# =============================================================================
# PRODUCTION ENVIRONMENT — terraform.tfvars
# =============================================================================
# Purpose: Live home-cluster production infrastructure
# Access: OPERATORS ONLY (manual apply recommended)
# Approval: MANUAL GITHUB ENVIRONMENT APPROVAL REQUIRED
# Rollback: See .github/workflows/rollback.yml
# =============================================================================

# ─── Environment ─────────────────────────────────────────────────────────────
environment           = "production"
environment_short     = "prod"

# ─── Network ─────────────────────────────────────────────────────────────────
cluster_cidr         = "10.100.0.0/16"
slurm_network_cidr    = "10.100.10.0/24"
ceph_network_cidr     = "10.100.20.0/24"
ray_network_cidr      = "10.100.30.0/24"
vpn_mesh_cidr        = "10.200.0.0/24"

# ─── MikroTik ────────────────────────────────────────────────────────────────
mikrotik_enabled     = true
mikrotik_host        = "192.168.1.1"
mikrotik_user        = "admin"
mikrotik_ssh_port    = 22

# ─── VLANs ───────────────────────────────────────────────────────────────────
vlans = {
  management = { id = 10, subnet = "10.100.10.0/24", description = "Management VLAN" }
  slurm      = { id = 20, subnet = "10.100.20.0/24", description = "Slurm cluster VLAN" }
  ceph       = { id = 30, subnet = "10.100.30.0/24", description = "Ceph storage VLAN" }
  ray        = { id = 40, subnet = "10.100.40.0/24", description = "Ray AI VLAN" }
  guest      = { id = 99, subnet = "10.100.99.0/24", description = "Guest VLAN" }
}

# ─── Slurm ──────────────────────────────────────────────────────────────────
slurm_enabled        = true
slurm_ha_enabled     = true              # 3 controllers in production
slurm_controller_nodename = "slurm-ctrl-prod"
slurm_backup_controller_nodenames = ["slurm-ctrl-backup1", "slurm-ctrl-backup2"]
slurm_partitions = {
  gpu = { nodes = "rtx3060-*", default = true,  gres = "gpu:rtx3060:1" }
  compute = { nodes = "compute-*", default = false, gres = null }
  edge = { nodes = "rk3576-*", default = false, gres = null }
}

# ─── Ceph ────────────────────────────────────────────────────────────────────
ceph_enabled         = true
ceph_replicas        = 3                 # 3x replication in production
ceph_pool_size       = 3
ceph_min_osds        = 3
ceph_public_network   = "10.100.30.0/24"
ceph_cluster_network  = "10.100.20.0/24"
ceph_autoscaling     = true

# ─── Ray ─────────────────────────────────────────────────────────────────────
ray_enabled          = true
ray_head_nodename     = "ray-head-prod"
ray_worker_nodenames = ["ray-worker-1-prod", "ray-worker-2-prod"]
ray_head_port        = 6379

# ─── GPU ─────────────────────────────────────────────────────────────────────
gpu_enabled          = true
gpu_nvidia_enabled   = true
gpu_nvidia_device    = "rtx3060"
gpu_nvidia_count     = 1

# ─── Compute Nodes ───────────────────────────────────────────────────────────
compute_nodes = {
  rtx3060 = {
    enabled     = true
    nodename    = "rtx3060-prod"
    socket_count = 1
    cores_per_socket = 8
    threads_per_core = 2
    memory_gb   = 32
    is_gpu      = true
  }
  rk3576 = {
    enabled     = true
    nodename    = "rk3576-prod"
    socket_count = 1
    cores_per_socket = 4
    threads_per_core = 1
    memory_gb   = 8
    is_gpu      = false
  }
}

# ─── VPN Mesh ────────────────────────────────────────────────────────────────
vpn_mesh_enabled     = true
vpn_mesh_type        = "amneziawg"
amneziawg_private_key = ""
amneziawg_listen_port = 51871

# ─── Kubernetes (OPTIONAL — requires explicit enable) ─────────────────────────
k8s_enabled          = false              # MUST set to true explicitly in production

# ─── Monitoring ──────────────────────────────────────────────────────────────
monitoring_enabled    = true
monitoring_prometheus_port = 9090
monitoring_grafana_port    = 3000
monitoring_loki_port       = 3100

# ─── Self-Healing ─────────────────────────────────────────────────────────────
self_healing_enabled  = true
self_healing_interval  = 30              # More frequent in production
health_check_timeout   = 15

# ─── Rollback ────────────────────────────────────────────────────────────────
auto_rollback         = true
state_backup_path      = "/var/backups/terraform"

# ─── Tags ────────────────────────────────────────────────────────────────────
tags = {
  Environment = "production"
  ManagedBy   = "terraform"
  Project     = "home-cluster"
  Stage       = "live"
  Critical    = "true"
}
