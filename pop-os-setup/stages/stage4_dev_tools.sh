#!/bin/bash
#===============================================================================
# Stage 4 — Dev Toolchain
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_dev_tools() {
    step "DEV TOOLCHAIN" "4"

    log "Installing development toolchain..."

    apt install -y \
        build-essential \
        git curl wget vim \
        htop net-tools iproute2 iputils-ping \
        traceroute mtr dnsutils telnet ncdu tree \
        unzip zip 7zip-extra \
        jq yq \
        btop glances atop sysstat iotop \
        lsof strace ltrace \
        netcat-openbsd openssl \
        ca-certificates gnupg \
        software-properties-common apt-transport-https \
        zlib1g-dev libffi-dev libssl-dev \
        python3 python3-pip python3-venv python3-dev

    ok "Dev toolchain installed"
}