#!/usr/bin/env bash
#===============================================
# engine/intent_validator.sh — Intent Compliance Validation Engine (v1.0)
# Three-layer truth model: Intent → CESM → Physical → Reconciliation → Intent
#===============================================

set -euo pipefail

readonly INTENT_VALIDATOR_VERSION="v1.0"

validate_intent() {
    local cesm_file="${1:-${LOGDIR}/cesm_state.json}"
    local intent_file="$2"
    local policy="${POLICY:-intent-warn}"

    if [[ ! -f "$intent_file" ]]; then
        echo "ERROR: Intent file not found: $intent_file" >&2
        return 1
    fi

    if ! command -v python3 &>/dev/null; then
        echo "ERROR: python3 required for intent validation" >&2
        return 1
    fi

    echo "[ICVL] Validating against intent: $intent_file"

    local score
    score=$(python3 - "$cesm_file" "$intent_file" << 'PYEOF'
import json, sys, subprocess

cesm_file = sys.argv[1]
intent_file = sys.argv[2]

with open(intent_file) as f:
    intent = json.load(f)

with open(cesm_file) as f:
    cesm = json.load(f)

requirements = intent.get("requirements", {})
violations = []

for key, expected in requirements.items():
    cesm_value = cesm.get(key, "NOT_SET")
    if cesm_value == "NOT_SET":
        violations.append({"type": "missing_cesm_key", "key": key, "expected": expected})
    elif cesm_value != expected and expected not in ("enabled", "disabled"):
        violations.append({"type": "cesm_mismatch", "key": key, "expected": expected, "actual": cesm_value})

checks = {
    "nvidia_driver": ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
    "docker": ["docker", "ps"],
    "python": ["python3", "--version"],
    "zsh": ["zsh", "--version"],
    "neovim": ["nvim", "--version"],
}

for key, cmd in checks.items():
    expected = requirements.get(key)
    if expected and expected == "enabled":
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                violations.append({"type": "physical_check_failed", "key": key})
        except Exception as e:
            violations.append({"type": "physical_check_error", "key": key, "error": str(e)})

score = max(0, 100 - len(violations) * 10)
print(score)
PYEOF
)

    local grade="F"
    if (( score >= 90 )); then grade="A"
    elif (( score >= 80 )); then grade="B"
    elif (( score >= 70 )); then grade="C"
    fi

    echo ""
    echo "═══════════════════════════════════════"
    echo "  INTENT COMPLIANCE REPORT"
    echo "═══════════════════════════════════════"
    echo "  Score:  $score/100  [$grade]"
    echo "  Profile: $(basename "$intent_file" .intent.json)"
    echo "═══════════════════════════════════════"

    if (( score < 80 )); then
        echo "[CRITICAL] Score < 80 — INVALID DEPLOYMENT"
        case "$policy" in
            intent-enforce) return 3 ;;
            intent-strict) return 4 ;;
        esac
    fi

    echo "[OK] Intent compliance: $score/100"
    return 0
}

main() {
    local intent_file="${1:-}"
    local cesm_file="${LOGDIR}/cesm_state.json"

    if [[ -z "$intent_file" ]]; then
        echo "Usage: intent_validator.sh <profile.intent.json>" >&2
        return 1
    fi

    validate_intent "$cesm_file" "$intent_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
