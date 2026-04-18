# ============================================================
# home-cluster-iac — Root Terraform Module
# ============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    local  = { source = "hashicorp/local",   version = "~> 2.4" }
    null   = { source = "hashicorp/null",     version = "~> 3.2" }
    remote = { source = "mitre/remote",       version = "~> 0.2" }
  }
}

provider "local" {}
provider "null"  {}

# ── Network module (MikroTik VLAN + WireGuard) ────────────────
module "network" {
  source = "./modules/network"

  mesh_vpn_subnet  = var.mesh_vpn_subnet
  vlan_segments    = var.vlan_segments
  wireguard_port   = var.wireguard_port

  mikrotik_host     = var.mikrotik_host
  mikrotik_user     = var.mikrotik_user
  mikrotik_password = var.mikrotik_password
}

# ── Compute nodes ──────────────────────────────────────────────
module "home_node" {
  source = "./modules/compute"

  node_name = "home-rtx3060"
  node_ip   = var.home_node_ip
  node_role = "primary"
  gpu_count = 1
  gpu_type  = "nvidia-rtx3060"

  labels = {
    role          = "primary"
    slurm_control = "true"
    ray_head      = "true"
    ceph_mon      = "true"
    ceph_osd      = "true"
  }
}

module "edge_node" {
  source = "./modules/compute"

  node_name = "edge-rk3576"
  node_ip   = var.edge_node_ip
  node_role = "edge"
  gpu_count = 0
  gpu_type  = "none"

  labels = {
    role       = "edge"
    ray_worker = "true"
    ceph_osd   = "true"
  }
}

# ── Slurm HA cluster ──────────────────────────────────────────
module "slurm_cluster" {
  source = "./modules/slurm"

  slurm_cluster_name   = "home-slurm"
  controller_ips       = [var.home_node_ip]  # primary only; backup on VPS later
  compute_ips          = [var.home_node_ip, var.edge_node_ip]
  gpu_partition_enabled = true
}

# ── Ray AI runtime ───────────────────────────────────────────
module "ray_cluster" {
  source = "./modules/ray"

  ray_cluster_name = "home-ray"
  ray_head_ip       = var.home_node_ip
  ray_worker_ips   = [var.edge_node_ip]
  ray_worker_gpu_count = 0
}

# ── Kubernetes layer (optional) ────────────────────────────────
module "kubernetes" {
  source = "./modules/kubernetes"

  k8s_cluster_name   = "home-k8s"
  k8s_api_server_ip  = var.home_node_ip
  k8s_pod_subnet     = "10.244.0.0/16"
  k8s_service_subnet = "10.96.0.0/12"
  k8s_worker_nodes   = [var.edge_node_ip]
  enable_k8s         = false  # enable when Docker host is stable
}

# ── Ceph storage fabric ──────────────────────────────────────
module "ceph_storage" {
  source = "./modules/storage"

  cluster_name         = "home-ceph"
  ceph_subnet          = var.ceph_subnet
  mon_hosts            = [var.home_node_ip, var.edge_node_ip]
  osd_devices         = var.ceph_osd_devices
  replication_factor  = var.ceph_replication_factor

  depends_on = [module.home_node, module.edge_node]
}

# ── VPN mesh overlay ──────────────────────────────────────────
module "vpn_mesh" {
  source = "./modules/vpn_mesh"

  mesh_name   = "home-mesh"
  mesh_subnet = var.mesh_vpn_subnet
  mesh_port   = var.wireguard_port
  peers = [
    { name = "home-rtx3060", ip = var.home_node_ip, endpoint = var.home_endpoint,  pubkey = var.home_wg_pubkey },
    { name = "edge-rk3576",  ip = var.edge_node_ip,  endpoint = var.edge_endpoint,  pubkey = var.edge_wg_pubkey },
  ]

  depends_on = [module.network]
}

# ── Monitoring stack ─────────────────────────────────────────
module "monitoring" {
  source = "./modules/monitoring"

  monitoring_cluster_name = "home-monitoring"
  prometheus_host         = var.home_node_ip
  grafana_host            = var.home_node_ip
  loki_host               = var.home_node_ip

  scrape_configs = [
    { job_name = "node", targets = ["${var.home_node_ip}:9100", "${var.edge_node_ip}:9100"] },
    { job_name = "slurm", targets = ["${var.home_node_ip}:8080"] },
    { job_name = "ray", targets = ["${var.home_node_ip}:8265"] },
  ]
}
