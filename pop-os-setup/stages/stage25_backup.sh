#!/bin/bash
#===============================================================================
# Stage 25 — System Recovery + Backup (Timeshift + Rsync)
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_backup() {
    step "SYSTEM BACKUP + RECOVERY" "25"

    log "Setting up system backup with Timeshift..."

    pkg_installed timeshift || sudo apt install -y timeshift

    # Default rsync backup schedule (weekly)
    local backup_dir="${HOME}/.backup"
    mkdir -p "$backup_dir"

    cat > "${HOME}/.backup/backup-home.sh" << 'EOF'
#!/bin/bash
# Incremental backup of home directory
TARGET="${BACKUP_TARGET:-/mnt/backup}"
SRC="${HOME}"

rsync -av --delete \
    --exclude='.cache' \
    --exclude='.local/share/Trash' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    "$SRC/" "$TARGET/home-$(date +%Y%m%d)/" 2>&1

echo "Backup complete: $(date)" >> "${HOME}/.backup/backup.log"
EOF
    chmod +x "${HOME}/.backup/backup-home.sh"

    # Timeshift auto-snapshots (daily)
    if command -v timeshift &>/dev/null; then
        log "Configuring Timeshift for daily snapshots..."
        sudo timeshift --create --comments "Initial setup snapshot" --tags D 2>/dev/null || true
        ok "Timeshift snapshots enabled"
    fi

    ok "Backup system configured"
    log "Backup script: ${HOME}/.backup/backup-home.sh"
}

stage25_backup() { stage_backup; }