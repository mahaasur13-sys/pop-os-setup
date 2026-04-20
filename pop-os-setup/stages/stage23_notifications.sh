#!/bin/bash
#===============================================================================
# Stage 23 — System Notifications & Health Monitoring
#===============================================================================
# Профиль: workstation, ai-dev, full
# Настраивает: systemd user timers для уведомлений (GPU temp, updates, disk)
# Работает на уровне пользователя (не root)
# Использует: ensure_dir, append_once, get_target_user, get_user_home,
#             has_nvidia, command_exists, backup_file из lib/utils.sh
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

_STAGE_SOURCED=yes

# ----------------------------------------------------------------------------
# Внутренняя функция: активация user systemd timer с fallback
# ----------------------------------------------------------------------------
_enable_user_timer() {
    local timer="$1"
    local user="$2"

    # Для systemctl --user нужен XDG_RUNTIME_DIR
    local runtime_dir="/run/user/$(id -u "$user")"

    if [[ ! -d "$runtime_dir" ]]; then
        warn "Runtime dir not found for ${user} — creating"
        mkdir -p "$runtime_dir"
        chown "$user:$user" "$runtime_dir"
        chmod 700 "$runtime_dir"
    fi

    # Проверяем что пользователь залогинен
    if ! who | grep -q "^$user "; then
        warn "User ${user} not logged in — timer will activate on next login"
    fi

    # daemon-reload от имени пользователя
    su - "$user" -c "XDG_RUNTIME_DIR=$runtime_dir systemctl --user daemon-reload" 2>/dev/null || {
        warn "Could not reload systemd for ${user} — timers will activate on login"
        return 1
    }

    # enable + start
    su - "$user" -c "XDG_RUNTIME_DIR=$runtime_dir systemctl --user enable --now '$timer'" 2>/dev/null && \
        ok "Timer enabled: $timer" || \
        warn "Timer '$timer' will start on next user login"
    return 0
}

# ----------------------------------------------------------------------------
# Основная stage-функция
# ----------------------------------------------------------------------------
stage_notifications() {
    step "SYSTEM NOTIFICATIONS & HEALTH MONITORING" "23"

    # Проверка флага из профиля
    if [[ "${ENABLE_NOTIFICATIONS:-1}" != "1" ]]; then
        ok "Notifications setup skipped (ENABLE_NOTIFICATIONS=0)"
        return 0
    fi

    # Проверяем наличие notify-send (required)
    if ! command_exists notify-send; then
        if pkg_installed libnotify-bin; then
            warn "libnotify-bin installed but notify-send not in PATH"
        else
            log "Installing notify-bin for desktop notifications..."
            apt-get install -y libnotify-bin 2>/dev/null || \
                warn "Could not install libnotify-bin — notifications may not work"
        fi
    fi

    local target_user
    target_user="$(get_target_user)"

    if [[ -z "$target_user" || "$target_user" == "root" ]]; then
        warn "Could not determine target non-root user. Skipping."
        return 0
    fi

    local home
    home="$(get_user_home "$target_user")"

    if [[ -z "$home" || "$home" == "/" ]]; then
        err "Invalid home directory for user: ${target_user}"
        return 1
    fi

    log "Setting up user-level notifications for ${target_user}..."

    # Создаём директорию для пользовательских systemd unit'ов
    local systemd_user_dir="${home}/.config/systemd/user"
    ensure_dir "$systemd_user_dir"
    chmod 755 "$systemd_user_dir"

    # ─── 1. GPU Temperature Monitor (если есть NVIDIA) ───────────────────────
    if has_nvidia; then
        log "NVIDIA GPU detected — setting up temperature monitor..."

        cat > "${systemd_user_dir}/gpu-temp-monitor.service" << 'EOF'
[Unit]
Description=GPU Temperature Monitor (pop-os-setup)
After=graphical-session.target

[Service]
Type=oneshot
Environment=DISPLAY=:0
ExecStart=/bin/bash -c 'TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null); if [ -n "$TEMP" ] && [ "$TEMP" -ge 80 ]; then notify-send "GPU Warning" "Temperature: ${TEMP}°C — consider reducing load" --icon=dialog-warning; fi'
EOF

        cat > "${systemd_user_dir}/gpu-temp-monitor.timer" << 'EOF'
[Unit]
Description=GPU Temperature Check (pop-os-setup)
After=graphical-session.target

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

        ok "GPU temperature monitor created (threshold: 80°C)"
        _enable_user_timer "gpu-temp-monitor.timer" "$target_user"
    else
        ok "No NVIDIA GPU — skipping GPU monitor"
    fi

    # ─── 2. Update Notification Timer ─────────────────────────────────────────
    log "Creating update check notification timer..."

    cat > "${systemd_user_dir}/update-check.service" << 'EOF'
[Unit]
Description=Check for System Updates (pop-os-setup)
After=network-online.target

[Service]
Type=oneshot
Environment=DISPLAY=:0
ExecStart=/bin/bash -c 'apt-get update -qq 2>/dev/null; UPDATES=$(apt-get upgrade -s -qq 2>/dev/null | grep -c "^[0-9]* upgraded" || echo "0"); if [ "$UPDATES" -gt 0 ]; then notify-send "System Updates" "$UPDATES updates available" --icon=software-update-available; fi'
EOF

    cat > "${systemd_user_dir}/update-check.timer" << 'EOF'
[Unit]
Description=Check for Updates Daily (pop-os-setup)
After=timers.target

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
EOF

    ok "Update check timer created"
    _enable_user_timer "update-check.timer" "$target_user"

    # ─── 3. Disk Space Warning Timer ──────────────────────────────────────────
    log "Creating disk space warning timer..."

    cat > "${systemd_user_dir}/disk-space-check.service" << 'EOF'
[Unit]
Description=Disk Space Check (pop-os-setup)
After=network-online.target

[Service]
Type=oneshot
Environment=DISPLAY=:0
ExecStart=/bin/bash -c 'USED=$(df -h / | awk "NR==2 {print \$5}" | tr -d "%"); if [ "$USED" -ge 90 ]; then notify-send "Disk Warning" "Usage at ${USED}% — consider cleaning up" --icon=dialog-warning; elif [ "$USED" -ge 80 ]; then notify-send "Disk Notice" "Usage at ${USED}% — plan cleanup soon" --icon=drive-harddisk; fi'
EOF

    cat > "${systemd_user_dir}/disk-space-check.timer" << 'EOF'
[Unit]
Description=Check Disk Space Weekly (pop-os-setup)
After=timers.target

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
EOF

    ok "Disk space check timer created (90% warning, 80% notice)"
    _enable_user_timer "disk-space-check.timer" "$target_user"

    # ─── Финальный отчёт ─────────────────────────────────────────────────────
    log_sep
    ok "User notification timers configured for ${target_user}"
    info "Timers active:"
    log "   • update-check.timer       — daily (randomized +30min)"
    log "   • disk-space-check.timer   — weekly (randomized +1h)"

    if has_nvidia; then
        log "   • gpu-temp-monitor.timer — every 5 min (80°C threshold)"
    fi

    info "Manage timers with:"
    log "   su - ${target_user} -c 'systemctl --user list-timers'"
    log "   su - ${target_user} -c 'systemctl --user status gpu-temp-monitor.timer'"
    log "   su - ${target_user} -c 'systemctl --user stop <timer>'  → pause"
    log "   su - ${target_user} -c 'systemctl --user disable <timer>' → disable"

    info "Notifications require user session (logged in with GUI)"
    return 0
}

# Для совместимости
stage23_notifications() {
    stage_notifications "$@"
}