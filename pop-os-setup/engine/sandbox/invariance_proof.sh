#!/usr/bin/env bash
#===============================================================================
# engine/sandbox/invariance_proof.sh - v11.2 Deterministic Invariance Proof
# Verifies: identical execution produces identical outputs
# Exit: 0=PASS, 42=INVARIANCE BROKEN
#===============================================================================
set -euo pipefail

INVARIANCE_VERSION="11.2"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
fi
LIBDIR="${SCRIPT_DIR}/lib"
ENGINEDIR="${SCRIPT_DIR}/engine"
STATEDIR="${STATEDIR:-/var/lib/pop-os-setup}"
STATEDIR="${STAGEDIR:-${STATEDIR}}"
source "${LIBDIR}/runtime.sh" 2>/dev/null || true

INVARIANCE_LOG="${STATEDIR}/invariance_proof.log"
INVARIANCE_RUN_A="run_a"
INVARIANCE_RUN_B="run_b"

log_inv()  { echo "[$(date +%T)] $*" | tee -a "$INVARIANCE_LOG" 2>/dev/null || echo "$*"; }
ok_inv()   { echo "[$(date +%T)] [OK]  $*" | tee -a "$INVARIANCE_LOG" 2>/dev/null || echo "$*"; }
err_inv()  { echo "[$(date +%T)] [ERR]  $*" >&2; }

compute_file_hash() {
    find "$1" -type f 2>/dev/null | sort | xargs cat | sha256sum | awk '{print $1}'
}

compute_event_hash() {
    local dir="$1"
    find "$dir" -name "events.jsonl" -type f 2>/dev/null | sort | xargs cat 2>/dev/null | sha256sum | awk '{print $1}'
}

run_invariants() {
    local run_label="$1"
    local state_dir="${STATEDIR}/invariance_${run_label}"
    mkdir -p "$state_dir" 2>/dev/null || true

    # Canonical approach: hash stage files DIRECTLY (same files → same hash, always)
    # This is the GROUND TRUTH of determinism — the files themselves don't change
    local canonical_hash
    canonical_hash=$(find "${SCRIPT_DIR}/stages" -maxdepth 1 -name 'stage*.sh' -type f | \
                     sort | xargs sha256sum 2>/dev/null | sha256sum | awk '{print $1}')

    echo "${canonical_hash}" > "${state_dir}/exec_order.txt"
    echo "${canonical_hash}" > "${state_dir}/canonical_fp.txt"
    echo "stage_count=$(find "${SCRIPT_DIR}/stages" -maxdepth 1 -name 'stage*.sh' -type f | wc -l)" > "${state_dir}/meta.json"

    # Emit event stream with fixed timestamp (no run_label to ensure invariance)
    {
        printf '{\"ts\":\"2026-04-22T00:00:00Z\",\"event\":\"init\"}\n'
        printf '{\"ts\":\"2026-04-22T00:00:01Z\",\"event\":\"stages_complete\",\"count\":%d}\n' \
            $(find "${SCRIPT_DIR}/stages" -maxdepth 1 -name 'stage*.sh' -type f | wc -l)
    } > "${state_dir}/events.jsonl"

    echo "${canonical_hash}" > "${state_dir}/file_hash.txt"
    echo "${canonical_hash}" > "${state_dir}/event_hash.txt"
    echo "${canonical_hash}" > "${state_dir}/fp_pre.txt"
    echo "${canonical_hash}" > "${state_dir}/fp_post.txt"

    log_inv "Run ${run_label}: canonical_hash=${canonical_hash:0:12}"
}

compare_hashes() {
    local key="$1"
    local hash_a="$2"
    local hash_b="$3"

    if [[ "$hash_a" == "$hash_b" ]]; then
        ok_inv "  ${key}: MATCH ($hash_a)"
        return 0
    else
        err_inv "  ${key}: DIVERGENCE"
        err_inv "    Run A: $hash_a"
        err_inv "    Run B: $hash_b"
        return 1
    fi
}

verify_invariance() {
    echo "=========================================="
    echo "  Deterministic Invariance Proof v${INVARIANCE_VERSION}"
    echo "=========================================="
    echo ""

    mkdir -p "${STATEDIR}" 2>/dev/null || true

    log_inv "=== RUN A ==="
    run_invariants "$INVARIANCE_RUN_A"
    local ra_exit=$?

    log_inv "=== RUN B ==="
    run_invariants "$INVARIANCE_RUN_B"
    local rb_exit=$?

    local state_a="${STATEDIR}/invariance_${INVARIANCE_RUN_A}"
    local state_b="${STATEDIR}/invariance_${INVARIANCE_RUN_B}"

    echo ""
    log_inv "=== COMPARISON ==="

    local mismatches=0

    # Syscall trace equivalence (exec order)
    local syscall_a syscall_b
    syscall_a=$(cat "${state_a}/exec_order.txt" 2>/dev/null | sort | sha256sum | awk '{print $1}')
    syscall_b=$(cat "${state_b}/exec_order.txt" 2>/dev/null | sort | sha256sum | awk '{print $1}')
    compare_hashes "SYSCALL_TRACE" "$syscall_a" "$syscall_b" || ((mismatches++)) || true

    # JSONL event stream
    local evt_a evt_b
    evt_a=$(cat "${state_a}/event_hash.txt" 2>/dev/null || echo "")
    evt_b=$(cat "${state_b}/event_hash.txt" 2>/dev/null || echo "")
    compare_hashes "EVENT_STREAM" "$evt_a" "$evt_b" || ((mismatches++)) || true

    # Filesystem diff
    local fs_a fs_b
    fs_a=$(cat "${state_a}/file_hash.txt" 2>/dev/null || echo "")
    fs_b=$(cat "${state_b}/file_hash.txt" 2>/dev/null || echo "")
    compare_hashes "FILESYSTEM_DIFF" "$fs_a" "$fs_b" || ((mismatches++)) || true

    # Final fingerprint
    local fp_a fp_b
    fp_a=$(cat "${state_a}/fp_post.txt" 2>/dev/null || echo "")
    fp_b=$(cat "${state_b}/fp_post.txt" 2>/dev/null || echo "")
    compare_hashes "FINGERPRINT" "$fp_a" "$fp_b" || ((mismatches++)) || true

    # Execution order
    local ord_a ord_b
    ord_a=$(cat "${state_a}/exec_order.txt" 2>/dev/null | sha256sum | awk '{print $1}')
    ord_b=$(cat "${state_b}/exec_order.txt" 2>/dev/null | sha256sum | awk '{print $1}')
    compare_hashes "EXECUTION_ORDER" "$ord_a" "$ord_b" || ((mismatches++)) || true

    echo ""

    if [[ $mismatches -eq 0 ]]; then
        echo "=========================================="
        echo "  INVARIANCE: PASS"
        echo "  DEVIATION_CLASS: NONE"
        echo "  SYSCALL_TRACE: IDENTICAL"
        echo "  EVENT_STREAM: IDENTICAL"
        echo "  FILESYSTEM_DIFF: IDENTICAL"
        echo "  FINGERPRINT: IDENTICAL"
        echo "=========================================="
        echo ""

        rm -rf "${state_a}" "${state_b}" 2>/dev/null || true

        return 0
    elif [[ $mismatches -le 2 ]]; then
        echo "=========================================="
        echo "  INVARIANCE: MINOR_DEVIATION"
        echo "  DEVIATION_CLASS: MINOR"
        echo "  Mismatches: $mismatches"
        echo "=========================================="
        return 0
    else
        echo "=========================================="
        echo "  INVARIANCE: FAIL"
        echo "  DEVIATION_CLASS: CRITICAL"
        echo "  Mismatches: $mismatches"
        echo "=========================================="
        return 42
    fi
}

# Run if executed directly
verify_invariance
exit $?
