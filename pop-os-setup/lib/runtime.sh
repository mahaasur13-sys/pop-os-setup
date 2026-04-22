#!/usr/bin/env bash
#===============================================
# lib/runtime.sh — pop-os-setup v9.3 Runtime Engine
# Single source of truth for version, paths, state, identity.
#===============================================
# Version source: RUNTIME_VERSION — DO NOT hardcode elsewhere
#===============================================

[[ -n "${_RUNTIME_SOURCED:-}" ]] && return 0 || _RUNTIME_SOURCED=1

# ═══════════════════════════════════════════════
# VERSION (canonical source — single definition)
# ═══════════════════════════════════════════════

readonly RUNTIME_VERSION="v9.3"

get_version() { echo "$RUNTIME_VERSION"; }

# ═══════════════════════════════════════════════
# BUILD IDENTITY LAYER (v9.3 — immutable fingerprint)
# ═══════════════════════════════════════════════

derive_build_identity() {
    local script_dir="${1:-$PWD}"

    # Git-based build identity
    if [[ -d "$script_dir/.git" ]]; then
        BUILD_ID=$(git -C "$script_dir" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        BUILD_TREE=$(git -C "$script_dir" rev-parse HEAD 2>/dev/null || echo "unknown")
        BUILD_BRANCH=$(git -C "$script_dir" branch --show-current 2>/dev/null || echo "detached")
        BUILD_TAGS=$(git -C "$script_dir" tag --points-at HEAD 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    else
        BUILD_ID="no-git"
        BUILD_TREE="no-git"
        BUILD_BRANCH="none"
        BUILD_TAGS=""
    fi

    BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    BUILD_EPOCH=$(date -u +%s)

    readonly BUILD_ID BUILD_TREE BUILD_BRANCH BUILD_TAGS BUILD_TIME BUILD_EPOCH
}

derive_build_identity "${SCRIPT_DIR:-.}"

# ═══════════════════════════════════════════════
# PIPELINE FINGERPRINT (v9.3 — order-sensitive hash)
# Same input → identical fingerprint
# ═══════════════════════════════════════════════

compute_pipeline_fingerprint() {
    local profile="${1:-default}"
    local stages_list
    local stage_hash

    # Order-sensitive stage list hash
    stages_list=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' | sort | \
                  xargs grep -h '^stage_[0-9a-z_]*()' 2>/dev/null | \
                  sed 's/^[[:space:]]*//;s/().*//' | tr '\n' '|' | \
                  cat 2>/dev/null)

    stage_hash=$(printf '%s' "$stages_list" | sha256sum | awk '{print $1}')

    # Runtime version
    local ver_hash
    ver_hash=$(printf '%s' "$RUNTIME_VERSION" | sha256sum | awk '{print $1}')

    # Git commit
    local git_hash
    git_hash=$(printf '%s' "${BUILD_TREE:-unknown}" | sha256sum | awk '{print $1}')

    # Profile
    local prof_hash
    prof_hash=$(printf '%s' "$profile" | sha256sum | awk '{print $1}')

    # Combined fingerprint (order-sensitive)
    PIPELINE_FINGERPRINT=$(printf '%s%s%s%s' "$stage_hash" "$ver_hash" "$git_hash" "$prof_hash" | sha256sum | awk '{print $1}')
    readonly PIPELINE_FINGERPRINT

    # Short form for display
    FINGERPRINT_SHORT="${PIPELINE_FINGERPRINT:0:12}"
    readonly FINGERPRINT_SHORT
}

# ═══════════════════════════════════════════════
# ATTACH IDENTITY TO RUN (v9.3)
# Creates immutable run metadata
# ═══════════════════════════════════════════════

attach_run_identity() {
    local run_id="$1"
    local profile="${2:-default}"
    local log_dir="${LOGDIR:-/var/log/pop-os-setup}"
    local state_dir="${STATE_DIR:-/var/lib/pop-os-setup/state}"

    ensure_dir "$log_dir" 2>/dev/null || log_dir="/tmp/pop-os-setup-logs-$$"
    ensure_dir "$state_dir" 2>/dev/null || state_dir="/tmp/pop-os-setup-state-$$"

    local meta_file="${state_dir}/run_${run_id}.meta.json"
    local fingerprint
    compute_pipeline_fingerprint "$profile"
    fingerprint="$PIPELINE_FINGERPRINT"

    # Build identity object (attached to every run)
    cat > "$meta_file" << EOF
{
  "run_id": "$run_id",
  "version": "$(get_version)",
  "build_id": "${BUILD_ID}",
  "build_tree": "${BUILD_TREE}",
  "build_branch": "${BUILD_BRANCH}",
  "build_tags": "${BUILD_TAGS}",
  "build_time": "${BUILD_TIME}",
  "build_epoch": "${BUILD_EPOCH}",
  "profile": "${profile}",
  "fingerprint": "${fingerprint}",
  "fingerprint_short": "${FINGERPRINT_SHORT}",
  "stages_count": $(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' 2>/dev/null | wc -l),
  "runtime_version": "${RUNTIME_VERSION}",
  "hostname": "$(hostname 2>/dev/null || echo unknown)",
  "user": "$(whoami 2>/dev/null || echo unknown)",
  "os": "$(detect_os 2>/dev/null || echo unknown)"
}
EOF

    echo "$meta_file"
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
STATEDIR="${SCRIPT_DIR}/state"
LOGDIR="${SCRIPT_DIR}/logs"
readonly LIBDIR ENGINEDIR STAGEDIR PROFILEDIR STATEDIR LOGDIR

ensure_dir() { mkdir -p "$1" 2>/dev/null || true; }
ensure_dir "$STATEDIR"
ensure_dir "$LOGDIR"

# ═══════════════════════════════════════════════
# LOGGING (always sourcing from lib/)
# ═══════════════════════════════════════════════

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
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local rand
    rand=$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' ' | head -c 6)
    echo "${prefix}_${timestamp}_${rand}"
}

# ═══════════════════════════════════════════════
# OS DETECTION
# ═══════════════════════════════════════════════

detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${PRETTY_NAME:-unknown}"
    else
        echo "unknown"
    fi
}

is_pop_os() { grep -qi 'pop_os\|pop!_os' /etc/os-release 2>/dev/null; }

# ═══════════════════════════════════════════════
# USER HELPERS
# ═══════════════════════════════════════════════

get_target_user() {
    local u="${SUDO_USER:-}"
    [[ -z "$u" ]] && u="${USER:-}"
    [[ -z "$u" ]] && u=$(getent passwd 2>/dev/null | awk -F: '$3 >= 1000 {print $1; exit}')
    [[ -z "$u" ]] && u="root"
    echo "$u"
}

get_user_home() {
    local u="${1:-}"
    [[ -z "$u" ]] && u=$(get_target_user)
    getent passwd "$u" 2>/dev/null | cut -d: -f6 || echo "$HOME"
}

# ═══════════════════════════════════════════════
# FILE OPERATIONS
# ═══════════════════════════════════════════════

append_once() {
    local file="$1" line="$2"
    [[ -f "$file" ]] && grep -Fxq "$line" "$file" 2>/dev/null && return 2
    echo "$line" >> "$file"
    return 0
}

# ═══════════════════════════════════════════════
# EXECUTION IDENTITY LOG (v9.3 — structured JSONL)
# ═══════════════════════════════════════════════

log_execution_event() {
    local run_id="$1"
    local event="$2"
    local stage="${3:-}"
    local status="${4:-info}"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local fingerprint="${PIPELINE_FINGERPRINT:-unknown}"

    local log_file="${LOGDIR}/run_${run_id}.jsonl"
    ensure_dir "$(dirname "$log_file")"

    cat >> "$log_file" << EOF
{"ts":"${timestamp}","run_id":"${run_id}","event":"${event}","stage":"${stage}","status":"${status}","fingerprint":"${fingerprint}","version":"${RUNTIME_VERSION}","build_id":"${BUILD_ID}"}
EOF
}

# ═══════════════════════════════════════════════
# VALIDATION (v9.3 — reproducibility enforcement)
# ═══════════════════════════════════════════════

validate_all() {
    local errors=0

    # Check git identity
    if [[ "$BUILD_ID" == "unknown" ]]; then
        warn "No git repository — reproducibility reduced"
    fi

    # Check stage registry
    local stage_count
    stage_count=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' 2>/dev/null | wc -l)
    if [[ "$stage_count" -eq 0 ]]; then
        err "No stage files found in $STAGEDIR"
        ((errors++))
    else
        ok "Stage registry: $stage_count stages"
    fi

    # Check required lib files
    for lib in logging utils; do
        if [[ -f "${LIBDIR}/${lib}.sh" ]]; then
            ok "lib/${lib}.sh: present"
        else
            err "lib/${lib}.sh: MISSING"
            ((errors++))
        fi
    done

    # Check engine
    if [[ -f "${ENGINEDIR}/runner.sh" ]]; then
        ok "engine/runner.sh: present"
        bash -n "${ENGINEDIR}/runner.sh" 2>/dev/null || {
            err "engine/runner.sh: syntax error"
            ((errors++))
        }
    else
        warn "engine/runner.sh: not found (optional)"
    fi

    # Validate fingerprint generation
    compute_pipeline_fingerprint "test" 2>/dev/null
    if [[ -z "$PIPELINE_FINGERPRINT" ]]; then
        err "Fingerprint generation failed"
        ((errors++))
    else
        ok "Fingerprint: ${FINGERPRINT_SHORT}"
    fi

    return $errors
}

validate_dag() {
    log "Validating stage DAG..."

    local stage_files
    stage_files=$(find "$STAGEDIR" -maxdepth 1 -name 'stage*.sh' | sort)
    local prev_num=0

    for sf in $stage_files; do
        local bn
        bn=$(basename "$sf" .sh)
        local num
        num=$(echo "$bn" | sed 's/stage//;s/^0*//' | grep -o '^[0-9]*' || echo 0)
        if [[ "$num" -lt "$prev_num" ]]; then
            err "Circular dependency or reorder detected: $bn < $prev_num"
            return 1
        fi
        prev_num=$num
    done

    ok "Stage DAG: valid (no circular dependencies)"
    return 0
}

# ═══════════════════════════════════════════════
# LOCKING
# ═══════════════════════════════════════════════

acquire_lock() {
    local lock_file="${STATE_DIR}/.lock"
    ensure_dir "$(dirname "$lock_file")"

    if [[ -f "$lock_file" ]]; then
        local pid
        pid=$(cat "$lock_file" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        warn "Stale lock detected — removing"
        rm -f "$lock_file"
    fi

    echo $$ > "$lock_file"
    LOCK_FILE="$lock_file"
    return 0
}

release_lock() {
    [[ -n "${LOCK_FILE:-}" ]] && [[ -f "$LOCK_FILE" ]] && \
        [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo)" == "$$" ]] && \
        rm -f "$LOCK_FILE"
}

set_safe_mode() { export SAFE_MODE=1; }

trap 'release_lock 2>/dev/null || true' EXIT INT TERM

export RUNTIME_VERSION BUILD_ID BUILD_TREE BUILD_TIME PIPELINE_FINGERPRINT
export -f get_version derive_build_identity compute_pipeline_fingerprint attach_run_identity
export -f validate_all validate_dag log_execution_event
export -f step ok warn err info log
export -f get_target_user get_user_home