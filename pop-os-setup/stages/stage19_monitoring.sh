#!/bin/bash
#===============================================================================
# Stage 19 — Monitoring Stack (Prometheus + Grafana + Node Exporter)
#===============================================================================
# Профиль: full, ai-dev (опционально)
# Генерирует случайные пароли для Grafana
# Использует: generate_random_password() из lib/installer.sh
#===============================================================================

# Защита от повторного sourcing
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

stage_monitoring() {
    step "MONITORING STACK (Prometheus + Grafana)" "19"

    if [[ "${ENABLE_MONITORING:-0}" != "1" ]]; then
        ok "Monitoring stack skipped (ENABLE_MONITORING=0)"
        return 0
    fi

    # Проверка Docker (требуется для Prometheus/Grafana)
    if ! command_exists docker; then
        err "Docker is required for monitoring stack. Run stage 07 first."
        return 1
    fi

    log "Deploying Prometheus + Grafana monitoring stack..."

    # Генерируем сильный пароль для Grafana
    local grafana_password="${GRAFANA_ADMIN_PASSWORD:-$(generate_random_password 20)}"

    # Создаём директорию для хранения пароля
    local config_dir="${HOME}/.config/pop-os-setup"
    mkdir -p "$config_dir"
    local pw_file="${config_dir}/.grafana_password"

    # Docker Compose файл для стека
    local compose_file="/opt/monitoring/docker-compose.yml"
    mkdir -p /opt/monitoring

    cat > "$compose_file" << 'EOF'
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - prometheus_data:/prometheus
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus

volumes:
  prometheus_data:
  grafana_data:
EOF

    # Создаём базовый prometheus.yml
    cat > "/opt/monitoring/prometheus.yml" << 'EOF'
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
EOF

    # Сохраняем пароль Grafana
    echo "$grafana_password" > "$pw_file"
    chmod 600 "$pw_file"

    # Подставляем пароль в compose файл
    sed -i "s/\${GRAFANA_PASSWORD}/$grafana_password/" "$compose_file"

    # Запускаем стек через Docker Compose
    log "Starting monitoring stack with Docker Compose..."
    cd /opt/monitoring || {
        err "Failed to change directory to /opt/monitoring"
        return 1
    }

    docker compose up -d || {
        err "Failed to start monitoring stack"
        return 1
    }

    # Финальная проверка
    sleep 5
    if docker ps | grep -q "grafana"; then
        ok "Monitoring stack deployed successfully!"
        ok "Grafana: http://localhost:3000"
        ok "Username: admin"
        ok "Password saved to: ${pw_file}"
        info "You can view the password with: cat ${pw_file}"
    else
        err "Monitoring stack failed to start"
        return 1
    fi

    # Добавляем node-exporter (опционально, но рекомендуется)
    if ! docker ps | grep -q "node-exporter"; then
        docker run -d \
            --name node-exporter \
            --restart=unless-stopped \
            -p 9100:9100 \
            -v /proc:/host/proc:ro \
            -v /sys:/host/sys:ro \
            -v /:/rootfs:ro \
            prom/node-exporter:latest \
            --path.procfs=/host/proc \
            --path.sysfs=/host/sys \
            --path.rootfs=/rootfs || true
    fi

    return 0
}

# Для совместимости
stage19_monitoring() {
    stage_monitoring "$@"
}
