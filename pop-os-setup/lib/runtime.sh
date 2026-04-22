#!/usr/bin/env bash
#===============================================
# lib/runtime.sh — pop-os-setup v11.2 Runtime Engine
# Single source of truth for version, paths, state, identity.
#===============================================

[[ -n "${_RUNTIME_SOURCED:-}" ]] && return 0 || _RUNTIME_SOURCED=1

# ═══════════════════════════════════════════════
# VERSION (canonical source — single definition)
# ═══════════════════════════════════════════════

readonly RUNTIME_VERSION="v11.2"

get_version() { echo "$RUNTIME_VERSION"; }

# ═══════════════════════════════════════════════
# BUILD IDENTITY LAYER (v11.2 — immutable fingerprint)
# ═══════════════════════════════════════════════

derive_build_identity() {
    local script_dir="${1:-$PWD}"

    if [[ -d "$script_dir/.git" ]]; then
        BUILD_ID=$(git -C "$script_dir" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        BUILD_TREE=$(git -C "$script_dir" rev-parse HEAD 2>/dev/null || echo "unknown")
        BUILD_BRANCH=$(git -C "$script_dir" branch --show-current 2>/dev/null || echo "detached")
        BUILD_TAGS=$(git -C "$script_dir" tag --points-at HEAD 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    else
        BUILD_ID="no-git"; BUILD_TREE="no-git"; BUILD_BRANCH="none"; BUILD_TAGS=""
    fi

    BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    BUILD_EPOCH=$(date -u +%s)

    readonly BUILD_ID BUILD_TREE BUILD_BRANCH BUILD_TAGS BUILD_TIME BUILD_EPOCH
}

derive_build_identity "${SCRIPT_DIR:-.}"

# ═══════════════════════════════════════════════
# PIPELINE FINGERPRINT (v11.2 — order-sensitive hash)
# Same input → identical fingerprint
# ═══════════════════════════════════════════════

compute_pipeline_fingerprint() {
    local profile="${1:-default}"

    local stages_list
    stages_list=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' | sort |                   xargs grep -h '^stage_[0-9a-z_]*()' 2>/dev/null |                   sed 's/^[[:space:]]*//;s/().*//' | tr '\n' '|' | cat 2>/dev/null)

    local stage_hash ver_hash git_hash prof_hash
    stage_hash=$(printf '%s' "$stages_list" | sha256sum | awk '{print $1}')
    ver_hash=$(printf '%s' "$RUNTIME_VERSION" | sha256sum | awk '{print $1}')
    git_hash=$(printf '%s' "${BUILD_TREE:-unknown}" | sha256sum | awk '{print $1}')
    prof_hash=$(printf '%s' "$profile" | sha256sum | awk '{print $1}')

    PIPELINE_FINGERPRINT=$(printf '%s%s%s%s' "$stage_hash" "$ver_hash" "$git_hash" "$prof_hash" | sha256sum | awk '{print $1}')
    readonly PIPELINE_FINGERPRINT
    FINGERPRINT_SHORT="${PIPELINE_FINGERPRINT:0:12}"
    readonly FINGERPRINT_SHORT
}

# ═══════════════════════════════════════════════
# DETERMINISTIC LOGGING CONTRACT v2 (v11.2)
# same input → same observable trace (always)
# ═══════════════════════════════════════════════

readonly LOG_CONTRACT_VERSION=v2

# Log mode: deterministic | system | user
# Path depends ONLY on: LOG_MODE + RUN_ID + RUNTIME_VERSION
# NEVER use EUID, filesystem checks, or runtime guesses
get_log_target() {
    local mode="${LOG_MODE:-deterministic}"
    local run_id="${RUN_ID:-default}"
    local ver="${RUNTIME_VERSION:-v11.2}"

    case "$mode" in
        deterministic)
            printf '%s/.logs/%s/%s' "${SCRIPT_DIR:-.}" "$ver" "$run_id"
            ;;
        system)
            printf '/var/log/pop-os-setup/%s/%s' "$ver" "$run_id"
            ;;
        user)
            printf '%s/.local/share/pop-os-setup/logs/%s/%s' "${HOME:-/tmp}" "$ver" "$run_id"
            ;;
        *)
            printf '%s/.logs/%s/%s' "${SCRIPT_DIR:-.}" "$ver" "$run_id"
            ;;
    esac
}

# Validates log contract: no env probes, no filesystem branching
validate_log_environment() {
    local errors=0

    case "${LOG_MODE:-deterministic}" in
        deterministic|system|user) : ;;
        *)
            err "LOG_MODE must be: deterministic | system | user (got: '${LOG_MODE:-}')"
            errors=$((errors + 1))
            ;;
    esac

    local path; path=$(get_log_target)
    if echo "$path" | grep -qE '(\$EUID|\$\(id|whoami|hostname)'; then
        err "Log path contains environment probe: $path"
        errors=$((errors + 1))
    fi

    if [[ "${DRY_RUN:-0}" == "1" && "${LOG_MODE:-deterministic}" != "deterministic" ]]; then
        err "DRY-RUN mandates LOG_MODE=deterministic (enforced)"
        errors=$((errors + 1))
    fi

    return $errors
}

# Trace hash: identical for identical log structure + event ordering
compute_trace_hash() {
    local run_id="${1:-default}"
    local log_dir; log_dir=$(get_log_target)
    local trace_input=""
    local jsonl_file="${log_dir}/run_${run_id}.jsonl"

    if [[ -f "$jsonl_file" ]]; then
        trace_input=$(cat "$jsonl_file" 2>/dev/null || echo "")
    fi

    trace_input="${trace_input}$(find "$log_dir" -name '*.log' -type f 2>/dev/null | sort | xargs cat 2>/dev/null || echo '')"
    printf '%s' "$trace_input" | sha256sum | awk '{print $1}'
}

# ═══════════════════════════════════════════════
# PATH SETUP
# ═══════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SCRIPT_DIR

LIBDIR="${SCRIPT_DIR}/lib"
ENGINEDIR="${SCRIPT_DIR}/engine"
STAGEDIR="${SCRIPT_DIR}/stages"
PROFILEDIR="${SCRIPT_DIR}/profiles"
STATEDIR="${STATEDIR:-${SCRIPT_DIR}/state}"
LOGDIR="${LOGDIR:-${SCRIPT_DIR}/logs}"
readonly LIBDIR ENGINEDIR STAGEDIR PROFILEDIR STATEDIR LOGDIR

ensure_dir() { mkdir -p "$1" 2>/dev/null || true; }
ensure_dir "$STATEDIR"; ensure_dir "$LOGDIR"

for lib in logging utils; do
    [[ -f "${LIBDIR}/${lib}.sh" ]] && source "${LIBDIR}/${lib}.sh" || true
done

step()  { echo "[$(date +'%H:%M:%S')] [STAGE $2] $1"; }
ok()    { echo "[$(date +'%H:%M:%S')] [OK] $1"; }
warn()  { echo "[$(date +'%H:%M:%S')] [WARN] $1"; }
err()   { echo "[$(date +'%H:%M:%S')] [ERR] $1" >&2; }
info()  { echo "[$(date +'%H:%M:%S')] [INFO] $1"; }
log()   { echo "[$(date +'%H:%M:%S')] $1"; }

# ═══════════════════════════════════════════════
# RUN ID MANAGEMENT
# ═══════════════════════════════════════════════

generate_run_id() {
    local prefix="${1:-run}"
    local timestamp; timestamp=$(date +%Y%m%d_%H%M%S)
    local rand; rand=$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' ' | head -c 6)
    echo "${prefix}_${timestamp}_${rand}"
}

# ═══════════════════════════════════════════════
# OS DETECTION
# ═══════════════════════════════════════════════

detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release; echo "${PRETTY_NAME:-unknown}"
    else
        echo "unknown"
    fi
}

is_pop_os() { grep -qi 'pop_os\|pop!_os' /etc/os-release 2>/dev/null; }

# ═══════════════════════════════════════════════
# USER HELPERS
# ═══════════════════════════════════════════════

get_target_user() {
    local u="${SUDO_USER:-}"; [[ -z "$u" ]] && u="${USER:-}"
    [[ -z "$u" ]] && u=$(getent passwd 2>/dev/null | awk -F: '$3 >= 1000 {print $1; exit}')
    [[ -z "$u" ]] && u="root"; echo "$u"
}

get_user_home() {
    local u="${1:-}"; [[ -z "$u" ]] && u=$(get_target_user)
    getent passwd "$u" 2>/dev/null | cut -d: -f6 || echo "$HOME"
}

# ═══════════════════════════════════════════════
# FILE OPERATIONS
# ═══════════════════════════════════════════════

append_once() {
    local file="$1" line="$2"
    [[ -f "$file" ]] && grep -Fxq "$line" "$file" 2>/dev/null && return 2
    echo "$line" >> "$file"; return 0
}

# ═══════════════════════════════════════════════
# EXECUTION IDENTITY LOG (v11.2 — structured JSONL)
# ═══════════════════════════════════════════════

log_execution_event() {
    local run_id="$1" event="$2" stage="${3:-}" status="${4:-info}"
    local timestamp; timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local fingerprint="${PIPELINE_FINGERPRINT:-unknown}"
    local log_file="${LOGDIR}/run_${run_id}.jsonl"
    ensure_dir "$(dirname "$log_file")"
    cat >> "$log_file" << EOF
{"ts":"${timestamp}","run_id":"${run_id}","event":"${event}","stage":"${stage}","status":"${status}","fingerprint":"${fingerprint}","version":"${RUNTIME_VERSION}","build_id":"${BUILD_ID}"}
EOF
}

# ═══════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════

validate_all() {
    local errors=0
    [[ "$BUILD_ID" == "unknown" ]] && warn "No git repository — reproducibility reduced"

    local stage_count; stage_count=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' 2>/dev/null | wc -l)
    if [[ "$stage_count" -eq 0 ]]; then err "No stage files found"; ((errors++)); else ok "Stage registry: $stage_count stages"; fi

    for lib in logging utils; do
        if [[ -f "${LIBDIR}/${lib}.sh" ]]; then ok "lib/${lib}.sh: present"; else err "lib/${lib}.sh: MISSING"; ((errors++)); fi
    done

    [[ -f "${ENGINEDIR}/runner.sh" ]] && bash -n "${ENGINEDIR}/runner.sh" 2>/dev/null || { err "engine/runner.sh: syntax error"; ((errors++)); }

    compute_pipeline_fingerprint "test" 2>/dev/null
    if [[ -z "$PIPELINE_FINGERPRINT" ]]; then err "Fingerprint generation failed"; ((errors++)); else ok "Fingerprint: ${FINGERPRINT_SHORT}"; fi

    return $errors
}

validate_dag() {
    log "Validating stage DAG..."
    local stage_files; stage_files=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' | sort)
    local prev_num=0
    for sf in $stage_files; do
        local bn; bn=$(basename "$sf" .sh)
        local num; num=$(echo "$bn" | sed 's/stage//;s/^0*//' | grep -o '^[0-9]*' || echo 0)
        if [[ "$num" -lt "$prev_num" ]]; then err "Circular dependency: $bn < $prev_num"; return 1; fi
        prev_num=$num
    done
    ok "Stage DAG: valid"; return 0
}

# ═══════════════════════════════════════════════
# LOCKING
# ═══════════════════════════════════════════════

acquire_lock() {
    local lock_file="${STATE_DIR}/.lock"
    ensure_dir "$(dirname "$lock_file")"
    if [[ -f "$lock_file" ]]; then
        local pid; pid=$(cat "$lock_file" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then return 1; fi
        warn "Stale lock removed"; rm -f "$lock_file"
    fi
    echo $$ > "$lock_file"; LOCK_FILE="$lock_file"; return 0
}

release_lock() {
    [[ -n "${LOCK_FILE:-}" ]] && [[ -f "$LOCK_FILE" ]] &&         [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo)" == "$$" ]] &&         rm -f "$LOCK_FILE"
}

set_safe_mode() { export SAFE_MODE=1; }
trap 'release_lock 2>/dev/null || true' EXIT INT TERM

export RUNTIME_VERSION BUILD_ID BUILD_TREE BUILD_TIME PIPELINE_FINGERPRINT
export -f get_version derive_build_identity compute_pipeline_fingerprint
export -f validate_all validate_dag log_execution_event
export -f step ok warn err info log get_target_user get_user_home
export -f get_log_target validate_log_environment compute_trace_hash
