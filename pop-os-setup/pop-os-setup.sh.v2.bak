#!/bin/bash
#===============================================================================
# Pop!_OS 24.04 NVIDIA — AI/Dev Workstation Auto-Setup (Modular)
#===============================================================================
# Role    : SRE/DevOps Autonomous Deployment Agent
# Target  : Pop!_OS 24.04 LTS NVIDIA Edition (USB Boot → Production Ready)
# Version : 2.0.0 (modular)
# Safety  : Idempotent, verbose logging, profile-driven
#===============================================================================

set -euo pipefail

#--- Script location -----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="${SCRIPT_DIR}/lib"
STAGEDIR="${SCRIPT_DIR}/stages"
# shellcheck disable=SC2034
PROFILEDIR="${SCRIPT_DIR}/profiles"

#--- Config -------------------------------------------------------------------
export LOGFILE="${LOGFILE:-/var/log/popos-setup-$(date +%Y%m%d-%H%M%S).log}"
export SCRIPT_VERSION="2.0.0"
export CURRENT_USER="${CURRENT_USER:-$(logname 2>/dev/null || echo "$SUDO_USER")}"
export HOMEDIR="${HOMEDIR:-$(getent passwd "$CURRENT_USER" | cut -d: -f6)}"

#--- Load libraries -----------------------------------------------------------
# shellcheck source=lib/logging.sh
source "${LIBDIR}/logging.sh"
# shellcheck source=lib/utils.sh
source "${LIBDIR}/utils.sh"
# shellcheck source=lib/profiles.sh
source "${LIBDIR}/profiles.sh"

#--- Argument parsing ---------------------------------------------------------
usage() {
    cat <<EOF
Pop!_OS Setup v$SCRIPT_VERSION — AI/Dev Workstation Auto-Setup

USAGE: $0 [OPTIONS] [PROFILE]

PROFILES:
  workstation  AI/Dev single-machine (default)
  cluster      home-cluster compute node (K8s + Slurm + Ray)
  ai-dev       AI researcher (CUDA + Jupyter + PyTorch)
  full         all components

OPTIONS:
  -p, --profile NAME    Set profile (workstation|cluster|ai-dev|full)
  -s, --stage N          Start from stage N (1-13)
  -l, --list            List all profiles and exit
  -h, --help            Show this help

EXAMPLES:
  sudo $0                        # Interactive workstation setup
  sudo $0 ai-dev                 # AI researcher profile
  sudo $0 -s 5 workstation       # Start from stage 5, workstation profile
  sudo $0 --list                 # Show all profiles

EOF
}

PROFILE="${1:-workstation}"
START_STAGE=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        -s|--stage)   START_STAGE="$2"; shift 2 ;;
        -l|--list)    list_profiles; exit 0 ;;
        -h|--help)    usage; exit 0 ;;
        -*)           err "Unknown option: $1"; usage; exit 1 ;;
        *)            PROFILE="$1"; shift ;;
    esac
done

#===============================================================================
# Pre-flight (always runs first)
#===============================================================================
log "══════════════════════════════════════════════════════════"
log "  Pop!_OS Setup v$SCRIPT_VERSION — Modular"
log "  Profile: $PROFILE | Start stage: $START_STAGE"
log "  User: $CURRENT_USER | Home: $HOMEDIR"
log "  Log: $LOGFILE"
log "══════════════════════════════════════════════════════════"

exec &>> >(tee -a "$LOGFILE")

#===============================================================================
# Apply profile
#===============================================================================
apply_profile "$PROFILE"

#===============================================================================
# Stage runner
#===============================================================================
run_stage() {
    local num="$1"
    local name="$2"

    if (( num < START_STAGE )); then
        log "Skipping stage $num ($name) — before start point"
        return 0
    fi

    local stage_file="${STAGEDIR}/stage${num}_${name}.sh"

    if [[ ! -f "$stage_file" ]]; then
        # Try alternate naming
        stage_file="${STAGEDIR}/stage${num}_${name}.sh"
        if [[ ! -f "$stage_file" ]]; then
            warn "Stage file not found: $stage_file"
            return 0
        fi
    fi

    log "─── Running stage $num: $name ───"
    # shellcheck source=stages/stageN_name.sh
    source "$stage_file"
    "stage_${name}" || {
        err "Stage $num ($name) failed"
        return 1
    }
    ok "Stage $num ($name) complete"
}

#===============================================================================
# Stage definitions
#===============================================================================
STAGES=(
    "1:preflight"
    "2:update"
    "3:nvidia"
    "4:dev_tools"
    "5:zsh"
    "6:kde"
    "7:docker"
    "8:python_ai"
    "9:cuda"
    "10:hardening"
    "11:ssh"
    "12:optimization"
    "13:tailscale"
)

#===============================================================================
# Run stages
#===============================================================================
for entry in "${STAGES[@]}"; do
    IFS=':' read -r num name <<< "$entry"
    run_stage "$num" "$name" || {
        err "Setup failed at stage $num"
        exit 1
    }
done

#===============================================================================
# Final validation
#===============================================================================
step "FINAL VALIDATION" "✓"
log "=== System ==="
uname -r; uptime -p 2>/dev/null || uptime

log "=== Disk ==="
lsblk --bytes | grep -E "NAME|disk|sda|sdb|nvme" | head -8

if has_nvidia; then
    log "=== NVIDIA ==="
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv 2>/dev/null || nvidia-smi | head -4
fi

if command -v docker &>/dev/null; then
    log "=== Docker ==="
    docker ps &>/dev/null && ok "Docker: RUNNING" || warn "Docker: NOT running"
fi

log "=== Zsh ==="
zsh --version 2>/dev/null || warn "Zsh not found"

log "=== Python ==="
python3 --version

log "=== Firewall ==="
ufw status | head -4

log "=== Log ==="
ls -lh "$LOGFILE"

step "SETUP COMPLETE" "✓"

cat <<'EOF'

╔══════════════════════════════════════════════════════════╗
║         Pop!_OS Setup Complete — Reboot Required         ║
╚══════════════════════════════════════════════════════════╝

NEXT STEPS:
  1. sudo reboot
  2. At login: select 'Plasma (X11)' session for KDE
  3. Verify: neofetch && nvidia-smi

Log: /var/log/popos-setup-*.log
Profile: %PROFILE%
EOF

log "Setup complete — reboot recommended"
