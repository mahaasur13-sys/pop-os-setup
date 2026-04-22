#!/usr/bin/env bash
#===============================================
set -euo pipefail
RED="''[0;31m'''; GREEN="''[0;32m'''; YELLOW="''[0;33m'''; BLUE="''[0;34m'''; BOLD="''[1m'''; RESET="''[0m'''

SCRIPT_DIR="''$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"''
WORKSPACE_DIR="''$(pwd)"''

print_header() { echo ""; echo "${BOLD}${BLUE}$(printf '''═'''%.0s {1..45})${RESET}"; echo "${BOLD}${BLUE}  $1"; echo "${BOLD}${BLUE}$(printf '''═'''%.0s {1..45})"; }

echo ""
echo "${BOLD}╔$(printf '''═'''%.0s {1..43})╗${RESET}"
echo "${BOLD}║   pop-os-setup v10.x Audit Suite    ║${RESET}"
echo "${BOLD}╚$(printf '''═'''%.0s {1..43})╝${RESET}"
echo ""

print_header "1. Syntax Check"
for f in "${SCRIPT_DIR}"/*.sh "${SCRIPT_DIR}"/stages/*.sh "${SCRIPT_DIR}"/lib/*.sh "${SCRIPT_DIR}"/engine/*.sh; do
  [[ -f "$f" ]] || continue
  echo -n "  $(basename "$f"): "
  bash -n "$f" 2>/dev/null && echo "${GREEN}OK${RESET}" || echo "${RED}FAIL${RESET}"
done

print_header "2. File Structure"
for d in stages lib profiles logs state observability engine; do
  echo -n "  $d/: "
  [[ -d "${SCRIPT_DIR}/$d" ]] && echo "${GREEN}✓${RESET}" || echo "${RED}✗${RESET}"
done

print_header "3. Stage Files Count"
total=0; present=0
for i in $(seq 1 26); do
  file=$(ls "${SCRIPT_DIR}"/stages/stage${i}_*.sh 2>/dev/null | head -1)
  [[ -n "$file" ]] && present=$((present+1)) || echo "  ! Stage ${i}: missing"
  total=$((total+1))
done
echo "  Stages: ${present}/${total} present"

print_header "4. Intent Profiles"
for p in workstation ai-dev cluster full; do
  echo -n "  ${p}.intent.json: "
  [[ -f "${SCRIPT_DIR}/profiles/${p}.intent.json" ]] && echo "${GREEN}✓${RESET}" || echo "${RED}✗${RESET}"
done

print_header "5. Core Runtime Files"
for f in lib/runtime.sh lib/observability.sh engine/intent_validator.sh engine/state_linearizer.sh; do
  echo -n "  $f: "
  [[ -f "${SCRIPT_DIR}/$f" ]] && echo "${GREEN}✓${RESET}" || echo "${RED}✗${RESET}"
done

print_header "6. Idempotency — stage sourcing (first 3 only)"
cnt=0
for f in "${SCRIPT_DIR}"/stages/*.sh; do
  [[ -f "$f" ]] || continue
  [[ $cnt -ge 3 ]] && break
  name=$(basename "$f")
  echo -n "  $name: "
  LIBDIR="${SCRIPT_DIR}/lib" bash "$f" &>/dev/null && echo "${GREEN}OK${RESET}" || echo "${RED}FAIL${RESET}"
  cnt=$((cnt+1))
done

print_header "7. Version"
v_main=$(grep -m1 '''RUNTIME_VERSION=''' "${SCRIPT_DIR}"/pop-os-setup.sh 2>/dev/null | cut -d'"' -f2)
echo "  Script:   ${v_main:-NOT FOUND}"
echo ""
echo "${BOLD}Audit Complete${RESET}"
