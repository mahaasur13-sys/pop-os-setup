#!/bin/bash
#===============================================================================
# pop-os-setup v4.1.0 One-Line Installer
#===============================================================================
# Usage: curl -fsSL https://raw.githubusercontent.com/mahaasur13-sys/pop-os-setup/main/install.sh | bash
#
# Bootstrap distribution adapter layer — clones repo, validates integrity,
# prepares environment, hands off control to DAG engine (pop-os-setup.sh).
#===============================================================================

set -euo pipefail

REPO="https://github.com/mahaasur13-sys/pop-os-setup.git"
BRANCH="${POP_OS_BRANCH:-master}"
TARGET_DIR="${POP_OS_TARGET:-${HOME}/pop-os-setup}"
INSTALL_MODE="${POP_OS_MODE:-install}"

# ─── COLORS ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INSTALL]${NC} $1"; }
ok()      { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()     { echo -e "${RED}[ERR]${NC} $1"; }
fatal()   { echo -e "${RED}[FATAL]${NC} $1" >&2; exit 1; }

# ─── DEP CHECK ────────────────────────────────────────────────────────────────
deps_check() {
    info "Checking dependencies..."
    local missing=()
    for cmd in git curl; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        fatal "Missing required commands: ${missing[*]}"
    fi
    ok "Dependencies OK"
}

# ─── REPO CLONE ──────────────────────────────────────────────────────────────
clone_repo() {
    info "Cloning ${REPO} (branch: ${BRANCH})..."

    if [[ -d "$TARGET_DIR" ]]; then
        warn "Target directory exists: ${TARGET_DIR}"
        if [[ "${POP_OS_FORCE:-0}" == "1" ]]; then
            info "Forcing clean install..."
            rm -rf "$TARGET_DIR"
        else
            info "Keeping existing installation."
            info "Set POP_OS_FORCE=1 to override."
            cd "$TARGET_DIR"
            return 0
        fi
    fi

    if ! git clone --branch "$BRANCH" --depth=1 "$REPO" "$TARGET_DIR" 2>/dev/null; then
        fatal "Failed to clone repository"
    fi

    ok "Repository cloned to ${TARGET_DIR}"
}

# ─── VALIDATION ──────────────────────────────────────────────────────────────
validate() {
    info "Validating installation..."

    [[ -f "${TARGET_DIR}/pop-os-setup.sh" ]] || fatal "pop-os-setup.sh missing"
    [[ -f "${TARGET_DIR}/MANIFEST.json" ]]    || fatal "MANIFEST.json missing"

    # Validate JSON
    if command -v python3 &>/dev/null; then
        python3 -c "import json; json.load(open('${TARGET_DIR}/MANIFEST.json'))" 2>/dev/null || \
            warn "MANIFEST.json is not valid JSON (continuing anyway)"
    fi

    # Validate syntax of entry point
    bash -n "${TARGET_DIR}/pop-os-setup.sh" 2>/dev/null || \
        fatal "pop-os-setup.sh has syntax errors"

    ok "Validation passed"
}

# ─── PERMISSIONS ─────────────────────────────────────────────────────────────
fix_perms() {
    info "Setting permissions..."
    chmod +x "${TARGET_DIR}/pop-os-setup.sh"
    chmod +x "${TARGET_DIR}/lib/"*.sh 2>/dev/null || true
    chmod +x "${TARGET_DIR}/stages/"*.sh 2>/dev/null || true
    ok "Permissions set"
}

# ─── BOOTSTRAP DONE ──────────────────────────────────────────────────────────
show_next_steps() {
    echo ""
    ok "Installation complete! 🎉"
    echo ""
    echo -e "  ${CYAN}Target:${NC}   ${TARGET_DIR}"
    echo -e "  ${CYAN}Version:${NC}  $(git -C "$TARGET_DIR" describe --tags 2>/dev/null || echo "v4.1.0")"
    echo -e "  ${CYAN}Branch:${NC}   ${BRANCH}"
    echo ""
    echo "Next steps:"
    echo ""
    echo -e "  ${GREEN}# Dry-run (preview what will be installed)${NC}"
    echo -e "  cd ${TARGET_DIR} && sudo ./pop-os-setup.sh --dry-run --profile workstation"
    echo ""
    echo -e "  ${GREEN}# Full installation (workstation profile)${NC}"
    echo -e "  cd ${TARGET_DIR} && sudo ./pop-os-setup.sh --profile workstation"
    echo ""
    echo -e "  ${GREEN}# AI-Dev profile${NC}"
    echo -e "  cd ${TARGET_DIR} && sudo ./pop-os-setup.sh --profile ai-dev"
    echo ""
    echo -e "  ${GREEN}# Show all available stages${NC}"
    echo -e "  cd ${TARGET_DIR} && ./pop-os-setup.sh --list-stages"
    echo ""
}

# ─── AUTO-RUN MODE ───────────────────────────────────────────────────────────
auto_run() {
    local profile="${1:-workstation}"
    info "Running pop-os-setup.sh (profile: ${profile})..."
    echo ""

    cd "$TARGET_DIR"
    exec sudo ./pop-os-setup.sh --profile "$profile"
}

# ─── MAIN ─────────────────────────────────────────────────────────────────────
main() {
    deps_check
    clone_repo
    validate
    fix_perms

    if [[ "$INSTALL_MODE" == "run" ]]; then
        auto_run "${POP_OS_PROFILE:-workstation}"
    else
        show_next_steps
    fi
}

main