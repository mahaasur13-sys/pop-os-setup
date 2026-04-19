#!/bin/bash
#===============================================================================
# Stage 23 — Desktop Notification System (systemd user services)
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_notifications() {
    step "USER NOTIFICATION SYSTEM" "23"

    log "Setting up systemd user services for background monitoring..."

    # Create systemd user dir
    mkdir -p "${HOME}/.config/systemd/user"

    # GPU temperature monitoring service
    cat > "${HOME}/.config/systemd/user/gpu-temp-monitor.service" << 'EOF'
[Unit]
Description=GPU Temperature Monitor

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c 'while true; do
  temp=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null || echo 0)
  if [ "$temp" -gt 85 ]; then
    notify-send -u critical "GPU Hot!" "Temperature: ${temp}C"
  fi
  sleep 30
done'
StandardOutput=null
StandardError=null

[Install]
WantedBy=default.target
EOF

    # Software update checker
    cat > "${HOME}/.config/systemd/user/update-check.timer" << 'EOF'
[Unit]
Description=Daily software update check

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

    cat > "${HOME}/.config/systemd/user/update-check.service" << 'EOF'
[Unit]
Description=Software Update Checker
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c 'updates=$(apt list --upgradable 2>/dev/null | grep -c "Listing") && \
  [ "$updates" -gt 0 ] && notify-send "Updates Available" "$updates packages can be updated"'
StandardOutput=null
EOF

    # Enable user services
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now update-check.timer 2>/dev/null || true

    ok "Notification system configured"
}

stage23_notifications() { stage_notifications; }