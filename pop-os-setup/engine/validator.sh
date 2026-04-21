#!/bin/bash
#===============================================================================
# engine/validator.sh — v5.0.0 Schema + Integrity Validator
# Validates MANIFEST.json schema, stage integrity, and SHA256 signing
#===============================================================================

[[ -z "${_ENGINE_SOURCED:-}" ]] && { _ENGINE_SOURCED=1; } || return 0

# ─── SCHEMA ─────────────────────────────────────────────────────────────────
declare -A VALID_STAGE_FIELDS=(
    [id]=1
    [name]=1
    [profile]=1
    [deps]=1
    [parallel]=1
    [timeout]=1
    [rollback]=1
    [sha256]=1
)

# ─── MAIN VALIDATOR ──────────────────────────────────────────────────────────
validate_manifest() {
    local manifest="${1:-${MANIFEST_PATH}}"
    local exit_code=0

    log "Validating MANIFEST.json..."

    # File exists
    [[ -f "$manifest" ]] || { err "MANIFEST.json not found: $manifest"; return 1; }

    # Valid JSON
    if command -v python3 &>/dev/null; then
        python3 -c "import json; json.load(open('$manifest'))" 2>/dev/null || {
            err "MANIFEST.json: invalid JSON"
            return 1
        }
    fi

    # Required top-level fields
    local required_fields=("version" "schema" "stages")
    for field in "${required_fields[@]}"; do
        if ! python3 -c "import json; d=json.load(open('$manifest')); print(d.get('$field',''))" 2>/dev/null | grep -qv "^$"; then
            err "MANIFEST.json: missing required field: $field"
            exit_code=1
        fi
    done

    # Each stage: required fields
    python3 - << 'PYEOF' 2>/dev/null || exit_code=1
import json, sys, os
try:
    m = json.load(open(os.environ.get('MANIFEST_PATH', 'MANIFEST.json')))
except Exception as e:
    print(f"JSON parse error: {e}", file=sys.stderr)
    sys.exit(1)

valid_fields = {'id','name','profile','deps','parallel','timeout','rollback','sha256'}
required = {'id','name','profile'}

for i, stage in enumerate(m.get('stages', [])):
    missing = required - set(stage.keys())
    if missing:
        print(f"Stage[{i}]: missing required fields: {missing}", file=sys.stderr)
        sys.exit(1)
    unknown = set(stage.keys()) - valid_fields
    if unknown:
        print(f"Stage[{i}] '{stage.get('name','?')}': unknown fields: {unknown}", file=sys.stderr)
        sys.exit(1)

print(f"MANIFEST.json: {len(m.get('stages', []))} stages validated")
PYEOF

    if [[ $exit_code -eq 0 ]]; then
        ok "MANIFEST.json schema valid"
    fi

    return $exit_code
}

# ─── INTEGRITY CHECK ─────────────────────────────────────────────────────────
validate_integrity() {
    local stage_file="$1"
    local expected_sha="$2"

    [[ -z "$expected_sha" || "$expected_sha" == "null" ]] && return 0  # optional

    [[ -f "$stage_file" ]] || { err "File not found for integrity check: $stage_file"; return 1; }

    local actual_sha
    actual_sha=$(sha256sum "$stage_file" 2>/dev/null | awk '{print $1}')

    if [[ "$actual_sha" != "$expected_sha" ]]; then
        err "Integrity mismatch: $stage_file"
        err "  Expected: $expected_sha"
        err "  Got:      $actual_sha"
        return 1
    fi

    ok "Integrity OK: ${stage_file##*/}"
    return 0
}

# ─── SHA256 OF ENTIRE STAGE DIR ──────────────────────────────────────────────
compute_manifest_sha() {
    # Stable sort by filename, then SHA256
    find "${STAGES_DIR}" -name 'stage*.sh' -type f 2>/dev/null | \
        sort | xargs -d '\n' sha256sum 2>/dev/null | \
        sha256sum | awk '{print $1}'
}

# ─── ENFORCE MANIFEST LOCK ────────────────────────────────────────────────────
validate_lock() {
    local lock_file="${STATE_DIR}/.manifest.lock"
    [[ ! -f "$lock_file" ]] && return 0  # no lock = free run

    local locked_sha
    locked_sha=$(< "$lock_file")
    local current_sha
    current_sha=$(compute_manifest_sha)

    if [[ "$locked_sha" != "$current_sha" ]]; then
        err "MANIFEST lockdown active: stage files modified since last run"
        err "  Lock SHA:  $locked_sha"
        err "  Current:  $current_sha"
        err "  Remove ${lock_file} to override"
        return 1
    fi

    ok "MANIFEST lockdown enforced"
    return 0
}

# ─── LOCK MANIFEST ───────────────────────────────────────────────────────────
lock_manifest() {
    ensure_dir "${STATE_DIR}"
    compute_manifest_sha > "${STATE_DIR}/.manifest.lock"
    ok "MANIFEST locked: SHA=$(< "${STATE_DIR}/.manifest.lock")"
}

export -f validate_manifest validate_integrity validate_lock lock_manifest