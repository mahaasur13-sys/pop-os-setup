#!/bin/bash
#===============================================================================
# Utilities Library — pop-os-setup
#===============================================================================
# Shared helper functions for all stages
#===============================================================================

#--- Package helpers -----------------------------------------------------------

install_pkg() {
    local pkg="$1"
    if dpkg -l "$pkg" &>/dev/null; then
        return 0  # already installed
    fi
    apt install -y "$pkg" 2>&1 | tail -3
    return 0
}

pkg_installed() {
    local pkg="$1"
    dpkg -l "$pkg" &>/dev/null
}

#--- Service helpers ----------------------------------------------------------

enable_service() {
    local svc="$1"
    systemctl enable "$svc" 2>/dev/null || true
    systemctl start "$svc" 2>/dev/null || true
}

service_active() {
    local svc="$1"
    systemctl is-active "$svc" &>/dev/null
}

restart_service() {
    local svc="$1"
    systemctl restart "$svc" 2>/dev/null || true
}

#--- User helpers -------------------------------------------------------------

get_current_user() {
    logname 2>/dev/null || echo "$SUDO_USER"
}

get_home_dir() {
    local user="${1:-$(get_current_user)}"
    getent passwd "$user" | cut -d: -f6
}

user_exists() {
    local user="$1"
    id "$user" &>/dev/null
}

add_to_group() {
    local user="$1"
    local group="$2"
    usermod -aG "$group" "$user" 2>/dev/null || true
}

#--- OS detection -------------------------------------------------------------

is_pop_os() {
    grep -q "Pop!_OS" /etc/os-release 2>/dev/null
}

is_debian() {
    grep -q "Debian" /etc/os-release 2>/dev/null
}

is_ubuntu() {
    grep -q "Ubuntu" /etc/os-release 2>/dev/null
}

detect_os() {
    for os in pop_os debian ubuntu; do
        "is_${os}" && echo "$os" && return 0
    done
    echo "unknown"
}

#--- Hardware detection -------------------------------------------------------

has_nvidia() {
    command -v nvidia-smi &>/dev/null
}

nvidia_info() {
    if has_nvidia; then
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null
    fi
}

nvidia_driver_version() {
    nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1
}

has_system76() {
    command -v system76-driver &>/dev/null
}

has_system76_power() {
    command -v system76-power &>/dev/null
}

#--- Network helpers ----------------------------------------------------------

has_internet() {
    curl -sf --max-time 5 https://api.github.com &>/dev/null
}

wait_for_network() {
    local timeout="${1:-30}"
    local waited=0
    while ! has_internet; do
        sleep 2
        waited=$((waited + 2))
        if (( waited >= timeout )); then
            return 1
        fi
    done
    return 0
}

#--- File helpers -------------------------------------------------------------

backup_file() {
    local file="$1"
    if [[ -f "$file" ]]; then
        cp -a "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
    fi
}

ensure_dir() {
    local dir="$1"
    mkdir -p "$dir"
}

#--- Sysctl helpers -----------------------------------------------------------

apply_sysctl() {
    local key="$1"
    local value="$2"
    local conf_file="/etc/sysctl.d/99-custom.conf"
    if ! grep -q "^${key}=" "$conf_file" 2>/dev/null; then
        echo "${key} = ${value}" >> "$conf_file"
    fi
    sysctl -p "$conf_file" 2>/dev/null || true
}

#--- Docker helpers -----------------------------------------------------------

docker_ready() {
    command -v docker &>/dev/null && docker ps &>/dev/null
}

restart_docker() {
    systemctl restart docker 2>/dev/null || true
    sleep 2
}

#--- Python helpers -----------------------------------------------------------

python_installed() {
    command -v python3 &>/dev/null
}

ensure_pip() {
    if ! command -v pip3 &>/dev/null; then
        apt install -y python3-pip
    fi
}

upgrade_pip() {
    pip3 install --upgrade pip 2>&1 | tail -2
}

#--- Git helpers --------------------------------------------------------------

git_clone_or_update() {
    local repo="$1"
    local dest="$2"
    local branch="${3:-main}"

    if [[ -d "$dest/.git" ]]; then
        git -C "$dest" pull origin "$branch" 2>/dev/null || true
    else
        git clone -b "$branch" "$repo" "$dest"
    fi
}

#--- Cleanup helpers ----------------------------------------------------------

cleanup_apt() {
    apt autoremove -y 2>&1 | tail -3
    apt autoclean 2>&1 | tail -2
}