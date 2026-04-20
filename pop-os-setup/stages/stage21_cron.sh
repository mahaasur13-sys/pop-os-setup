#!/bin/bash
#===============================================================================
# Stage 21 — Cron Jobs & Scheduled Tasks
#===============================================================================
# Профиль: все (workstation, ai-dev, full, cluster)
# Настраивает: очистка логов, проверка обновлений, disk check, backup reminder
# Использует: ensure_dir, append_once, backup_file, get_target_user,
#             command_exists, restart_service из lib/utils.sh
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
# Внутренняя функция: безопасное добавление cron-записи если её ещё нет
# ----------------------------------------------------------------------------
_cron_add_if_missing() {
    local line="$1"
    local crontab="${2:-/etc/crontab}"

    if [[ -f "$crontab" ]] && grep -Fqx -- "$line" 2>/dev/null; then
        return 2
    fi
    echo "$line" >> "$crontab"
    return 0
}

# ----------------------------------------------------------------------------
# Внутренняя функция: создание скрипта проверки диска
# ----------------------------------------------------------------------------
_install_disk_check_script() {
    local script="/usr/local/bin/pop-os-disk-check"
    local marker="# pop-os-setup: disk check script"

    # Не перезаписываем если уже есть наш скрипт
    if [[ -f "$script" ]] && grep -q "$marker" "$script" 2>/dev/null; then
        ok "Disk check script already exists"
        return 2
    fi

    cat > "$script" << 'SCRIPTEOF'
#!/bin/bash
# pop-os-setup: disk check script
set -euo pipefail

THRESHOLD="${THRESHOLD:-85}"
MOUNT_POINT="${MOUNT_POINT:-/}"

USED="$(df -h "$MOUNT_POINT" | awk 'NR==2 {print $5}' | tr -d '%')"
if [[ "$USED" -ge "$THRESHOLD" ]]; then
    echo "WARNING: Disk usage is ${USED}% on ${MOUNT_POINT}" | systemd-cat -t pop-os-disk -p warning
    logger -p user.warning "pop-os-setup: Disk usage high: ${USED}% on ${MOUNT_POINT}"
fi
SCRIPTEOF

    chmod +x "$script"
    ok "Disk check script installed: ${script}"
    return 0
}

# ----------------------------------------------------------------------------
# Основная stage-функция
# ----------------------------------------------------------------------------
stage_cron() {
    step "CRON JOBS & SCHEDULED TASKS" "21"

    # Проверка флага из профиля
    if [[ "${ENABLE_CRON:-1}" != "1" ]]; then
        ok "Cron setup skipped (ENABLE_CRON=0)"
        return 0
    fi

    log "Setting up scheduled maintenance tasks..."

    local marker="# pop-os-setup v3.0.0"
    local cron_file="/etc/crontab"

    if [[ ! -w "$cron_file" ]]; then
        err "Cannot write to ${cron_file} — skipping cron setup"
        return 1
    fi

    # 1. Очистка старых логов (каждый понедельник в 04:00)
    local log_cleanup="0 4 * * 1 root find /var/log -type f -name '*.log' -mtime +30 -delete 2>/dev/null || true"
    if _cron_add_if_missing "$log_cleanup" "$cron_file"; then
        ok "Cron: weekly log cleanup (Mon 04:00)"
    fi

    # 2. Проверка обновлений безопасности (каждый вторник в 05:00)
    # --allow-unauthenticated для fallback, -y для авто-подтверждения
    local sec_update='0 5 * * 2 root apt-get update -qq && apt-get upgrade -y --only-upgrade -qq 2>/dev/null || true'
    if _cron_add_if_missing "$sec_update" "$cron_file"; then
        ok "Cron: weekly security updates (Tue 05:00)"
    fi

    # 3. Скрипт проверки диска
    _install_disk_check_script

    local disk_check="0 8 * * * root /usr/local/bin/pop-os-disk-check"
    if _cron_add_if_missing "$disk_check" "$cron_file"; then
        ok "Cron: daily disk check (08:00)"
    fi

    # 4. Напоминание о бэкапе (раз в 14 дней в 09:00)
    # Записываем в пользовательский crontab целевого пользователя
    local target_user
    target_user="$(get_target_user)"
    local user_crontab=""
    local user_home=""

    if [[ -n "$target_user" && "$target_user" != "root" ]]; then
        user_home="$(get_user_home "$target_user")"
        user_crontab="${user_home}/.crontab"

        # Создаём файл если его нет
        touch "$user_crontab" 2>/dev/null || true
        chmod 600 "$user_crontab" 2>/dev/null || true

        local backup_reminder='0 9 */14 * * echo "[pop-os-setup] Backup reminder: run '\''pop-os-backup'\'' or '\''timeshift-launcher'\''" | systemd-cat -t pop-os-backup-reminder -p info'
        if grep -Fqx -- "$backup_reminder" "$user_crontab" 2>/dev/null; then
            ok "Cron: backup reminder already set for ${target_user}"
        else
            echo "$backup_reminder" >> "$user_crontab"
            # Активируем пользовательский crontab
            crontab -u "$target_user" "$user_crontab" 2>/dev/null && \
                ok "Cron: backup reminder set for ${target_user} (bi-weekly 09:00)" || \
                warn "Could not activate crontab for ${target_user}"
        fi
    else
        warn "Cannot set user crontab — target user not determined"
    fi

    # 5. Перезапускаем cron чтобы применить изменения
    restart_service cron
    if command -v systemctl &>/dev/null; then
        systemctl reload cron 2>/dev/null || true
    fi

    # 6. Финальный вывод
    log_sep
    ok "Cron jobs configured successfully"
    info "Scheduled tasks:"
    log "   • Weekly log cleanup      — Mon 04:00  (find /var/log -mtime +30)"
    log "   • Weekly security check — Tue 05:00  (apt-get upgrade)"
    log "   • Daily disk monitor    — Daily 08:00 (threshold: 85%)"
    log "   • Backup reminder       — Bi-weekly 09:00 (user crontab)"

    info "Useful commands:"
    log "   sudo crontab -l              → view system cron"
    log "   crontab -l                   → view current user cron"
    log "   sudo journalctl -t pop-os-*  → view pop-os-setup cron logs"
    log "   /usr/local/bin/pop-os-disk-check  → run disk check manually"

    return 0
}

# Для совместимости
stage21_cron() {
    stage_cron "$@"
}
