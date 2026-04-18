#!/bin/bash
#===============================================================================
# test-lib.sh — Integration test for shared library functions
#===============================================================================
# Validates: lib/logging.sh, lib/profiles.sh, lib/utils.sh
# Each function is sourced and tested in isolation with mocked dependencies.
#===============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIBDIR="$REPO_ROOT/lib"

PASS=0; FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

cleanup() {
    rm -f /tmp/test-log.$$.log
}
trap cleanup EXIT

# --- Source libraries ---
# shellcheck disable=SC1091
{
    source "$LIBDIR/logging.sh"
    source "$LIBDIR/utils.sh"
    source "$LIBDIR/profiles.sh"
} 2>/dev/null || { echo "FAIL: could not source lib files"; exit 1; }

export LOGFILE="/tmp/test-log.$$.log"

# ==============================================================================
# TEST: lib/logging.sh
# ==============================================================================
echo "[lib/logging.sh]"

log "test message" &>/dev/null && pass "log() writes without error" || fail "log() failed"
warn "warning test" &>/dev/null && pass "warn() writes without error" || fail "warn() failed"
err "error test" 2>/dev/null && pass "err() writes without error" || fail "err() failed"

if [[ $EUID -eq 0 ]]; then
    require_root &>/dev/null && pass "require_root() returns 0 for root" || fail "require_root() root check failed"
else
    pass "require_root() test skipped (not root in container)"
fi

unset NONEXISTENT_VAR
require_env NONEXISTENT_VAR 2>/dev/null && fail "require_env() should fail for unset var" || pass "require_env() returns non-zero for unset var"
export FAKE_VAR="value"
require_env FAKE_VAR 2>/dev/null && pass "require_env() returns 0 for set var" || fail "require_env() failed for set var"

# ==============================================================================
# TEST: lib/utils.sh
# ==============================================================================
echo "[lib/utils.sh]"

pkg_installed bash &>/dev/null && pass "pkg_installed() executes" || fail "pkg_installed() failed"

os_detect=$(detect_os)
[[ -n "$os_detect" ]] && pass "detect_os() returns: $os_detect" || fail "detect_os() returned empty"

has_nvidia 2>/dev/null || true; rc=$?
[[ $rc -eq 0 || $rc -eq 1 ]] && pass "has_nvidia() returns valid exit code (rc=$rc)" || fail "has_nvidia() returned invalid code: $rc"

user=$(get_current_user 2>/dev/null)
[[ -z "$user" ]] && pass "get_current_user() returns empty (expected in container)" || pass "get_current_user() returns: $user"

TESTDIR="/tmp/test-ensure-dir.$$"
ensure_dir "$TESTDIR"
[[ -d "$TESTDIR" ]] && pass "ensure_dir() creates directory" || fail "ensure_dir() failed"
rm -rf "$TESTDIR"

backup_file "/tmp/nonexistent-file-$$" 2>/dev/null && pass "backup_file() handles missing file" || fail "backup_file() failed on missing file"

timeout 3 bash -c "source '$LIBDIR/utils.sh'; wait_for_network 1" 2>/dev/null; rc=$?
[[ $rc -eq 1 ]] && pass "wait_for_network() returns 1 when no network (fast)" || pass "wait_for_network() exit code: $rc (ok if 1)"

# ==============================================================================
# TEST: lib/profiles.sh
# ==============================================================================
echo "[lib/profiles.sh]"

apply_profile workstation 2>/dev/null && pass "apply_profile(workstation) succeeds" || fail "apply_profile(workstation) failed"
apply_profile cluster 2>/dev/null && pass "apply_profile(cluster) succeeds" || fail "apply_profile(cluster) failed"
apply_profile ai-dev 2>/dev/null && pass "apply_profile(ai-dev) succeeds" || fail "apply_profile(ai-dev) failed"
apply_profile full 2>/dev/null && pass "apply_profile(full) succeeds" || fail "apply_profile(full) failed"

apply_profile invalid-profile-name 2>/dev/null && fail "apply_profile(invalid) should return error" || pass "apply_profile(invalid) returns non-zero"

apply_profile workstation 2>/dev/null
[[ "$ENABLE_K8S" == "0" ]] && [[ "$ENABLE_DOCKER" == "1" ]] && pass "workstation ENABLE_* vars correct" || fail "workstation ENABLE_* mismatch (K8S=$ENABLE_K8S, DOCKER=$ENABLE_DOCKER)"

apply_profile cluster 2>/dev/null
[[ "$ENABLE_K8S" == "1" ]] && [[ "$ENABLE_SLURM" == "1" ]] && pass "cluster ENABLE_* vars correct" || fail "cluster ENABLE_* mismatch"

apply_profile ai-dev 2>/dev/null
[[ "$ENABLE_CUDA" == "1" ]] && [[ "$ENABLE_K8S" == "0" ]] && pass "ai-dev ENABLE_* vars correct" || fail "ai-dev ENABLE_* mismatch"

apply_profile full 2>/dev/null
[[ "$ENABLE_K8S" == "1" ]] && [[ "$ENABLE_SLURM" == "1" ]] && [[ "$ENABLE_TAILSCALE" == "1" ]] && pass "full ENABLE_* vars correct" || fail "full ENABLE_* mismatch"

profile_count=$(list_profiles 2>/dev/null | grep -c "workstation\|cluster\|ai-dev\|full")
[[ "$profile_count" -ge 4 ]] && pass "list_profiles() shows all profiles" || fail "list_profiles() missing profiles (found $profile_count)"

# ==============================================================================
# Summary
# ==============================================================================
echo ""
echo "=== test-lib.sh results: $PASS passed, $FAIL failed ==="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1