#!/bin/bash
#===============================================================================
# Stage 19 — System Monitoring (Prometheus + Grafana + Node Exporter)
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_monitoring() {
    step "SYSTEM MONITORING" "19"

    if [[ "${ENABLE_MONITORING:-0}" != "1" ]]; then
        ok "Monitoring skipped"
        return 0
    fi

    log "Deploying monitoring stack via Docker Compose..."
    local mon_dir="${HOME}/.monitoring"
    mkdir -p "$mon_dir"

    cat > "${mon_dir}/docker-compose.yml" << 'EOF'
version: "3.8"
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
EOF

    cat > "${mon_dir}/prometheus.yml" << 'EOF'
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
EOF

    cd "$mon_dir" && docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null || true

    ok "Monitoring: Prometheus http://localhost:9090 | Grafana http://localhost:3000"
    ok "Monitoring stack configured"
}

stage19_monitoring() { stage_monitoring; }