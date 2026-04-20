#!/bin/bash
#===============================================================================
# Stage 25 — Backup & Recovery Setup
#===============================================================================
# Профиль: все (workstation, ai-dev, full, cluster)
# Настраивает: Timeshift + rsync-based backup script + scheduled tasks
# Создаёт restore point после установки
# Использует: ensure_dir, append_once, backup_file, get_target_user,
#             get_user_home, command_exists, pkg_installed из lib/utils.sh
#===============================================================================

# Защита от повторного sourcing + поддержка автономного запуска
[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"
source "${LIBDIR}/installer.sh"

_STAGE_SOURCED=yes

stage_backup() {
    step "BACKUP & RECOVERY SETUP" "25"

    # Проверка флага из профиля
    if [[ "${ENABLE_BACKUP:-1}" != "1" ]]; then
        ok "Backup setup skipped (ENABLE_BACKUP=0)"
        return 0
    fi

    local target_user
    target_user="$(get_target_user)"

    if [[ -z "$target_user" || "$target_user" == "root" ]]; then
        err "Cannot determine target non-root user for backup setup"
        return 1
    fi

    local home
    home="$(get_user_home "$target_user")"

    log "Setting up backup and recovery for user: ${target_user}"

    # ─── 1. Timeshift ───────────────────────────────────────────────────────
    local ts_installed=false

    if command_exists timeshift; then
        ok "Timeshift already installed"
        ts_installed=true
    elif pkg_available timeshift; then
        log "Installing Timeshift..."
        if apt-get install -y timeshift 2>/dev/null; then
            ok "Timeshift installed"
            ts_installed=true
        else
            warn "Failed to install Timeshift — continuing with rsync backup only"
        fi
    else
        warn "Timeshift package not available — skipping"
    fi

    # ─── 2. Timeshift Configuration ───────────────────────────────────────
    if $ts_installed; then
        local ts_conf="/etc/timeshift/timeshift.json"
        local ts_etc_dir="/etc/timeshift"

        if [[ ! -f "$ts_conf" ]]; then
            ensure_dir "$ts_etc_dir"

            cat > "$ts_conf" << 'EOF'
{
    "backup_device_uuid": "",
    "parent_device_uuid": "",
    "do_first_run": "true",
    "btrfs_mode": "false",
    "include_btrfs_home": "false",
    "stop_cron_emails": "true",
    "schedule_monthly": "true",
    "schedule_weekly": "true",
    "schedule_daily": "true",
    "schedule_hourly": "false",
    "schedule_boot": "false",
    "count_monthly": "2",
    "count_weekly": "3",
    "count_daily": "5",
    "count_hourly": "0",
    "count_boot": "0"
}
EOF
            ok "Timeshift configured: monthly×2, weekly×3, daily×5"
        else
            ok "Timeshift config already exists — skipping"
        fi

        # Создание первого снапшота
        log "Creating initial Timeshift snapshot..."
        if timeshift --create \
            --comments "Initial snapshot after pop-os-setup v3.0.0" \
            --scripted 2>&1 | tail -3; then
            ok "Initial Timeshift snapshot created"
        else
            warn "Could not create initial snapshot (may need device configured)"
            info "Run: sudo timeshift-launcher or sudo timeshift --create"
        fi
    fi

    # ─── 3. Rsync Backup Script ──────────────────────────────────────────────
    local backup_script="/usr/local/bin/pop-os-backup"
    local backup_dir="/usr/local/bin"

    ensure_dir "$backup_dir"

    if [[ ! -f "$backup_script" ]]; then
        cat > "$backup_script" << 'EOF'
#!/bin/bash
#===============================================================================
# pop-os-backup — Rsync incremental backup script
# Usage: sudo pop-os-backup [target]   # default: /backup/pop-os
#===============================================================================

set -euo pipefail

BACKUP_TARGET="${1:-/backup/pop-os}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_TARGET}/backup_${DATE}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "Starting backup: / -> ${BACKUP_PATH}"

mkdir -p "$BACKUP_TARGET"

if ! rsync -aAXv --delete \
    --exclude="/dev/*" \
    --exclude="/proc/*" \
    --exclude="/sys/*" \
    --exclude="/tmp/*" \
    --exclude="/run/*" \
    --exclude="/mnt/*" \
    --exclude="/media/*" \
    --exclude="/lost+found" \
    --exclude=".cache/*" \
    / "$BACKUP_PATH/"; then
    log "ERROR: Backup failed"
    exit 1
fi

log "Backup completed: ${BACKUP_PATH}"
du -sh "$BACKUP_PATH"
EOF
        chmod +x "$backup_script"
        ok "Backup script created: ${backup_script}"
    else
        ok "Backup script already exists: ${backup_script}"
    fi

    # ─── 4. Scheduled Backup (cron) ────────────────────────────────────────
    local cron_entry="0 3 * * 0 root ${backup_script} /backup/pop-os"
    local cron_marker="# pop-os-setup weekly backup"

    if ! grep -Fq "$cron_marker" /etc/crontab 2>/dev/null; then
        append_once "/etc/crontab" "$cron_marker" || true
        append_once "/etc/crontab" "$cron_entry" || true
        ok "Weekly backup scheduled: Sunday 03:00 → ${backup_script}"
    else
        ok "Weekly backup already in crontab"
    fi

    # ─── 5. User backup alias ──────────────────────────────────────────────
    local bashrc="${home}/.bashrc"
    local alias_line="alias pop-backup='sudo ${backup_script} /backup/pop-os'"

    if [[ -f "$bashrc" ]]; then
        append_once "$bashrc" "# pop-os-setup: manual backup alias" || true
        append_once "$bashrc" "$alias_line" || true
        ok "Backup alias added for ${target_user}: pop-backup"
    fi

    # ─── 6. Summary ────────────────────────────────────────────────────────
    log_sep
    ok "Backup & Recovery setup complete!"

    info "Available tools:"
    log "   timeshift        → System snapshots (GUI: sudo timeshift-launcher)"
    log "   pop-os-backup    → Manual rsync backup (sudo pop-backup)"
    log "   Weekly backup    → Every Sunday at 03:00 (see /etc/crontab)"

    info "Quick commands:"
    log "   sudo timeshift --create --comment 'Before update'"
    log "   sudo timeshift --restore"
    log "   sudo pop-os-backup"
    log "   sudo timeshift-launcher  # GUI"

    return 0
}

# Для совместимости со старым вызовом
stage25_backup() {
    stage_backup "$@"
}
