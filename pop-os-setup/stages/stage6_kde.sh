#!/bin/bash
#===============================================================================
# Stage 6 — KDE Plasma Desktop
#===============================================================================

source "${LIBDIR}/logging.sh"
source "${LIBDIR}/utils.sh"

stage_kde() {
    step "KDE PLASMA DESKTOP" "6"

    if dpkg -l plasma-desktop &>/dev/null; then
        ok "KDE Plasma already installed"
        return 0
    fi

    log "Installing KDE Plasma Desktop..."
    apt install -y kde-plasma-desktop 2>&1 | tail -5

    ok "KDE Plasma installed"
    log "Switch to KDE: logout → select 'Plasma (X11)' at login screen"
}

# stub for back-compat (stage 5 in monolith was KDE)
stage5_kde() { stage_kde; }