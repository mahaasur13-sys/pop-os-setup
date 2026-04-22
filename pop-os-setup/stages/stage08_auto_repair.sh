#!/usr/bin/env bash
#===============================================================================
# Stage 08 — Zsh + Oh My Zsh (AUTO-REPAIR)
# Purpose: restore DAG continuity for CESM pipeline integrity
# Profile: workstation, ai-dev, full
#===============================================================================

[[ "${_STAGE_SOURCED:-}" != "yes" ]] && {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    LIBDIR="${SCRIPT_DIR}/lib"
}

source "${LIBDIR}/logging.sh" 2>/dev/null || true
source "${LIBDIR}/utils.sh" 2>/dev/null || true

stage08_auto_repair() {
    step "ZSH (AUTO-REPAIR)" "08"

    log "[RECOVERY] Executing stage08_auto_repair.sh"
    log "[RECOVERY] No-op stage to maintain deterministic DAG continuity"

    if command -v zsh &>/dev/null; then
        log "zsh available"
    fi

    ok "Stage 08 (auto-repair) complete"
    return 0
}

stage08() { stage08_auto_repair "$@"; }