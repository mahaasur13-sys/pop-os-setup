#!/usr/bin/env bash
# engine/pipeline_lock.sh
# Ensures immutable pipeline: no patches during locked state

set -euo pipefail

PIPELINE_LOCK="${STATE_DIR}/pipeline.lock"

acquire_lock() {
    if [[ -f "$PIPELINE_LOCK" ]]; then
        echo "ERROR: Pipeline is locked by $(cat $PIPELINE_LOCK)"
        return 1
    fi
    echo "$$" > "$PIPELINE_LOCK"
    echo "Pipeline lock acquired: $$"
}

release_lock() {
    rm -f "$PIPELINE_LOCK"
    echo "Pipeline lock released"
}

validate_locked() {
    if [[ ! -f "$PIPELINE_LOCK" ]]; then
        echo "ERROR: Pipeline not locked"
        return 1
    fi
    echo "Pipeline is locked: $(cat $PIPELINE_LOCK)"
    return 0
}

"$@"
