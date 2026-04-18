cluster_name = "home-cluster"

nodes = {
  rtx-node = {
    role     = "gpu-head"
    ip       = "10.20.20.10"
    vlans    = ["10", "20", "30"]
    hardware = "nvidia-rtx3060"
  }
  rk3576-edge = {
    role     = "edge-worker"
    ip       = "10.20.20.20"
    vlans    = ["10", "20", "30"]
    hardware = "rockchip-rk3576"
  }
}
