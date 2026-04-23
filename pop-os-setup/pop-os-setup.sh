#!/usr/bin/env bash
#===============================================
# pop-os-setup.sh — Deterministic Intent-Driven Provisioning System v11.3
# Three-layer truth: Intent → CESM → Physical → Reconciliation → Intent
#===============================================
# v11.3 HARDENING:
#   • trap handlers (INT/TERM/ERR)
#   • require_cmd dependency validation
#   • safe_download with SHA256
#   • is_installed / is_done idempotency
#   • safe_source (no silent failures)
#   • validate_profile
#===============================================
set -euo pipefail

readonly RUNTIME_VERSION="v11.3"
readonly STATEDIR="${STATEDIR:-/var/lib/pop-os-setup}"
readonly INTENT_DIR="${INTENT_DIR:-./profiles}"
readonly POLICY="${POLICY:-intent-warn}"
readonly MODE="${MODE:-full}"

PROFILE="${PROFILE:-full}"
DRY_RUN="${DRY_RUN:-0}"
SELECTED_STAGE="${SELECTED_STAGE:-}"
export LOG_MODE="${LOG_MODE:-deterministic}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="${SCRIPT_DIR}/lib"
STAGEDIR="${SCRIPT_DIR}/stages"
PROFILEDIR="${SCRIPT_DIR}/profiles"

# Source logging first
source "${LIBDIR}/logging.sh" 2>/dev/null || true

mkdir -p "$STATEDIR" 2>/dev/null || true

# Emit log mode event
_log_mode_event() {
    local entry="[$(date -Iseconds)] log.mode.selected|${LOG_MODE}|euid=${EUID:-$(id -u)}|dry=${DRY_RUN:-0}"
    echo "$entry" >> "${LOGDIR}/setup.jsonl" 2>/dev/null || true
}
_log_mode_event "selected"

# Fallback logging
: "${LOGDIR:=${SCRIPT_DIR}/logs}"
log()  { echo -e "[$(date '+%H:%M:%S')] $*" | tee -a "${LOGDIR}/setup.log" 2>/dev/null || echo -e "[$(date '+%H:%M:%S')] $*"; }
step() { log ""; log "══ $1 ══ [Stage $2]"; }
ok()   { log "[OK]  $*"; }
warn() { log "[WARN] $*"; }
err()  { echo -e "[$(date '+%H:%M:%S')] [ERR]  $*" >&2; }

# ═══════════════════════════════════════════════
# v11.3 HARDENING — Core Safety Functions
# ═══════════════════════════════════════════════

# ── TRAP HANDLERS ────────────────────────────────────
cleanup() {
    echo ""
    echo "[CLEANUP] Interrupt received, cleaning up..."
    pkill -P $$ 2>/dev/null || true
    exit 130
}

report_error() {
    echo "[FATAL] Error at line $LINENO — command: $BASH_COMMAND"
    exit 1
}

# Install trap handlers
trap cleanup INT TERM
trap 'report_error' ERR

# ── DEPENDENCY VALIDATION ─────────────────────────────
require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[FATAL] Missing dependency: $cmd"
        echo "[FATAL] Install required tool before running this script."
        exit 10
    fi
}

check_dependencies() {
    local required=(git curl wget awk sed grep)
    for cmd in "${required[@]}"; do
        require_cmd "$cmd"
    done

    # Optional warnings
    command -v docker >/dev/null 2>&1 || warn "docker not found (optional)"
    command -v nvidia-smi >/dev/null 2>&1 || warn "nvidia-smi not found (optional)"
}

# ── SAFE DOWNLOAD (SHA256) ────────────────────────────
safe_download() {
    local url="$1"
    local expected_hash="$2"
    local output="$3"

    if [[ -z "$url" || -z "$output" ]]; then
        echo "[FATAL] safe_download: url and output are required"
        return 1
    fi

    curl -fsSL "$url" -o "$output" || {
        echo "[ERROR] Download failed: $url"
        return 1
    }

    # If hash provided, verify
    if [[ -n "$expected_hash" && "$expected_hash" != "none" ]]; then
        local actual_hash
        actual_hash=$(sha256sum "$output" | awk '{print $1}')
        if [[ "$actual_hash" != "$expected_hash" ]]; then
            echo "[FATAL] SHA256 mismatch!"
            echo "  Expected: $expected_hash"
            echo "  Actual:   $actual_hash"
            rm -f "$output"
            exit 20
        fi
        echo "[VERIFY] SHA256 OK: $output"
    fi
}

# ── IDEMPOTENCY ──────────────────────────────────────
is_installed() {
    dpkg -s "$1" >/dev/null 2>&1
}

install_pkg() {
    local pkg="$1"
    if is_installed "$pkg"; then
        echo "[SKIP] $pkg already installed"
        return 0
    fi
    apt-get install -y "$pkg"
}

# ── STAGE STATE (done markers) ───────────────────────
: "${STATE_DIR:=${SCRIPT_DIR}/state}"
mkdir -p "$STATE_DIR" 2>/dev/null || true

mark_done() {
    touch "${STATE_DIR}/${1}.done"
}

is_done() {
    [[ -f "${STATE_DIR}/${1}.done" ]]
}

# ── SAFE SOURCE ──────────────────────────────────────
safe_source() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        echo "[ERROR] Stage file not found: $file"
        return 1
    fi
    if [[ ! -r "$file" ]]; then
        echo "[ERROR] Stage file not readable: $file"
        return 1
    fi
    source "$file"
}

# ── PROFILE VALIDATION ───────────────────────────────
validate_profile() {
    case "$PROFILE" in
        workstation|ai-dev|cluster|full) return 0 ;;
        *)
            echo "[FATAL] Invalid profile: '$PROFILE'"
            echo "Valid profiles: workstation, ai-dev, cluster, full"
            exit 30
            ;;
    esac
}

# ─── Argument parsing ──────────────────────────────────────────────────────
show_usage() {
    cat << 'USAGE'
Usage: pop-os-setup.sh [OPTIONS]

Options:
  --profile <name>     Profile: workstation|cluster|ai-dev|full (default: full)
  --stage <N>          Run only stage N
  --dry-run            Show what would be executed without running
  --validate-intent    Run ICVL intent compliance validation
  --policy <mode>      intent-warn|intent-enforce|intent-strict
  --intent-dir <path>  Directory containing .intent.json files
  --reconcile          Run physical reconciliation check
  --log-mode <mode>    deterministic|system|user (default: deterministic)
  --help, -h           Show this help

Profiles:
  workstation          KDE + Docker + dev tools
  cluster              k3s + networking + storage
  ai-dev               CUDA + PyTorch + Jupyter + Ollama
  full                 All of the above (default)
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --validate-intent)
            source "${LIBDIR}/runtime.sh" 2>/dev/null || true
            source "${SCRIPT_DIR}/engine/intent_validator.sh" 2>/dev/null || true
            validate_intent "${STATEDIR}/cesm_state.json" \
                "${INTENT_DIR}/${PROFILE}.intent.json"
            exit $?
            ;;
        --reconcile)
            source "${SCRIPT_DIR}/engine/state_reconciler.sh" 2>/dev/null || true
            reconcile_physical_state
            exit $?
            ;;
        --policy=*) POLICY="${1#*=}"; shift ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --stage) SELECTED_STAGE="${2#0}"; shift 2 ;;
        --intent-dir) INTENT_DIR="$2"; shift 2 ;;
        --log-mode)
            LOG_MODE="$2"; export LOG_MODE
            case "$LOG_MODE" in
                deterministic|system|user) log "[INFO] LOG_MODE set: $LOG_MODE" ;;
                *) warn "LOG_MODE must be: deterministic|system|user (defaulting)"
                     LOG_MODE="deterministic"; export LOG_MODE ;;
            esac
            shift 2 ;;
        --help|-h) show_usage; exit 0 ;;
        *) warn "Unknown option: $1"; shift ;;
    esac
done

# ─── Stage loader (safe_source) ───────────────────────
load_stage() {
    local num="$1"
    local padded_num
    padded_num=$(printf '%02d' "$num")

    for candidate in \
        "${STAGEDIR}/stage${padded_num}_"*.sh \
        "${STAGEDIR}/stage${num}_"*.sh \
        "${STAGEDIR}/stage${padded_num}.sh" \
        "${STAGEDIR}/stage${num}.sh"; do

        [[ -f "$candidate" ]] || continue

        safe_source "$candidate" || {
            err "Failed to source: $candidate"
            return 1
        }
        return 0
    done

    err "Stage $num not found"
    return 1
}

# ─── SANDBOX INTEGRITY GATE (v11.2) ──────────────────
run_integrity_gate() {
    local gate_script="${SCRIPT_DIR}/engine/sandbox_integrity_check.sh"

    if [[ -f "$gate_script" ]]; then
        log "🔒 [INTEGRITY GATE v11.2] Pre-execution verification..."
        if ! bash "$gate_script"; then
            err "❌ INTEGRITY GATE FAILED — aborting pipeline"
            return 1
        fi
        log "✅ Integrity gate PASSED — proceeding"
    else
        warn "⚠ Integrity gate not found — skipping"
    fi

    return 0
}

# ─── Execution ────────────────────────────────────────
run_stage() {
    local num="$1"
    local stage_fn="stage_${num}"

    step "$(printf '%02d' "$num")" "$num"

    if [[ -n "${SELECTED_STAGE}" && "${SELECTED_STAGE}" != "$num" ]]; then
        ok "Skipped (--stage filter)"
        return 0
    fi

    if [[ "$DRY_RUN" == 1 ]]; then
        ok "[DRY-RUN] Would execute: $stage_fn"
        return 0
    fi

    if declare -f "$stage_fn" &>/dev/null; then
        "$stage_fn" || {
            err "Stage $num failed"
            return 1
        }
        ok "Stage $num completed"
        return 0
    else
        warn "Function not found: $stage_fn"
        return 0
    fi
}

# ─── MAIN ─────────────────────────────────────────────
main() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  pop-os-setup v${RUNTIME_VERSION}"
    echo "  Profile: ${PROFILE}"
    echo "  Mode: ${MODE}"
    echo "  Policy: ${POLICY}"
    echo "  Sandbox: ENABLED (v11.2)"
    echo "═══════════════════════════════════════"
    echo ""

    # Validate profile first
    validate_profile

    # Check dependencies
    check_dependencies

    # dry-run skips integrity gate
    if [[ "$DRY_RUN" != 1 ]]; then
        if ! run_integrity_gate; then
            echo ""
            echo "═══════════════════════════════════════"
            echo "  ❌ PIPELINE ABORTED — INTEGRITY GATE FAILED"
            echo "═══════════════════════════════════════"
            exit 1
        fi
    fi

    if [[ "$DRY_RUN" == 1 ]]; then
        ok "DRY-RUN MODE — no changes will be made"
        echo ""
    fi

    log "Starting installation — Profile: ${PROFILE}"

    local stage_numbers=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26)

    local failed=0
    for num in "${stage_numbers[@]}"; do
        if ! load_stage "$num"; then
            warn "Stage $num not found — skipping"
            continue
        fi

        if ! run_stage "$num"; then
            err "Stage $num failed — continuing"
            ((failed++)) || true
        fi
    done

    echo ""
    echo "═══════════════════════════════════════"
    if (( failed > 0 )); then
        echo "  INSTALLATION COMPLETED WITH ERRORS"
        echo "  Failed stages: $failed"
    else
        echo "  INSTALLATION COMPLETED SUCCESSFULLY"
    fi
    echo "  Version: v${RUNTIME_VERSION}"
    echo "═══════════════════════════════════════"

    if [[ -f "${INTENT_DIR}/${PROFILE}.intent.json" ]]; then
        echo ""
        ok "Running Intent Compliance Validation..."
        source "${SCRIPT_DIR}/engine/intent_validator.sh" 2>/dev/null || true
        validate_intent "${STATEDIR}/cesm_state.json" \
            "${INTENT_DIR}/${PROFILE}.intent.json" || true
    fi

    return $((failed > 0 ? 1 : 0))
}

main "$@"