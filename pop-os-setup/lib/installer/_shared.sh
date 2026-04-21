#!/bin/bash
#===============================================================================
# lib/installer/_shared.sh — Shared installer primitives (v4.0.0)
#===============================================================================

[[ -n "${_INSTALLER_SHARED_SOURCED:-}" ]] && return 0
_INSTALLER_SHARED_SOURCED=1

INSTALLER_TMPDIR="${INSTALLER_TMPDIR:-/tmp/pop-os-installers}"
mkdir -p "$INSTALLER_TMPDIR" 2>/dev/null || true
chmod 700 "$INSTALLER_TMPDIR"

# ─── SAFE DOWNLOAD ───────────────────────────────────────────────────────────
# safe_download <url> <dest> [expected_sha256]
# Returns: 0=success, 1=failed, 2=sha256 mismatch
safe_download() {
    local url="$1" dest="$2" expected_sha="${3:-}"
    local filename="${dest##*/}"
    local max_retries=3 attempt=1

    log "Downloading ${filename}"

    while (( attempt <= max_retries )); do
        curl -fsSL --connect-timeout 15 --max-time 120 \
             -o "$dest" "$url" 2>/dev/null && break
        warn "Download failed (${attempt}/${max_retries}), retrying..."
        sleep $(( attempt * 2 ))
        ((attempt++)) || true
    done

    [[ ! -f "$dest" ]] && { err "Download failed: $url"; return 1; }

    if [[ -n "$expected_sha" ]]; then
        local actual_sha
        actual_sha=$(sha256sum "$dest" 2>/dev/null | awk '{print $1}')
        if [[ "$actual_sha" != "$expected_sha" ]]; then
            err "SHA256 mismatch for $filename"
            rm -f "$dest"
            return 2
        fi
        ok "SHA256 verified"
    fi

    chmod 644 "$dest"
    log "Downloaded: $filename ($(du -h "$dest" 2>/dev/null | cut -f1 || echo '?'))"
    return 0
}

# ─── SAFE GIT CLONE ────────────────────────────────────────────────────────────
# safe_git_clone <repo> <dest> [branch]
# Returns: 0=cloned, 1=error, 2=already exists (up-to-date)
safe_git_clone() {
    local repo="$1" dest="$2" branch="${3:-master}"

    if [[ -d "$dest/.git" ]]; then
        git -C "$dest" pull --quiet --rebase=false 2>/dev/null || true
        ok "Updated: ${dest##*/}"
        return 2
    fi

    log "Cloning ${repo}"
    git clone --depth=1 -b "$branch" "$repo" "$dest" 2>/dev/null || {
        err "Clone failed: $repo"
        return 1
    }
    ok "Cloned: ${dest##*/}"
    return 0
}

# ─── RETRY LOOP ──────────────────────────────────────────────────────────────
# retry_until <max_attempts> <interval_sec> <command...>
retry_until() {
    local max_attempts=$1 interval=$2
    shift 2
    local attempt=1

    while (( attempt <= max_attempts )); do
        if "$@"; then
            return 0
        fi
        warn "Attempt ${attempt}/${max_attempts} failed"
        ((attempt++)) || true
        sleep "$interval"
    done
    return 1
}

# ─── RANDOM PASSWORD ────────────────────────────────────────────────────────
generate_password() {
    local length="${1:-20}"
    if command -v openssl &>/dev/null; then
        openssl rand -base64 32 | tr -dc 'A-Za-z0-9!@#$%^&*()_+' | head -c "$length"
    else
        python3 - << PYEOF
import secrets, string
print("".join(secrets.choice(string.ascii_letters + string.digits + "!@#\$%^&*()_+") for _ in range($length)))
PYEOF
    fi
}

export -f safe_download safe_git_clone retry_until generate_password
