#!/bin/bash
#===============================================================================
# Stage 01 — Pre-flight Checks (v4.0.0)
#===============================================================================
# Профиль: все
# Контракт: provides structure_valid, network_ok, sudo_ok
#
# Исправления v4.0:
#   • LIBDIR проверяется через bootstrap
#   • HOMEDIR заменён на $HOME
#   • Проверки ДО любых side effects
#   • network check через /etc/os-release (без external ping)
#===============================================================================

[[ "${_STAGE_SOURCED:-}" == "yes" ]] && return 0
_STAGE_SOURCED=yes

stage_preflight() {
    step "PRE-FLIGHT CHECKS" "1"

    # ─── 1. STRUCTURE CHECK (bootstrap уже загружен) ───────────────────────────
    local required_files=(
        "${LIBDIR}/logging.sh"
        "${LIBDIR}/utils.sh"
        "${LIBDIR}/profiles.sh"
        "${LIBDIR}/bootstrap.sh"
    )

    for f in "${required_files[@]}"; do
        if [[ ! -f "$f" ]]; then
            err "MISSING: $f"
            return 1
        fi
    done

    # ─── 2. SUDO CHECK ───────────────────────────────────────────────────────
    if [[ $EUID -ne 0 ]]; then
        err "This script must be run as root (sudo $0)"
        return 1
    fi
    ok "Running as root"

    # ─── 3. OS CHECK ─────────────────────────────────────────────────────────
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        log "OS: ${PRETTY_NAME:-unknown}"
        if ! grep -qi 'pop_os\|pop!_os\|ubuntu\|debian' <<< "$PRETTY_NAME"; then
            warn "OS may not be fully supported: $PRETTY_NAME"
        fi
    else
        warn "Cannot detect OS version"
    fi

    # ─── 4. USER DETECTION ───────────────────────────────────────────────────
    local target_user
    target_user="$(get_target_user 2>/dev/null || echo 'root')"
    if [[ -z "$target_user" ]]; then
        err "Cannot determine target user"
        return 1
    fi
    log "Target user: ${target_user} (home: $HOME)"
    ok "User detection OK"

    # ─── 5. DISK SPACE CHECK ─────────────────────────────────────────────────
    local root_available
    root_available=$(df -BG / | awk 'NR==2 {print $4}' | tr -d 'G')
    if (( root_available < 10 )); then
        err "Low disk space: ${root_available}G available (minimum 10G recommended)"
        return 1
    fi
    ok "Disk space OK: ${root_available}G available"

    # ─── 6. NETWORK CHECK (no external ping) ─────────────────────────────────
    if curl -sf --max-time 3 --dns-timeout 3 http://archive.ubuntu.com/ubuntu/dists/ &>/dev/null; then
        ok "Network OK (archive.ubuntu.com reachable)"
    else
        warn "Network may be limited — some packages may fail"
    fi

    # ─── 7. REQUIRED COMMANDS ────────────────────────────────────────────────
    local required_cmds=(curl git jq)
    for cmd in "${required_cmds[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            warn "Missing command: $cmd — will attempt to install"
        fi
    done

    # ─── 8. EXISTING INSTALLATIONS ────────────────────────────────────────────
    local existing=()
    command -v docker  &>/dev/null && existing+=("docker")
    command -v nvim    &>/dev/null && existing+=("neovim")
    command -v zsh     &>/dev/null && existing+=("zsh")
    command -v kubectl &>/dev/null && existing+=("kubectl")

    if [[ ${#existing[@]} -gt 0 ]]; then
        log "Already installed: ${existing[*]}"
    fi

    ok "Pre-flight checks complete"
    return 0
}

stage01_preflight() { stage_preflight "$@"; }
