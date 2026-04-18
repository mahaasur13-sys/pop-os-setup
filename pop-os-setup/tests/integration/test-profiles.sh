#!/bin/bash
#===============================================================================
# test-profiles.sh — Integration test for deployment profiles
#===============================================================================
# Validates: each profile in profiles/ can be sourced and correctly sets
# the ENABLE_* environment variables expected for that profile.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIBDIR="$REPO_ROOT/lib"
PROFILEDIR="$REPO_ROOT/profiles"

PASS=0; FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

# ==============================================================================
# Helpers
# ==============================================================================
reset_env() {
    unset ENABLE_SSH ENABLE_DOCKER ENABLE_CUDA ENABLE_AI ENABLE_HARDEN \
          ENABLE_KDE ENABLE_ZSH ENABLE_TAILSCALE ENABLE_K8S ENABLE_SLURM \
          ENABLE_MONITORING
}

expect_eq() {
    local var="$1"; local expected="$2"; local actual="$3"; local ctx="$4"
    [[ "$actual" == "$expected" ]] && pass "$ctx" || fail "$ctx (expected $expected, got $actual)"
}

# ==============================================================================
# Source logging.sh for log/ok/err functions (profile files call log())
# ==============================================================================
export LOGFILE="/tmp/test-profiles.log"
# shellcheck disable=SC1091
source "$LIBDIR/logging.sh"

# ==============================================================================
# Discover profile files
# ==============================================================================
profile_files=("$PROFILEDIR"/*.sh)

if [[ ${#profile_files[@]} -eq 0 ]] || [[ ! -f "${profile_files[0]}" ]]; then
    echo "No profile files found in $PROFILEDIR"
    exit 1
fi

echo "Found ${#profile_files[@]} profile files"

# ==============================================================================
# Test: each profile file sources without error
# ==============================================================================
for profile_file in "${profile_files[@]}"; do
    pname=$(basename "$profile_file")
    # shellcheck disable=SC1091
    source "$profile_file" 2>/dev/null && pass "$pname: sourced" || fail "$pname: source failed"
done

# ==============================================================================
# Test: workstation profile
# ==============================================================================
echo ""
echo "[workstation]"

reset_env
# shellcheck disable=SC1091
source "$PROFILEDIR/workstation.sh"
apply_profile_workstation 2>/dev/null

expect_eq "ENABLE_SSH"        "0" "$ENABLE_SSH"        "workstation: SSH disabled"
expect_eq "ENABLE_DOCKER"    "1" "$ENABLE_DOCKER"    "workstation: Docker enabled"
expect_eq "ENABLE_CUDA"      "0" "$ENABLE_CUDA"      "workstation: CUDA disabled"
expect_eq "ENABLE_AI"        "1" "$ENABLE_AI"        "workstation: AI enabled"
expect_eq "ENABLE_HARDEN"    "1" "$ENABLE_HARDEN"    "workstation: Hardening enabled"
expect_eq "ENABLE_KDE"       "1" "$ENABLE_KDE"       "workstation: KDE enabled"
expect_eq "ENABLE_ZSH"       "1" "$ENABLE_ZSH"       "workstation: Zsh enabled"
expect_eq "ENABLE_TAILSCALE" "0" "$ENABLE_TAILSCALE" "workstation: Tailscale disabled"
expect_eq "ENABLE_K8S"       "0" "$ENABLE_K8S"       "workstation: K8s disabled"
expect_eq "ENABLE_SLURM"     "0" "$ENABLE_SLURM"     "workstation: Slurm disabled"
expect_eq "ENABLE_MONITORING" "1" "$ENABLE_MONITORING" "workstation: Monitoring enabled"

# ==============================================================================
# Test: ai-dev profile
# ==============================================================================
echo ""
echo "[ai-dev]"

reset_env
# shellcheck disable=SC1091
source "$PROFILEDIR/ai-dev.sh"
apply_profile_ai_dev 2>/dev/null

expect_eq "ENABLE_SSH"        "0" "$ENABLE_SSH"        "ai-dev: SSH disabled"
expect_eq "ENABLE_DOCKER"    "1" "$ENABLE_DOCKER"    "ai-dev: Docker enabled"
expect_eq "ENABLE_CUDA"      "1" "$ENABLE_CUDA"      "ai-dev: CUDA enabled"
expect_eq "ENABLE_AI"        "1" "$ENABLE_AI"        "ai-dev: AI enabled"
expect_eq "ENABLE_HARDEN"    "1" "$ENABLE_HARDEN"    "ai-dev: Hardening enabled"
expect_eq "ENABLE_KDE"       "1" "$ENABLE_KDE"       "ai-dev: KDE enabled"
expect_eq "ENABLE_ZSH"       "1" "$ENABLE_ZSH"       "ai-dev: Zsh enabled"
expect_eq "ENABLE_TAILSCALE" "0" "$ENABLE_TAILSCALE" "ai-dev: Tailscale disabled"
expect_eq "ENABLE_K8S"       "0" "$ENABLE_K8S"       "ai-dev: K8s disabled"
expect_eq "ENABLE_SLURM"     "0" "$ENABLE_SLURM"     "ai-dev: Slurm disabled"
expect_eq "ENABLE_MONITORING" "1" "$ENABLE_MONITORING" "ai-dev: Monitoring enabled"

# ==============================================================================
# Test: cluster profile (if exists)
# ==============================================================================
if [[ -f "$PROFILEDIR/cluster.sh" ]]; then
    echo ""
    echo "[cluster]"

    reset_env
    # shellcheck disable=SC1091
    source "$PROFILEDIR/cluster.sh"
    apply_profile_cluster 2>/dev/null

    expect_eq "ENABLE_SSH"        "1" "$ENABLE_SSH"        "cluster: SSH enabled"
    expect_eq "ENABLE_DOCKER"    "1" "$ENABLE_DOCKER"    "cluster: Docker enabled"
    expect_eq "ENABLE_CUDA"      "1" "$ENABLE_CUDA"      "cluster: CUDA enabled"
    expect_eq "ENABLE_AI"        "1" "$ENABLE_AI"        "cluster: AI enabled"
    expect_eq "ENABLE_HARDEN"    "1" "$ENABLE_HARDEN"    "cluster: Hardening enabled"
    expect_eq "ENABLE_KDE"       "0" "$ENABLE_KDE"       "cluster: KDE disabled"
    expect_eq "ENABLE_ZSH"       "1" "$ENABLE_ZSH"       "cluster: Zsh enabled"
    expect_eq "ENABLE_TAILSCALE" "1" "$ENABLE_TAILSCALE" "cluster: Tailscale enabled"
    expect_eq "ENABLE_K8S"       "1" "$ENABLE_K8S"       "cluster: K8s enabled"
    expect_eq "ENABLE_SLURM"     "1" "$ENABLE_SLURM"     "cluster: Slurm enabled"
    expect_eq "ENABLE_MONITORING" "1" "$ENABLE_MONITORING" "cluster: Monitoring enabled"
fi

# ==============================================================================
# Test: apply_profile dispatcher via lib/profiles.sh
# ==============================================================================
echo ""
echo "[apply_profile dispatcher]"

# shellcheck disable=SC1091
source "$LIBDIR/profiles.sh"

for profile in workstation ai-dev; do
    reset_env
    apply_profile "$profile" 2>/dev/null
    [[ -n "$ENABLE_KDE" ]] && pass "apply_profile($profile) dispatcher sets vars" || fail "apply_profile($profile) dispatcher failed"
done

# Unknown profile should error
reset_env
apply_profile nonexistent 2>/dev/null && fail "apply_profile(unknown) should error" || pass "apply_profile(unknown) returns error"

# ==============================================================================
# Summary
# ==============================================================================
echo ""
echo "=== test-profiles.sh results: $PASS passed, $FAIL failed ==="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1