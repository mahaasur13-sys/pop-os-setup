#!/bin/bash
#===============================================================================
# Stage 21 — Cron Jobs + Scheduled Tasks (automated maintenance)
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_cron() {
    step "CRON + AUTOMATED MAINTENANCE" "21"

    local cron_dir="${HOME}/.cron"
    mkdir -p "$cron_dir"

    # Cleanup old logs
    cat > "${cron_dir}/cleanup-logs.sh" << 'EOF'
#!/bin/bash
find /var/log -name "*.log" -mtime +30 -delete 2>/dev/null || true
find /tmp -name "*.tmp" -mtime +7 -delete 2>/dev/null || true
docker system prune -af --filter "until=168h" 2>/dev/null || true
EOF
    chmod +x "${cron_dir}/cleanup-logs.sh"

    # Security log rotation
    cat > "${cron_dir}/security-check.sh" << 'EOF'
#!/bin/bash
# Check failed login attempts
failed=$(lastb -F 2>/dev/null | wc -l || echo 0)
if [ "$failed" -gt 50 ]; then
    echo "Warning: $failed failed login attempts"
fi
# Check package updates
apt list --upgradable 2>/dev/null | grep -q "^ Listing" && echo "Updates available"
EOF
    chmod +x "${cron_dir}/security-check.sh"

    # Add to crontab
    (crontab -l 2>/dev/null | grep -v "pop-os-cleanup\|security-check"; \
     echo "0 3 * * * ${cron_dir}/cleanup-logs.sh >> ${cron_dir}/cleanup.log 2>&1"; \
     echo "0 6 * * * ${cron_dir}/security-check.sh >> ${cron_dir}/security.log 2>&1") | crontab -

    ok "Cron jobs installed"
    log "Crons at: $cron_dir"
}

stage21_cron() { stage_cron; }