#!/bin/bash
#===============================================================================
# lib/utils.sh — Utility functions for pop-os-setup v3.0.0
#===============================================================================

[[ -n "${_UTILS_SOURCED:-}" ]] && return 0 || _UTILS_SOURCED=1

# ─── OS DETECTION ─────────────────────────────────────────────────────────────
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${PRETTY_NAME:-unknown}"
    else
        echo "unknown"
    fi
}

is_pop_os() { grep -qi 'pop_os\|pop!_os' /etc/os-release 2>/dev/null; }
is_debian() { command -v apt &>/dev/null; }
has_system76() { command -v system76-power &>/dev/null; }
has_system76_power() { command -v system76-power &>/dev/null; }

# ─── NVIDIA ───────────────────────────────────────────────────────────────────
has_nvidia() {
    command -v nvidia-smi &>/dev/null && nvidia-smi -L &>/dev/null 2>&1
}

nvidia_info() {
    if has_nvidia; then
        nvidia-smi --query-gpu=name,driver_version,memory.total \
            --format=csv,noheader 2>/dev/null | head -1
    else
        echo "No NVIDIA GPU"
    fi
}

# ─── USER HELPERS ─────────────────────────────────────────────────────────────
# get_target_user — priority: SUDO_USER → $USER → first uid>=1000 user
get_target_user() {
    local u=""
    u="${SUDO_USER:-}"
    [[ -z "$u" ]] && u="${SUDO_USER:-${USER:-}}"
    [[ -z "$u" ]] && u=$(getent passwd 2>/dev/null | awk -F: '$3 >= 1000 {print $1; exit}')
    [[ -z "$u" ]] && u="root"
    echo "$u"
}

# get_user_home <username>
get_user_home() {
    local u="${1:-}"
    [[ -z "$u" ]] && u=$(get_target_user)
    getent passwd "$u" 2>/dev/null | cut -d: -f6 || echo "$HOME"
}

get_current_user() { echo "${SUDO_USER:-$(whoami)}"; }
get_home_dir() { get_user_home "$1"; }

# ─── COMMAND EXISTENCE ────────────────────────────────────────────────────────
command_exists() { command -v "$1" &>/dev/null 2>&1; }

# require_command <cmd> — exit 1 if command not found
require_command() {
    if ! command_exists "$1"; then
        err "Required command not found: $1"
        return 1
    fi
}

# ─── NETWORK ──────────────────────────────────────────────────────────────────
wait_for_network() {
    local timeout="${1:-10}"
    local i=0
    while (( i < timeout )); do
        if curl -sf --max-time 2 http://example.com &>/dev/null; then
            return 0
        fi
        sleep 1
        ((i++)) || true
    done
    return 1
}

is_network_available() { wait_for_network 5; }

# ─── PACKAGE MANAGEMENT ───────────────────────────────────────────────────────
pkg_installed() {
    dpkg -l "$1" 2>/dev/null | grep -q "^ii"
}

# pkg_available <package> — check if package exists in repos
pkg_available() {
    apt-cache show "$1" &>/dev/null
}

# ensure_pkg <package> — install only if not already installed
ensure_pkg() {
    if pkg_installed "$1"; then
        return 2  # already installed
    fi
    if pkg_available "$1"; then
        apt install -y "$1" 2>/dev/null
        return $?
    fi
    return 1
}

# ─── FILE OPERATIONS ──────────────────────────────────────────────────────────
ensure_dir() { mkdir -p "$1" 2>/dev/null || true; }

# backup_file <file> — create timestamped backup, return 0 if backed up
backup_file() {
    if [[ -f "$1" ]]; then
        local backup="${1}.backup-$(date +%Y%m%d%H%M%S)"
        cp -a "$1" "$backup"
        log "Backed up: $1 -> $backup"
        return 0
    fi
    return 1
}

# append_once <file> <line> — append line only if it doesn't already exist
append_once() {
    local file="$1"
    local line="$2"
    if [[ -f "$file" ]] && grep -Fxq "$line" "$file" 2>/dev/null; then
        return 2  # already present
    fi
    echo "$line" >> "$file"
    return 0
}

# is_file_modified <file> <expected_content> — check if file has expected content
is_file_modified() {
    local file="$1"
    shift
    local expected="$*"
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    local actual
    actual=$(cat "$file" 2>/dev/null)
    [[ "$actual" == "$expected" ]]
}

# ─── SERVICES ────────────────────────────────────────────────────────────────
enable_service() {
    local svc="$1"
    if command -v systemctl &>/dev/null; then
        systemctl enable "$svc" 2>/dev/null || true
        systemctl start "$svc" 2>/dev/null || true
    fi
}

restart_service() {
    local svc="$1"
    if command -v systemctl &>/dev/null; then
        systemctl restart "$svc" 2>/dev/null || true
    elif command -v service &>/dev/null; then
        service "$svc" restart 2>/dev/null || true
    fi
}

is_service_active() {
    local svc="$1"
    if command -v systemctl &>/dev/null; then
        systemctl is-active "$svc" &>/dev/null 2>&1
    else
        return 1
    fi
}

# ─── SYSCTL ───────────────────────────────────────────────────────────────────
apply_sysctl() {
    local key="$1" val="$2"
    local conf="/etc/sysctl.d/99-pop-os-setup.conf"
    ensure_dir "$(dirname "$conf")"
    if ! grep -q "^${key}=" "$conf" 2>/dev/null; then
        echo "$key = $val" >> "$conf"
    fi
    sysctl -w "$key=$val" 2>/dev/null || true
}

# ─── DOCKER ───────────────────────────────────────────────────────────────────
is_docker_running() {
    command_exists docker && docker ps &>/dev/null 2>&1
}

ensure_docker() {
    if ! is_docker_running; then
        log "Starting Docker daemon..."
        if command -v systemctl &>/dev/null; then
            systemctl start docker 2>/dev/null || true
        fi
        sleep 2
    fi
}

# ─── MISC ─────────────────────────────────────────────────────────────────────
get_ip_address() {
    ip route get 1 2>/dev/null | awk '{print $(NF); exit}' || \
    hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown"
}

is_wsl() { grep -qi 'microsoft\|wsl' /proc/version 2>/dev/null; }

is_root() { [[ $EUID -eq 0 ]]; }

# is_user_in_group <user> <group>
is_user_in_group() {
    local user="$1" group="$2"
    groups "$user" 2>/dev/null | grep -qw "$group"
}

require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "This script must be run as root (use sudo)"
        return 1
    fi
    return 0
}

# require_env <varname> — exit 1 if env var not set
require_env() {
    if [[ -z "${!1}" ]]; then
        err "Required environment variable not set: $1"
        return 1
    fi
    return 0
}

get_distro_codename() {
    . /etc/os-release 2>/dev/null
    echo "${VERSION_CODENAME:-unknown}"
}

get_architecture() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64)    echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        armv7l)    echo "armhf" ;;
        *)         echo "$arch" ;;
    esac
}