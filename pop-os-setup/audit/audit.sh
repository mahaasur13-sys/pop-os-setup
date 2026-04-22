#!/usr/bin/env bash
#===============================================
# pop-os-setup Audit Suite v11.0
#===============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(pwd)"
LOGDIR="/var/log"

print_header() { echo ""; echo "=== $1 ===:"; }
print_ok()    { echo "  [OK]  $1"; }
print_fail()  { echo "  [FAIL] $1"; }
print_warn()  { echo "  [WARN] $1"; }
print_info()  { echo "  [INFO] $1"; }

audit_all() {
    local failed=0
    echo ""
    echo "pop-os-setup v11.0 — AUDIT REPORT"
    echo "================================"

    # 1. File integrity
    print_header "1. FILE INTEGRITY"
    for f in pop-os-setup.sh; do
        [[ -f "$SCRIPT_DIR/$f" ]] && print_ok "$f exists" || { print_fail "$f missing"; ((failed++)); }
    done

    # 2. Critical lib files
    print_header "2. CRITICAL LIB FILES"
    for lib in lib/runtime.sh observability/tracer.sh engine/state_linearizer.sh; do
        [[ -f "$SCRIPT_DIR/$lib" ]] && print_ok "$lib" || { print_fail "$lib missing"; ((failed++)); }
    done

    # 3. Stage files
    print_header "3. STAGE FILES"
    local stage_count
    stage_count=$(ls "$SCRIPT_DIR"/stages/stage*.sh 2>/dev/null | wc -l)
    echo "  Found: $stage_count stage files"
    [[ "$stage_count" -ge 10 ]] && print_ok "Stage count OK ($stage_count)" || { print_fail "Too few stages ($stage_count)"; ((failed++)); }

    # 4. Syntax check
    print_header "4. SYNTAX CHECK (bash -n)"
    for f in pop-os-setup.sh lib/runtime.sh; do
        bash -n "$SCRIPT_DIR/$f" 2>/dev/null && print_ok "$f" || { print_fail "$f syntax error"; ((failed++)); }
    done

    # 5. Log write access
    print_header "5. LOG DIRECTORY ACCESS"
    if [[ -w "$LOGDIR" ]] 2>/dev/null; then
        print_ok "/var/log writable"
    else
        print_warn "/var/log not writable (use bash + tee instead of sudo)"
    fi

    # 6. Version
    print_header "6. VERSION"
    grep -m1 "SCRIPT_VERSION" "$SCRIPT_DIR/pop-os-setup.sh" 2>/dev/null || print_warn "SCRIPT_VERSION not found"

    # Summary
    echo ""
    echo "================================"
    if [[ "$failed" -eq 0 ]]; then
        echo "RESULT: ALL CHECKS PASSED"
    else
        echo "RESULT: $failed CHECK(S) FAILED"
    fi
    echo "================================"
    echo ""
    echo "Run with: bash $SCRIPT_DIR/audit/audit.sh"
}

audit_all
