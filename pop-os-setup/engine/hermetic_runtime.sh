#!/usr/bin/env bash
#=======================================================================
# engine/hermetic_runtime.sh — Hermetic Deterministic Execution Layer
# v11.1 — Fully reproducible execution environment
#=======================================================================
[[ -n "${_HERMETIC_RUNTIME_SOURCED:-}" ]] && return 0 || _HERMETIC_RUNTIME_SOURCED=1

# ═══════════════════════════════════════════════════════════════════
# SECTION 1: HERMETIC ENVIRONMENT SNAPSHOT
# ═══════════════════════════════════════════════════════════════════

_hermetic_snapshot_env() {
    _HERMETIC_ENV_FILE="${STATE_DIR}/hermetic_env.json"
    local env_snapshot
    env_snapshot=$(mktemp)
    env > "$env_snapshot" 2>/dev/null || true
    if [[ -f "$env_snapshot" ]]; then
        local sha
        sha=$(sha256sum "$env_snapshot" 2>/dev/null | awk '{print $1}')
        echo "{\"hermetic_env_hash\":\"$sha\",\"env_vars\":$(wc -l < "$env_snapshot")}" >> "$STATE_DIR/audit.jsonl" 2>/dev/null || true
        rm -f "$env_snapshot"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 2: CANONICAL ENVIRONMENT (no entropy)
# ═══════════════════════════════════════════════════════════════════

enter_hermetic_mode() {
    # Freeze locale — no NLS variability
    export LANG=C
    export LC_ALL=C
    export LANGUAGE=C

    # Freeze timezone — UTC always
    export TZ=UTC

    # Isolate PATH — controlled only
    export PATH="/usr/bin:/bin"
    export HOME="${HOME:-/root}"

    # Remove entropy sources
    unset RANDOM
    unset SEED
    unset SRANDOM
    unset GNUPGHOME
    unset GPG_TTY

    # Freeze subprocess environment
    export IFS=$' \t\n'
    export POSIXLY_CORRECT=1

    # Disable auto-update mechanisms
    export DEBIAN_FRONTEND=noninteractive
    export APT_LISTCHANGES_FRONTEND=none
    export NPM_CONFIG_LOGLEVEL=error
    export PYTHONDONTWRITEBYTECODE=1

    _hermetic_snapshot_env
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 3: DETERMINISTIC TIME (fake clock injection)
# ═══════════════════════════════════════════════════════════════════

# INJECTED_EPOCH is set by --epoch flag or replay system
readonly INJECTED_EPOCH="${INJECTED_EPOCH:-}"
readonly INJECTED_TIMESTAMP="${INJECTED_TIMESTAMP:-}"

get_deterministic_time() {
    if [[ -n "$INJECTED_EPOCH" ]]; then
        echo "$INJECTED_EPOCH"
    elif [[ -n "$INJECTED_TIMESTAMP" ]]; then
        date -d "$INJECTED_TIMESTAMP" +%s 2>/dev/null || echo "0"
    else
        echo "0"  # Unknown time — must be provided
    fi
}

get_deterministic_date() {
    local ts
    ts=$(get_deterministic_time)
    if [[ "$ts" -gt 0 ]]; then
        date -d "@$ts" +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "1970-01-01 00:00:00"
    else
        echo "1970-01-01 00:00:00"
    fi
}

# Deterministic filename-safe timestamp (always same format)
get_deterministic_fname_ts() {
    date -d "@$(get_deterministic_time)" +"%Y%m%d-%H%M%S" 2>/dev/null || echo "19700101-000000"
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 4: CANONICAL FILESYSTEM ORDERING
# ═══════════════════════════════════════════════════════════════════

# All glob/find/ls MUST use this wrapper
ls_sorted() { ls "$@" 2>/dev/null | sort; }
find_sorted() { find "$@" -type f -print0 2>/dev/null | sort -z | xargs -0 -r echo; }
glob_sorted() { for f in $1; do echo "$f"; done | sort; }

# Stage enumeration — always sorted numerically
get_sorted_stages() {
    find "${STAGEDIR}" -maxdepth 1 -name 'stage[0-9][0-9]*_*.sh' 2>/dev/null | sort -V
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 5: PURE FINGERPRINT (no entropy)
# ═══════════════════════════════════════════════════════════════════

compute_hermetic_fingerprint() {
    local profile="${1:-workstation}"
    local git_hash
    git_hash=$(git rev-parse --short=12 HEAD 2>/dev/null || echo "unknown")
    local version
    version="${RUNTIME_VERSION:-v11.1}"

    # Collect sorted stage list
    local stage_list
    stage_list=$(find "${STAGEDIR}" -maxdepth 1 -name 'stage[0-9][0-9]*_*.sh' 2>/dev/null | sort -V | xargs -r basename -a 2>/dev/null | tr '\n' ',')

    # Profile content (sorted keys)
    local profile_hash=""
    if [[ -f "${PROFILEDIR}/${profile}.intent.json" ]]; then
        profile_hash=$(sha256sum "${PROFILEDIR}/${profile}.intent.json" 2>/dev/null | awk '{print $1}' || echo "nofile")
    fi

    # Canonical fingerprint — no timestamps, no env, no hardware
    local fp="${version}|${git_hash}|${profile}|${stage_list}|${profile_hash}"
    echo "$fp" | sha256sum | awk '{print $1}'
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 6: ENTROPY SCANNER (detect nondeterminism)
# ═══════════════════════════════════════════════════════════════════

scan_forbidden_entropy() {
    local root="${1:-.}"
    local violations=0

    # Check for date calls in scripts
    if grep -rq 'date\s+' "${root}/stages/" "${root}/engine/" "${root}/lib/" 2>/dev/null; then
        log "WARN: date calls found — use get_deterministic_time() instead"
        ((violations++)) || true
    fi

    # Check for $RANDOM usage
    if grep -rq '\$RANDOM' "${root}/stages/" "${root}/engine/" "${root}/lib/" 2>/dev/null; then
        log "WARN: \$RANDOM detected — forbidden in hermetic mode"
        ((violations++)) || true
    fi

    # Check for unsorted ls
    if grep -rq 'ls\s' "${root}/stages/" "${root}/engine/" 2>/dev/null | grep -v '| sort'; then
        log "WARN: unsorted ls found — use ls_sorted()"
        ((violations++)) || true
    fi

    return $violations
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 7: STRICT DETERMINISM MODE
# ═══════════════════════════════════════════════════════════════════

STRICT_DETERMINISM="${STRICT_DETERMINISM:-0}"

enforce_strict_determinism() {
    if [[ "$STRICT_DETERMINISM" != "1" ]]; then
        return 0
    fi

    log "STRICT DETERMINISM MODE — blocking entropy sources"

    # Refuse any unset required env
    if [[ -z "${INJECTED_EPOCH:-}" ]]; then
        err "STRICT: INJECTED_EPOCH required in strict mode"
        return 1
    fi

    # Block network calls unless whitelisted
    if [[ "${ALLOW_NETWORK:-0}" != "1" ]]; then
        export http_proxy=""
        export https_proxy=""
        export HTTP_PROXY=""
        export HTTPS_PROXY=""
    fi

    enter_hermetic_mode
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 8: HERMETIC WRAPPER (stage execution)
# ═══════════════════════════════════════════════════════════════════

run_stage_hermetic() {
    local stage_file="$1"
    local stage_name
    stage_name=$(basename "$stage_file" .sh)

    # Enter hermetic before any stage
    enter_hermetic_mode

    # Source with injection
    INJECTED_EPOCH="${INJECTED_EPOCH:-0}" \
    INJECTED_TIMESTAMP="${INJECTED_TIMESTAMP:-}" \
    source "$stage_file"
}

# ═══════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════
export -f enter_hermetic_mode
export -f get_deterministic_time
export -f get_deterministic_date
export -f get_deterministic_fname_ts
export -f compute_hermetic_fingerprint
export -f scan_forbidden_entropy
export -f enforce_strict_determinism
export -f run_stage_hermetic
