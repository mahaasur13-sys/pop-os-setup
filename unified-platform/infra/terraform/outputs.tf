# ============================================================
# Outputs — home-cluster-iac
# ============================================================

output "mesh_vpn_subnet" {
  description = "WireGuard mesh overlay CIDR"
  value       = var.mesh_vpn_subnet
}

output "node_summary" {
  description = "Cluster node inventory"
  value = {
    home = {
      ip      = var.home_node_ip
      role    = "primary"
      gpu     = "RTX 3060"
      mesh_ip = cidrhost(var.mesh_vpn_subnet, 10)
    }
    edge = {
      ip      = var.edge_node_ip
      role    = "edge"
      gpu     = "none"
      mesh_ip = cidrhost(var.mesh_vpn_subnet, 11)
    }
  }
}

output "vlan_summary" {
  description = "VLAN segments"
  value       = var.vlan_segments
}

output "ceph_info" {
  description = "Ceph cluster endpoints"
  value = {
    mon_host = var.ceph_subnet
    replicas = var.ceph_replication_factor
  }
}

output "slurm_endpoints" {
  description = "Slurm controller endpoints"
  value = {
    control_host = var.slurm_control_host
    cluster_name = var.slurm_cluster_name
  }
}
