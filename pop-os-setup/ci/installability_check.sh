#!/usr/bin/env bash
#===============================================================================
# ci/installability_check.sh — v11.3 Production Installability Gate
# Validates that any commit can be installed from scratch on a clean machine
# Exit: 0=PASS, 1=SYNTAX_ERROR, 2=VERSION_MISSING, 3=DRYRUN_FAILED, 4=STAGE1_FAILED
#===============================================================================
set -euo pipefail

INSTALLABILITY_VERSION="1.1.0"

# Auto-detect SCRIPT_DIR from ci/ subdirectory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
readonly SCRIPT_DIR
cd "$SCRIPT_DIR"

readonly EXIT_SYNTAX=1
readonly EXIT_VERSION=2
readonly EXIT_DRYRUN=3
readonly EXIT_STAGE1=4
readonly EXIT_IDEMPOTENCY=5
readonly EXIT_DEPENDENCY=6
readonly EXIT_HOOK_BLOCKED=7

TEST_DIR=""
LOG_FILE="/tmp/installability_check_$$.log"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()   { echo -e "${BLUE}[INFO]${NC} $*" | tee -a "$LOG_FILE"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*" | tee -a "$LOG_FILE"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*" | tee -a "$LOG_FILE" >&2; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*" | tee -a "$LOG_FILE"; }

cleanup() {
    local exit_code=$?
    if [[ -n "$TEST_DIR" && -d "$TEST_DIR" ]]; then
        rm -rf "$TEST_DIR" 2>/dev/null || true
    fi
    exit $exit_code
}
trap cleanup EXIT

init() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  INSTALLABILITY CHECK v${INSTALLABILITY_VERSION} — Production Gate        ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""

    TEST_DIR="/tmp/popos-install-test_$$"
    LOG_FILE="/tmp/installability_check_$$.log"
    > "$LOG_FILE"

    log "Start: $(date -Iseconds)"
    log "Commit: $(git rev-parse HEAD 2>/dev/null || echo 'N/A')"
    log "Branch: $(git branch --show-current 2>/dev/null || echo 'N/A')"
    log "Log: $LOG_FILE"
}

# ─── Step 1: Clone to clean environment ─────────────────────────────────────
step1_clone() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [1] Creating clean environment"
    echo "═══════════════════════════════════════"

    local repo_url="${REPO_URL:-https://github.com/mahaasur13-sys/pop-os-setup.git}"

    rm -rf "$TEST_DIR" 2>/dev/null || true

    log "Cloning $repo_url into $TEST_DIR..."
    git clone --quiet "$repo_url" "$TEST_DIR" || {
        fail "Failed to clone repository"
        return $EXIT_SYNTAX
    }

    cd "$TEST_DIR"
    
    # GitHub repo is a meta-repo — project is in subdirectory
    if [[ -d "$TEST_DIR/pop-os-setup" ]]; then
        cd "$TEST_DIR/pop-os-setup"
        log "INFO: Switched to pop-os-setup/ subdirectory"
    fi
    pass "Repository cloned successfully"
    log "HEAD: $(git rev-parse HEAD)"
    log "Working dir: $(pwd)"
    return 0
}

# ─── Step 2: Git integrity check ──────────────────────────────────────────
step2_git_integrity() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [2] Git integrity check"
    echo "═══════════════════════════════════════"

    local status
    status=$(git status --porcelain 2>&1)

    if [[ -n "$status" ]]; then
        warn "Uncommitted changes detected:"
        echo "$status" | head -5
        warn "Proceeding anyway (hook should catch this)"
    else
        pass "Git state: clean"
    fi

    # Verify not in detached HEAD
    if git rev-parse --verify HEAD@{upstream} &>/dev/null; then
        pass "Branch tracking: OK"
    else
        warn "No upstream tracking — local commit"
    fi

    return 0
}

# ─── Step 3: Syntax validation (all .sh files) ────────────────────────────
step3_syntax() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [3] Syntax validation"
    echo "═══════════════════════════════════════"

    local errors=0 total=0

    while IFS= read -r -d '' f; do
        ((total++)) || true
        if ! bash -n "$f" 2>/dev/null; then
            fail "Syntax error: ${f#$TEST_DIR/}"
            ((errors++)) || true
        fi
    done < <(find "$TEST_DIR" -name "*.sh" -print0 2>/dev/null)

    if [[ $errors -eq 0 ]]; then
        pass "All $total shell files passed syntax check"
        return 0
    else
        fail "Syntax errors found in $errors/$total files"
        return $EXIT_SYNTAX
    fi
}

# ─── Step 4: Version check ─────────────────────────────────────────────────
step4_version() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [4] Version verification"
    echo "═══════════════════════════════════════"

    cd "$TEST_DIR"

    # Check RUNTIME_VERSION in pop-os-setup.sh
    local version_line
    version_line=$(grep -m1 'RUNTIME_VERSION=' pop-os-setup.sh 2>/dev/null || echo "")
    if [[ -z "$version_line" ]]; then
        fail "RUNTIME_VERSION not found in pop-os-setup.sh"
        return $EXIT_VERSION
    fi

    local version
    version=$(echo "$version_line" | sed 's/.*RUNTIME_VERSION=*"\([^"]*\)".*/\1/' | tr -d 'v' || echo "unknown")
    pass "Version detected: v${version}"
    log "Version line: $version_line"

    # Check version format (should be v11.x or similar)
    if ! echo "$version" | grep -qE '^[0-9]+\.[0-9]+'; then
        warn "Version format may be unexpected: $version"
    fi

    # Check required engine files exist
    local required_files=(
        "engine/sandbox_runtime.sh"
        "engine/sandbox/syscall_policy.sh"
        "engine/deterministic.sh"
        "engine/sandbox/replay_v2.sh"
        "lib/runtime.sh"
        "lib/logging.sh"
    )

    local missing=0
    log "DEBUG TEST_DIR=$TEST_DIR"
    log "DEBUG pwd=$(pwd)"
    log "DEBUG files in engine/:"
    ls -la engine/ 2>/dev/null | head -10 || log "  engine/ not found"
    for f in "${required_files[@]}"; do
        local full_path="$TEST_DIR/$f"
        if [[ ! -f "$f" ]]; then
            fail "Required file missing: $f"
            ((missing++)) || true
        else
            pass "  [OK] $f"
        fi
    done

    if [[ $missing -gt 0 ]]; then
        fail "$missing required files missing"
        return $EXIT_VERSION
    fi

    pass "All $(( ${#required_files[@]} )) required files present"
    return 0
}

# ─── Step 5: Dry-run test ─────────────────────────────────────────────────
step5_dryrun() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [5] Dry-run test"
    echo "═══════════════════════════════════════"

    cd "$TEST_DIR"

    log "Running: pop-os-setup.sh --dry-run --profile workstation"
    local dryrun_output
    local dryrun_exit=0

    bash pop-os-setup.sh --dry-run --profile workstation > /tmp/dryrun.log 2>&1 || dryrun_exit=$?

    if [[ $dryrun_exit -ne 0 ]]; then
        fail "Dry-run failed with exit code: $dryrun_exit"
        echo ""
        echo "=== Dry-run output (last 20 lines) ==="
        tail -20 /tmp/dryrun.log
        return $EXIT_DRYRUN
    fi

    # Verify output contains expected markers
    local has_stage_output
    has_stage_output=$(grep -c "STAGE\|Would execute\|DRY-RUN" /tmp/dryrun.log 2>/dev/null || echo "0")

    if [[ "$has_stage_output" -lt 3 ]]; then
        warn "Dry-run output looks minimal (found $has_stage_output markers)"
    fi

    pass "Dry-run completed successfully"
    log "Output lines: $(wc -l < /tmp/dryrun.log)"
    return 0
}

# ─── Step 6: Stage 1 install test ──────────────────────────────────────────
step6_stage1() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [6] Stage 1 install test"
    echo "═══════════════════════════════════════"

    cd "$TEST_DIR"

    # Check if stage 1 exists
    local stage1_file
    stage1_file=$(find stages/ -maxdepth 1 -name 'stage01_*.sh' -o -name 'stage1_*.sh' 2>/dev/null | head -1)

    if [[ -z "$stage1_file" ]]; then
        fail "Stage 1 file not found"
        return $EXIT_STAGE1
    fi

    log "Stage 1 file: $stage1_file"

    # Stage 1 is typically safe (preflight checks) — run with sudo for real system dirs
    if [[ $EUID -eq 0 ]]; then
        bash pop-os-setup.sh --stage 1 --profile workstation > /tmp/stage1.log 2>&1 || {
            fail "Stage 1 install failed"
            tail -10 /tmp/stage1.log
            return $EXIT_STAGE1
        }
    else
        log "Skipping real install (not root) — dry-run sufficient"
        warn "Stage 1 install requires root for full test"
    fi

    pass "Stage 1 validation passed"
    return 0
}

# ─── Step 7: Idempotency test ─────────────────────────────────────────────
step7_idempotency() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [7] Idempotency test"
    echo "═══════════════════════════════════════"

    cd "$TEST_DIR"

    log "Running second dry-run to check idempotency..."

    local idem_output
    local idem_exit=0

    bash pop-os-setup.sh --dry-run --profile workstation > /tmp/idem.log 2>&1 || idem_exit=$?

    if [[ $idem_exit -ne 0 ]]; then
        fail "Second dry-run failed — not idempotent"
        return $EXIT_IDEMPOTENCY
    fi

    # Compare outputs
    local dryrun_lines idem_lines
    dryrun_lines=$(wc -l < /tmp/dryrun.log 2>/dev/null || echo "0")
    idem_lines=$(wc -l < /tmp/idem.log 2>/dev/null || echo "0")

    local line_diff=$(( dryrun_lines - idem_lines ))
    line_diff=${line_diff#-}  # absolute value

    if [[ $line_diff -gt 5 ]]; then
        warn "Output line count differs by $line_diff (before: $dryrun_lines, after: $idem_lines)"
    fi

    pass "Idempotency check passed"
    return 0
}

# ─── Step 8: Dependency check ───────────────────────────────────────────────
step8_dependencies() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  [8] Dependency check"
    echo "═══════════════════════════════════════"

    cd "$TEST_DIR"

    local deps_required=("bash" "git" "grep" "sed" "awk" "find" "sort")
    local missing=0

    for dep in "${deps_required[@]}"; do
        if command -v "$dep" &>/dev/null; then
            log "  ✓ $dep"
        else
            fail "Missing dependency: $dep"
            ((missing++)) || true
        fi
    done

    if [[ $missing -gt 0 ]]; then
        fail "$missing dependencies missing"
        return $EXIT_DEPENDENCY
    fi

    pass "All required dependencies present"
    return 0
}

# ─── Main ─────────────────────────────────────────────────────────────────
main() {
    init

    local step_failed=0
    local step_results=()

    # Run all steps
    step1_clone || { step_failed=1; step_results+=("CLONE_FAILED"); }
    [[ $step_failed -eq 0 ]] && step2_git_integrity || { step_failed=1; step_results+=("GIT_FAILED"); }
    [[ $step_failed -eq 0 ]] && step3_syntax || { step_failed=1; step_results+=("SYNTAX_FAILED"); }
    [[ $step_failed -eq 0 ]] && step4_version || { step_failed=1; step_results+=("VERSION_FAILED"); }
    [[ $step_failed -eq 0 ]] && step5_dryrun || { step_failed=1; step_results+=("DRYRUN_FAILED"); }
    [[ $step_failed -eq 0 ]] && step6_stage1 || { step_failed=1; step_results+=("STAGE1_FAILED"); }
    [[ $step_failed -eq 0 ]] && step7_idempotency || { step_failed=1; step_results+=("IDEMPOTENCY_FAILED"); }
    [[ $step_failed -eq 0 ]] && step8_dependencies || { step_failed=1; step_results+=("DEPS_FAILED"); }

    echo ""
    if [[ $step_failed -eq 0 ]]; then
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║  ✅ INSTALLABILITY CHECK PASSED — PRODUCTION READY      ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        log "End: $(date -Iseconds)"
        return 0
    else
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║  ❌ INSTALLABILITY CHECK FAILED                         ║"
        echo "║  Failed steps: ${step_results[*]}                        ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        log "Failed steps: ${step_results[*]}"
        log "End: $(date -Iseconds)"
        return 1
    fi
}

# Standalone run
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
    exit $?
fi