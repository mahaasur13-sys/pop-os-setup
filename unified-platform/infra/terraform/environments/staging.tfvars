# =============================================================================
# STAGING ENVIRONMENT — terraform.tfvars
# =============================================================================
# Purpose: Pre-production validation of all infrastructure changes
# Access: Developers + CI/CD (automated apply allowed)
# Approval: None required (CI/CD gate only)
# Rollback: On failed apply, terraform state auto-rollbacks
# =============================================================================

# ─── Environment ─────────────────────────────────────────────────────────────
environment           = "staging"
environment_short     = "stg"

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
slurm_ha_enabled     = false              # Single controller in staging
slurm_controller_nodename = "slurm-ctrl-stg"
slurm_partitions = {
  gpu = { nodes = "rtx3060-*", default = true,  gres = "gpu:rtx3060:1" }
  compute = { nodes = "compute-*", default = false, gres = null }
  edge = { nodes = "rk3576-*", default = false, gres = null }
}

# ─── Ceph ────────────────────────────────────────────────────────────────────
ceph_enabled         = true
ceph_replicas        = 2                 # 2-node in staging (no autoscaling)
ceph_pool_size       = 2
ceph_min_osds        = 2
ceph_public_network   = "10.100.30.0/24"
ceph_cluster_network  = "10.100.20.0/24"

# ─── Ray ─────────────────────────────────────────────────────────────────────
ray_enabled          = true
ray_head_nodename     = "ray-head-stg"
ray_worker_nodenames = ["ray-worker-1-stg"]
ray_head_port        = 6379

# ─── GPU ─────────────────────────────────────────────────────────────────────
gpu_enabled          = true
gpu_nvidia_enabled   = true
gpu_nvidia_device    = "rtx3060"
gpu_nvidia_count     = 1                 # RTX 3060 (1 GPU)

# ─── Compute Nodes ───────────────────────────────────────────────────────────
compute_nodes = {
  rtx3060 = {
    enabled     = true
    nodename    = "rtx3060-stg"
    socket_count = 1
    cores_per_socket = 8
    threads_per_core = 2
    memory_gb   = 32
    is_gpu      = true
  }
  rk3576 = {
    enabled     = true
    nodename    = "rk3576-stg"
    socket_count = 1
    cores_per_socket = 4
    threads_per_core = 1
    memory_gb   = 8
    is_gpu      = false
  }
}

# ─── VPN Mesh ────────────────────────────────────────────────────────────────
vpn_mesh_enabled     = true
vpn_mesh_type        = "amneziawg"       # amneziawg | wireguard
amneziawg_private_key = ""               # Set via TF_VAR_amneziawg_private_key
amneziawg_listen_port = 51871

# ─── Kubernetes (OPTIONAL) ────────────────────────────────────────────────────
k8s_enabled          = false            # NOT enabled in staging (requires explicit toggle)

# ─── Monitoring ──────────────────────────────────────────────────────────────
monitoring_enabled    = true
monitoring_prometheus_port = 9090
monitoring_grafana_port    = 3000
monitoring_loki_port       = 3100

# ─── Self-Healing ─────────────────────────────────────────────────────────────
self_healing_enabled  = true
self_healing_interval  = 60              # seconds
health_check_timeout   = 30

# ─── Rollback ────────────────────────────────────────────────────────────────
# Auto-rollback on failed apply (terraform state backup)
auto_rollback         = true
state_backup_path      = "/var/backups/terraform"

# ─── Tags ────────────────────────────────────────────────────────────────────
tags = {
  Environment = "staging"
  ManagedBy   = "terraform"
  Project     = "home-cluster"
  Stage       = "ci-validate"
}
