#!/usr/bin/env bash
#===============================================
# pop-os-setup.sh v9.0 — Production Bootstrap
#===============================================

set -euo pipefail

BOOTSTRAP_START=$(date +%s)
readonly VERSION="9.0.0"

_resolve_root() {
    local src="${BASH_SOURCE[0]}"
    if [[ -L "$src" ]]; then
        cd "$(dirname "$(readlink -f "$src")")/.." && pwd -P
    else
        cd "$(dirname "$src")/.." && pwd -P
    fi
}

export SCRIPT_ROOT="${SCRIPT_ROOT:-$(_resolve_root)}"
export LIBDIR="${SCRIPT_ROOT}/lib"
export STAGEDIR="${SCRIPT_ROOT}/stages"
export ENGINEDIR="${SCRIPT_ROOT}/engine"
export STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/pop-os-setup/state"

mkdir -p "$STATE_DIR" /tmp/pop-os-setup 2>/dev/null || true

export LOGFILE="/tmp/pop-os-setup/pop-os-setup-$(date +%Y-%m-%d_%H-%M-%S).log"
mkdir -p "$(dirname "$LOGFILE")"
exec > >(tee -a "$LOGFILE") 2>&1

usage() {
    cat << 'EOF'
pop-os-setup v9.0.0

Usage: sudo ./pop-os-setup.sh [OPTIONS]

Options:
  --dry-run        Preview only
  --resume         Resume failed stages
  --list           List stages
  --validate       Check all syntax
  --force          Re-run completed
  --skip STAGE     Skip stage
  --only STAGE     Run single stage
  -h, --help       Help
EOF
}

log()   { echo "[$(date +%H:%M:%S)] [INFO]  $*"; }
ok()    { echo "[$(date +%H:%M:%S)] [OK]    $*"; }
warn()  { echo "[$(date +%H:%M:%S)] [WARN]  $*" >&2; }
err()   { echo "[$(date +%H:%M:%S)] [ERR]   $*" >&2; }
step()  { echo ""; echo "=== $1 | Stage $2 ==="; }

[[ "${_STAGE_SOURCED:-}" == "yes" ]] && return 0 || export _STAGE_SOURCED=yes

load_profile() {
    local profile="${PROFILE:-workstation}"
    local pf="${SCRIPT_ROOT}/profiles/${profile}.sh"
    if [[ -f "$pf" ]]; then
        log "Profile: ${profile}"
        source "$pf"
    else
        warn "Profile not found: ${profile}"
    fi
}

load_libs() {
    local ok=0
    for lib in logging.sh utils.sh; do
        local lp="${LIBDIR}/${lib}"
        if [[ -f "$lp" ]]; then
            source "$lp"
        else
            err "Missing: ${lp}"; ok=1
        fi
    done
    return $ok
}

validate_all() {
    log "Validating stages..."
    local errors=0
    for f in "${STAGEDIR}"/stage*.sh; do
        [[ -f "$f" ]] || continue
        if ! bash -n "$f" 2>/dev/null; then
            err "SYNTAX FAIL: $f"
            errors=$((errors + 1))
        fi
    done
    if [[ $errors -eq 0 ]]; then
        ok "All stages syntax-valid"
        return 0
    else
        err "${errors} stage(s) have errors"
        return 1
    fi
}

run_stage() {
    local num="$1"
    local padded
    padded=$(printf '%02d' "$num" 2>/dev/null)
    local stage_file
    stage_file=$(ls "${STAGEDIR}"/stage"${padded}"_*.sh 2>/dev/null | head -1)

    if [[ -z "$stage_file" || ! -f "$stage_file" ]]; then
        err "Stage ${num} not found"
        return 1
    fi

    local stage_name
    stage_name=$(basename "$stage_file" .sh | sed 's/stage[0-9]*_//')

    if [[ -f "${STATE_DIR}/${stage_name}.done" ]] && [[ "${FORCE:-0}" != "1" ]]; then
        ok "Stage ${num} (${stage_name}): done — skipping"
        return 0
    fi

    step "$stage_name" "${num}"

    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        ok "Stage ${num} (${stage_name}): [DRY-RUN]"
        return 0
    fi

    local start=$SECONDS
    if bash "$stage_file"; then
        touch "${STATE_DIR}/${stage_name}.done"
        ok "Stage ${num} (${stage_name}): done (${SECONDS}s)"
        return 0
    else
        touch "${STATE_DIR}/${stage_name}.failed"
        err "Stage ${num} (${stage_name}): FAILED"
        return 1
    fi
}

run_pipeline() {
    local failed=0
    local nums=()
    for f in "${STAGEDIR}"/stage*.sh; do
        [[ -f "$f" ]] || continue
        local n
        n=$(basename "$f" .sh | sed 's/stage//' | sed 's/_.*//' | grep -E '^[0-9]+$' | head -1)
        [[ -n "$n" ]] && nums+=("$n")
    done
    nums=($(printf '%s\n' "${nums[@]}" | sort -n | uniq))

    for num in "${nums[@]}"; do
        if ! run_stage "$num"; then
            if [[ "${CONTINUE_ON_ERROR:-0}" == "1" ]]; then
                warn "Continuing despite failure: stage ${num}"; failed=$((failed + 1))
            else
                err "Pipeline aborted at stage ${num}"; err "Resume: sudo ./pop-os-setup.sh --resume"; return 1
            fi
        fi
    done

    if [[ $failed -gt 0 ]]; then
        ok "Pipeline done with ${failed} failure(s)"
    else
        ok "Pipeline completed successfully"
    fi
}

resume_pipeline() {
    log "Resume mode"
    local failed_stages=()
    for f in "${STATE_DIR}"/*.failed; do
        [[ -f "$f" ]] || continue
        failed_stages+=("$(basename "$f" .failed)")
    done
    if [[ ${#failed_stages[@]} -eq 0 ]]; then
        ok "No failed stages"; return 0
    fi
    log "Found ${#failed_stages[@]} failed stage(s)"
    export FORCE=1
    for name in "${failed_stages[@]}"; do
        rm -f "${STATE_DIR}/${name}.failed"
        local num
        num=$(echo "$name" | sed 's/[^0-9]//g' | head -c2)
        run_stage "$num" || true
    done
}

list_stages() {
    echo ""; echo "=== Stage Registry ==="
    local count=0
    for f in "${STAGEDIR}"/stage*.sh; do
        [[ -f "$f" ]] || continue
        local name
        name=$(basename "$f" .sh | sed 's/stage[0-9]*_//')
        local st="[     ]"
        [[ -f "${STATE_DIR}/${name}.done" ]] && st="[DONE ]"
        [[ -f "${STATE_DIR}/${name}.failed" ]] && st="[FAIL ]"
        count=$((count + 1))
        echo "$st $(basename "$f")"
    done
    echo ""; echo "$count stages"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)  export DRY_RUN=1 ;;
            --resume)   export RESUME=1 ;;
            --list)     export LIST=1 ;;
            --validate) export VALIDATE=1 ;;
            --force)    export FORCE=1 ;;
            --skip)     export SKIP_STAGES="${SKIP_STAGES:-} $2"; shift ;;
            --only)     export ONLY_STAGE="$2"; shift ;;
            --version)  echo "pop-os-setup v${VERSION}"; exit 0 ;;
            -h|--help)  usage; exit 0 ;;
            *)          warn "Unknown: $1"; shift ;;
        esac
        shift
    done
}

main() {
    echo ""
    echo "=============================================="
    echo "  pop-os-setup v${VERSION} — Production Bootstrap"
    echo "=============================================="
    echo ""
    log "Log:   ${LOGFILE}"
    log "State: ${STATE_DIR}"
    log "Root:  ${SCRIPT_ROOT}"
    echo ""

    load_libs
    load_profile

    [[ "${VALIDATE:-0}" == "1" ]] && { validate_all; exit $?; }
    [[ "${LIST:-0}" == "1" ]] && { list_stages; exit 0; }
    [[ "${RESUME:-0}" == "1" ]] && { resume_pipeline; exit $?; }

    run_pipeline

    local elapsed=$(($(date +%s) - BOOTSTRAP_START))
    echo ""
    echo "=============================================="
    ok "pop-os-setup v${VERSION} — ALL DONE (${elapsed}s)"
    echo "=============================================="
}

parse_args "$@"
main
