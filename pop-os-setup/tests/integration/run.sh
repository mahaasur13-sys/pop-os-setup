#!/bin/bash
#===============================================================================
# Integration Test Runner — pop-os-setup
#===============================================================================
# Spins up a Docker container (ubuntu:24.04) with the repo mounted,
# then runs the selected test suite inside it.
# Usage: bash tests/integration/run.sh [--suite <name>|--help]
#   --suite all       — run all tests (default)
#   --suite lib       — lib functions only
#   --suite stages    — stage files only
#   --suite profiles  — profiles only
#   --suite cli       — CLI argument parsing only
#===============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="ubuntu:24.04"
SUITE="${SUITE:-all}"

usage() {
    echo "Usage: $0 [--suite <name>]"
    echo "  --suite all       — run all tests (default)"
    echo "  --suite lib       — lib functions only"
    echo "  --suite stages    — stage files only"
    echo "  --suite profiles  — profiles only"
    echo "  --suite cli       — CLI argument parsing only"
    echo "  --help            — show this help"
    exit 0
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --suite) SUITE="$2"; shift 2 ;;
        --help)  usage ;;
        *)       echo "Unknown option: $1"; usage ;;
    esac
done

echo "=== pop-os-setup integration tests ==="
echo "Repo: $REPO_ROOT"
echo "Suite: $SUITE"
echo ""

# Check Docker availability
if ! command -v docker &>/dev/null; then
    echo "Docker not found — falling back to host bash"
    echo "(Some tests may fail if shellcheck is missing)"
    SUITE="$SUITE" bash "$SCRIPT_DIR/test-lib.sh" || { echo "FAIL: test-lib.sh"; exit 1; }
    SUITE="$SUITE" bash "$SCRIPT_DIR/test-stages.sh" || { echo "FAIL: test-stages.sh"; exit 1; }
    SUITE="$SUITE" bash "$SCRIPT_DIR/test-profiles.sh" || { echo "FAIL: test-profiles.sh"; exit 1; }
    SUITE="$SUITE" bash "$SCRIPT_DIR/test-cli.sh" || { echo "FAIL: test-cli.sh"; exit 1; }
    echo ""
    echo "All tests passed (host fallback)."
    exit 0
fi

# Build test command list
case "$SUITE" in
    all)
        TESTS=("test-lib.sh" "test-stages.sh" "test-profiles.sh" "test-cli.sh")
        ;;
    lib|stages|profiles|cli)
        TESTS=("test-${SUITE}.sh")
        ;;
    *)
        echo "Unknown suite: $SUITE"
        usage
        ;;
esac

# Run tests inside Docker
for test in "${TESTS[@]}"; do
    test_path="$SCRIPT_DIR/$test"
    if [[ ! -f "$test_path" ]]; then
        echo "Test not found: $test_path"
        exit 2
    fi

    echo "--- Running $test ---"
    docker run --rm \
        --userns=host \
        -v "$REPO_ROOT:/repo:ro" \
        -w /repo \
        -e SUITE="$SUITE" \
        "$IMAGE" \
        bash -lc "apt-get update -qq && apt-get install -y -qq coreutils bash >/dev/null 2>&1; bash /repo/tests/integration/$test" \
    || { echo "FAIL: $test"; exit 1; }
    echo ""
done

echo "All tests passed."