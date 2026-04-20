#!/bin/bash
# lib/profiles.sh — Profile loader for pop-os-setup v3.0.0

[[ -n "${_PROFILES_SOURCED:-}" ]] && return 0 || _PROFILES_SOURCED=1

load_profile() {
    local name="$1"
    local pfile="${PROFILESDIR}/${name}.sh"

    if [[ ! -f "$pfile" ]]; then
        err "Profile not found: $name"
        err "Available: $(ls "$PROFILESDIR"/*.sh 2>/dev/null | xargs -I{} basename {} .sh | tr '\n' ' ')"
        return 2
    fi

    info "Loading profile: $name"
    # shellcheck disable=SC1090
    source "$pfile"

    local func="apply_profile_${name//-/_}"
    if ! declare -f "$func" &>/dev/null; then
        err "Function '${func}' not found in $pfile"; return 1; fi

    # Unset all ENABLE_ vars
    unset ENABLE_SSH ENABLE_DOCKER ENABLE_CUDA ENABLE_AI \
          ENABLE_HARDEN ENABLE_KDE ENABLE_ZSH ENABLE_TAILSCALE \
          ENABLE_K8S ENABLE_SLURM ENABLE_MONITORING 2>/dev/null

    "$func"; ok "Profile applied: $name"
}

list_profiles() {
    for f in "${PROFILESDIR}"/*.sh; do
        [[ -f "$f" ]] && basename "$f" .sh
    done
}
