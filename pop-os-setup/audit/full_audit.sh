#!/usr/bin/env bash
#==========================================================
# pop-os-setup v10.4 — FULL SYSTEM AUDIT
# Principal Engineer: asurdev / Zo Computer
# Run: sudo ./audit/full_audit.sh <RUN_ID>
#==========================================================
set -uo pipefail

# ─── COLORS ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
BLUE='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ─── CONFIG ──────────────────────────────────────────────
RUN_ID="${1:-audit-$(date +%Y%m%d-%H%M%S)}"
PROFILE="${PROFILE:-workstation}"
AUDIT_DIR="${AUDIT_DIR:-/var/log/pop-os-setup/audit}"
STATE_DIR="${STATE_DIR:-/var/opt/pop-os-setup/state}"
STAGES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../stages" && pwd)"
SCORE=0; MAX_SCORE=0; FAILED=()

# ─── OUTPUT HELPERS ──────────────────────────────────────
pass() { echo -e "  ${GREEN}✓${RESET} $1"; ((SCORE+=10)); ((MAX_SCORE+=10)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAILED+=("$1"); ((MAX_SCORE+=10)); }
info() { echo -e "  ${BLUE}ℹ${RESET} $1"; ((MAX_SCORE+=10)); }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; ((MAX_SCORE+=10)); }

header() { echo -e "\n${BOLD}══ $1 ══${RESET}"; }
section() { echo -e "\n${BOLD}── $1 ──${RESET}"; }

# ─── PRECHECKS ───────────────────────────────────────────
precheck() {
    section "PRECHECKS"
    # Root
    [[ $EUID -eq 0 ]]; pass "Running as root"
    # Find project root: derive from audit script location (not PWD)
    # Script is in: <PROJECT_ROOT>/audit/full_audit.sh
    # So PROJECT_ROOT = "$(dirname "${BASH_SOURCE[0]}")/.."
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    export PROJECT_ROOT
    if [[ -d "$PROJECT_ROOT/stages" && -f "$PROJECT_ROOT/pop-os-setup.sh" ]]; then
        cd "$PROJECT_ROOT" || exit 1
        # Verify git
        local git_root
        git_root="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
        if [[ -n "$git_root" ]]; then
            GIT_ROOT="$git_root"; export GIT_ROOT
            pass "Git repository: $git_root"
        fi
        pass "Project root: $PROJECT_ROOT"
    else
        fail "Not a pop-os-setup project (no stages/ or main script)"
        exit 1
    fi
    # Required dirs
    [[ -d "$STAGES_DIR" ]] || { fail "stages/ not found"; exit 1; }
    pass "stages/ directory"
    [[ -d engine/ ]] || { fail "engine/ not found"; exit 1; }
    pass "engine/ directory"
}

# ─── 1. VERSION SOURCE ──────────────────────────────────
check_version_source() {
    header "1. VERSION SOURCE (Single Source of Truth)"
    local main="${MAIN_SCRIPT:-pop-os-setup.sh}"
    if [[ ! -f "$main" ]]; then main="$(ls *.sh 2>/dev/null | head -1)"; fi
    if [[ -f "$main" ]]; then
        local ver_line
        ver_line=$(grep -m1 'RUNTIME_VERSION=' "$main" 2>/dev/null || echo "")
        if [[ -n "$ver_line" ]]; then
            pass "RUNTIME_VERSION found in $main"
            info "Line: $ver_line"
        else
            fail "RUNTIME_VERSION not found in $main"
        fi
    else
        fail "Main script not found"
    fi
}

# ─── 2. FILE INTEGRITY ───────────────────────────────────
check_file_integrity() {
    header "2. FILE INTEGRITY"
    local required=("lib/logging.sh" "lib/utils.sh" "lib/installer.sh")
    for f in "${required[@]}"; do
        [[ -f "$f" ]] && pass "lib: $f" || fail "MISSING: $f"
    done
}

# ─── 3. STAGE FILES ─────────────────────────────────────
check_stage_files() {
    header "3. STAGE FILES"
    local expected=(01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26)
    local missing=0
    for num in "${expected[@]}"; do
        local found
        found=$(ls "stages/stage${num}_"*.sh 2>/dev/null | head -1)
        if [[ -n "$found" ]]; then
            local fn
            fn=$(grep -m1 '^stage[0-9]' "$found" 2>/dev/null | sed 's/[(){].*//' | tr -d ' ')
            pass "Stage $num: $(basename "$found") → ${fn:-OK}"
        else
            fail "MISSING: stage${num}_*.sh"
            missing=$((missing+1))
        fi
    done
    if [[ $missing -eq 0 ]]; then
        info "All 26 stages present ✓"
    fi
}

# ─── 4. SYNTAX CHECK ────────────────────────────────────
check_syntax() {
    header "4. SYNTAX CHECK (bash -n)"
    local all_sh
    all_sh=$(find . -name "*.sh" -not -path "./.*" -not -path "./.git/*" | sort)
    local errors=0
    while IFS= read -r f; do
        bash -n "$f" 2>&1 | grep -q "syntax error" && {
            fail "SYNTAX ERROR: $f"
            errors=$((errors+1))
        } || pass "OK: $(basename "$f")"
    done <<< "$all_sh"
    [[ $errors -eq 0 ]] && pass "All files syntax-valid"
}

# ─── 5. DETERMINISM CHECK ────────────────────────────────
check_determinism() {
    header "5. DETERMINISM (Fingerprint)"
    local fp_file="${STATE_DIR}/manifest.fingerprint"
    if [[ -f "$fp_file" ]]; then
        local fp
        fp=$(cat "$fp_file" 2>/dev/null | head -c64)
        if [[ ${#fp} -eq 64 ]]; then
            pass "Fingerprint: ${fp:0:16}..."
        else
            warn "Fingerprint malformed: ${fp:-empty}"
        fi
    else
        info "No fingerprint yet (run after --dry-run)"
    fi
}

# ─── 6. STATE LEDGER ────────────────────────────────────
check_state_ledger() {
    header "6. STATE LEDGER (JSONL)"
    local ledger="${STATE_DIR}/run_ledger.jsonl"
    if [[ -f "$ledger" ]]; then
        local lines
        lines=$(wc -l < "$ledger" 2>/dev/null || echo 0)
        pass "Ledger: $lines entries"
        # Validate JSON
        if command -v python3 &>/dev/null; then
            python3 -c "import json; [json.loads(l) for l in open('$ledger')]" 2>/dev/null
            pass "JSONL valid (${lines} entries)"
        fi
    else
        warn "No ledger yet (run after dry-run)"
    fi
}

# ─── 7. EPOCH CHAIN ─────────────────────────────────────
check_epoch_chain() {
    header "7. EPOCH CHAIN"
    local chain="${STATE_DIR}/epoch_chain.jsonl"
    if [[ -f "$chain" ]]; then
        local entries
        entries=$(wc -l < "$chain" 2>/dev/null || echo 0)
        pass "Epoch chain: $entries entries"
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, sys
chain = [json.loads(l) for l in open('$chain')]
scores = [e.get('intent_score', 0) for e in chain]
avg = sum(scores)/len(scores) if scores else 0
print(f'  Average intent score: {avg:.1f}%')
sys.exit(0 if avg >= 90 else 1)
" 2>/dev/null && pass "Intent score ≥90% (chain valid)" || warn "Intent score <90% or malformed"
        fi
    else
        warn "No epoch chain yet"
    fi
}

# ─── 8. INTENT COMPLIANCE ───────────────────────────────
check_intent_compliance() {
    header "8. INTENT COMPLIANCE"
    local profile_file="profiles/${PROFILE}.intent.json"
    if [[ -f "$profile_file" ]]; then
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, sys
profile = json.load(open('$profile_file'))
checks = profile.get('intent_checks', [])
done = [c for c in checks if c.get('verified')]
score = int(100 * len(done) / len(checks)) if checks else 0
print(f'  Profile: $PROFILE')
print(f'  Checks: {len(done)}/{len(checks)}')
print(f'  Score: {score}%')
sys.exit(0 if score >= 90 else 1)
" 2>/dev/null && pass "Intent ≥90% ✓" || warn "Intent <90%"
        else
            info "python3 not available — skipping"
        fi
    else
        warn "Profile intent file not found: $profile_file"
    fi
}

# ─── 9. PHYSICAL RECONCILIATION ─────────────────────────
check_physical_recon() {
    header "9. PHYSICAL RECONCILIATION"
    local snapshot="${STATE_DIR}/system_snapshot.json"
    [[ -f "$snapshot" ]] && pass "Snapshot exists" || warn "No snapshot yet"
    if [[ -f "${STATE_DIR}/.reconciliation_report.json" ]]; then
        local dr
        dr=$(python3 -c "import json; d=json.load(open('${STATE_DIR}/.reconciliation_report.json')); print(d.get('drift_ratio','?'))" 2>/dev/null || echo "?")
        pass "Drift ratio: $dr"
    else
        info "Run system_snapshot.sh for drift detection"
    fi
}

# ─── 10. FAULT TOLERANCE ────────────────────────────────
check_fault_tolerance() {
    header "10. FAULT TOLERANCE"
    [[ -f engine/state_linearizer.sh ]] && pass "state_linearizer.sh exists"
    [[ -f engine/epoch_chain_validator.sh ]] && pass "epoch_chain_validator.sh exists"
    [[ -f observability/replay.sh ]] && pass "replay.sh exists"
    [[ -f observability/tracer.sh ]] && pass "tracer.sh exists"
}

# ─── FINAL VERDICT ──────────────────────────────────────
verdict() {
    header "FINAL VERDICT"
    local pct=$(( SCORE * 100 / MAX_SCORE ))
    echo -e "\n  Score: ${SCORE}/${MAX_SCORE} (${pct}%)"
    if [[ $pct -ge 90 ]]; then
        echo -e "  ${GREEN}${BOLD}🎯 PRODUCTION READY${RESET}"
        return 0
    elif [[ $pct -ge 70 ]]; then
        echo -e "  ${YELLOW}${BOLD}⚠ CONDITIONALLY READY${RESET}"
        return 1
    else
        echo -e "  ${RED}${BOLD}✗ NOT READY${RESET}"
        [[ ${#FAILED[@]} -gt 0 ]] && {
            echo -e "\n  ${RED}Failed checks:${RESET}"
            for f in "${FAILED[@]}"; do echo -e "    • $f"; done
        }
        return 2
    fi
}

# ─── MAIN ────────────────────────────────────────────────
main() {
    echo -e "\n${BOLD}╔══════════════════════════════════════╗╔══════════════════════════════════════╗╗
║   pop-os-setup v10.4 FULL AUDIT    ║║   RUN_ID: ${RUN_ID}   ║║
╚══════════════════════════════════════╝╚══════════════════════════════════════╝${RESET}"
    mkdir -p "$AUDIT_DIR" "$STATE_DIR" 2>/dev/null || true

    precheck
    check_version_source
    check_file_integrity
    check_stage_files
    check_syntax
    check_determinism
    check_state_ledger
    check_epoch_chain
    check_intent_compliance
    check_physical_recon
    check_fault_tolerance
    verdict
}

main "$@"
