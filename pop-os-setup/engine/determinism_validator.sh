#!/usr/bin/env bash
# engine/determinism_validator.sh
# Validates that pipeline is deterministic (fingerprint stable across runs)

set -euo pipefail

validate_determinism() {
    local run_a="$1" run_b="$2"
    local fp_a="${STATE_DIR}/run_${run_a}.meta/fingerprint"
    local fp_b="${STATE_DIR}/run_${run_b}.meta/fingerprint"
    
    if [[ ! -f "$fp_a" ]]; then
        echo "ERROR: No fingerprint for run_a: $run_a"
        return 1
    fi
    if [[ ! -f "$fp_b" ]]; then
        echo "ERROR: No fingerprint for run_b: $run_b"
        return 1
    fi
    
    local hash_a=$(sha256sum "$fp_a" | awk '{print $1}')
    local hash_b=$(sha256sum "$fp_b" | awk '{print $1}')
    
    if [[ "$hash_a" == "$hash_b" ]]; then
        echo "DETERMINISM: PASS (runs $run_a and $run_b are identical)"
        return 0
    else
        echo "DETERMINISM: FAIL"
        echo "  Run $run_a: ${hash_a:0:16}..."
        echo "  Run $run_b: ${hash_b:0:16}..."
        return 1
    fi
}

validate_determinism "$@"
