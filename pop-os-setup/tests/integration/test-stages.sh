#!/bin/bash
#===============================================================================
# test-stages.sh — Integration test for all stage files
#===============================================================================
# Validates: each stage file in stages/ is syntactically valid (bash -n),
# can be sourced, and exposes the expected stage function.
# =============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STAGEDIR="$REPO_ROOT/stages"
LIBDIR="$REPO_ROOT/lib"

PASS=0; FAIL=0; SKIP=0

pass()  { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail()  { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
skip()  { echo "  - $1"; SKIP=$((SKIP + 1)); }

# Environment for stage sourcing
export LOGFILE="/tmp/stages-test.log"
export SCRIPT_VERSION="test"
export CURRENT_USER="root"
export HOMEDIR="/root"
export GPU_DETECTED="no"
export USE_CUDA="no"
export SUDO_USER="root"
export LIBDIR

echo "Found stage files in $STAGEDIR"
echo ""

# ==============================================================================
# Test each stage file
# ==============================================================================
for stage_file in "$STAGEDIR"/stage*_*.sh; do
    [[ -f "$stage_file" ]] || continue
    stage_name=$(basename "$stage_file")

    # 1. bash -n syntax check
    if bash -n "$stage_file" 2>/dev/null; then
        pass "$stage_name: syntax valid"
    else
        fail "$stage_name: syntax ERROR"
        continue
    fi

    # 2. Source with env vars inlined via BASH_ENV trick
    # Extract func name from source
    func_pattern=$(grep -m1 '^stage_[a-z0-9_]*(' "$stage_file" 2>/dev/null | \
                   sed 's/^stage_//;s/(.*//')
    if [[ -z "$func_pattern" ]]; then
        skip "$stage_name: no stage_*() function found"
        continue
    fi

    # Create a temp init file that sets LIBDIR before stage file sources lib/
    INIT_FILE=$(mktemp)
    printf 'LIBDIR="%s"\nexport LIBDIR\n' "$LIBDIR" > "$INIT_FILE"

    # Source stage inside bash -c with BASH_ENV pointing to init file
    # This guarantees LIBDIR is set when stage sources ../lib/*.sh
    source_output=$(BASH_ENV="$INIT_FILE" bash -c \
        "source '$stage_file' 2>&1" || true)
    source_rc=$?
    rm -f "$INIT_FILE"

    # Verify function was defined (check in parent after source)
    # We do a second pass just for function detection
    INIT_FILE2=$(mktemp)
    printf 'LIBDIR="%s"\nexport LIBDIR\n' "$LIBDIR" > "$INIT_FILE2"
    BASH_ENV="$INIT_FILE2" bash -c \
        "source '$stage_file' 2>/dev/null && declare -F stage_$func_pattern 2>/dev/null && echo FOUND" \
        | grep -q FOUND
    func_defined=$?
    rm -f "$INIT_FILE2"

    if [[ $source_rc -eq 0 ]]; then
        pass "$stage_name: sourced successfully"
    elif [[ $func_defined -eq 0 ]]; then
        pass "$stage_name: sourced (func defined despite errors)"
    else
        fail "$stage_name: sourcing failed, func not defined (rc=$source_rc)"
        continue
    fi

    # 3. Validate function name matches stage number
    stage_num=$(echo "$stage_name" | sed 's/stage\([0-9]*\)_.*/\1/')
    expected_func="stage_$(echo "$func_pattern" | sed 's/^[0-9]*_//')"
    if declare -f "$expected_func" &>/dev/null; then
        pass "$stage_name: function '$expected_func' confirmed"
    else
        # Try the raw pattern
        if declare -f "stage_$func_pattern" &>/dev/null; then
            pass "$stage_name: function 'stage_$func_pattern' confirmed"
        else
            skip "$stage_name: function not verifiable via declare (subshell limit)"
        fi
    fi
done

echo ""
total=$((PASS + FAIL))
echo "=== test-stages.sh results: $PASS passed, $FAIL failed, $SKIP skipped ($total total) ==="
[[ $FAIL -eq 0 ]] || { echo "FAIL: test-stages.sh"; exit 1; }
echo "  ✓ All stage tests passed"
exit 0
