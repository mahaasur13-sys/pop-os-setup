#!/bin/bash
#===============================================================================
# lib/bootstrap.sh — PUBLIC: Mandatory stage bootstrap (v4.0.0)
#===============================================================================
# ЕДИНСТВЕННАЯ точка загрузки зависимостей для всех stages.
# Вызывается из КАЖДОГО stage ДО любой логики.
#
# Правило: bootstrap_stage() возвращает 0 = OK, != 0 = stage пропускается.
#===============================================================================

[[ -n "${_BOOTSTRAP_SOURCED:-}" ]] && return 0

# ─── LOAD PATH RESOLVER ──────────────────────────────────────────────────────
if [[ -f "${LIBDIR:-}/_path.sh" ]]; then
    source "${LIBDIR}/_path.sh"
fi

# ─── CORE LIBS (всегда) ──────────────────────────────────────────────────────
source "${LIBDIR}/logging.sh"   || return 1
source "${LIBDIR}/utils.sh"     || return 1
source "${LIBDIR}/profiles.sh"  || return 1

# ─── BOOTSTRAP STAGE ─────────────────────────────────────────────────────────

bootstrap_stage() {
    local caller="${BASH_SOURCE[1]:-unknown}"

    # Fail-fast: критическая структура
    if [[ ! -d "${LIBDIR:-}" ]]; then
        echo "[bootstrap] FATAL: LIBDIR invalid (${LIBDIR:-not set})" >&2
        return 1
    fi

    if ! declare -f log &>/dev/null; then
        echo "[bootstrap] FATAL: logging.sh not loaded" >&2
        return 1
    fi

    # Устанавливаем strict mode для stage scope
    set -euo pipefail

    _BOOTSTRAP_SOURCED=1
    export _BOOTSTRAP_SOURCED
    return 0
}

# ─── LAZY INSTALLER LOADER ───────────────────────────────────────────────────

load_installer() {
    local module="$1"
    local module_path="${LIBDIR}/installer/${module}.sh"

    if [[ ! -f "$module_path" ]]; then
        err "Installer module not found: ${module}"
        return 1
    fi

    source "$module_path"
    return 0
}

# ─── IDEMPOTENCY HELPERS ─────────────────────────────────────────────────────

is_installed() {
    command -v "$1" &>/dev/null 2>&1
}

skip_if_disabled() {
    local flag="$1"
    local var="ENABLE_${flag}"

    if [[ "${!var:-0}" != "1" ]]; then
        ok "${flag} installation skipped (${var}=0)"
        return 1  # signal to skip
    fi
    return 0  # continue
}

export -f bootstrap_stage load_installer is_installed skip_if_disabled
