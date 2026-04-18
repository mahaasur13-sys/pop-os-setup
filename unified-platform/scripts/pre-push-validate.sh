#!/usr/bin/env bash
# =============================================================================
# PRE-PUSH VALIDATION SCRIPT
# =============================================================================
# Purpose: Run before every git push to catch violations
# Failures: BLOCK push until resolved
#
# Checks:
#   ✓ C1: No direct terraform apply in code
#   ✓ C2: No ray.init with GPU args (without job-router)
#   ✓ C3: No kubectl apply (without pipeline approval)
#   ✓ C4: No forbidden ACOS imports (infra in acos/)
#   ✓ C5: Makefile entrypoint exists
#   ✓ C6: job-router.py exists
#   ✓ C7: environments/ directory exists
#   ✓ C8: promote.yml exists
#   ✓ C9: rollback.yml exists
# =============================================================================

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

ERRORS=0

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  PRE-PUSH VALIDATION — Enterprise Infrastructure Platform"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── C1: No direct terraform apply (excluding workflows) ──────────────────
echo "[C1] Checking for forbidden terraform apply in code..."
# terraform apply in .github/workflows/ is APPROVED (canonical path via CI)
# terraform apply in infra/scripts/acos-deploy/ is ACCEPTABLE (infra-tools)
# terraform apply in Makefile is APPROVED (infra-apply target)
if grep -r "terraform apply" --include="*.py" --include="*.sh" . 2>/dev/null | \
    grep -v "\.github/workflows" | \
    grep -v "infra/scripts/acos-deploy" | \
    grep -v "Makefile" | \
    grep -v "pre-push-validate" | \
    grep -v "#.*terraform apply"; then
    echo "  ❌ VIOLATION: Direct terraform apply found (outside approved paths)"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — terraform apply only in approved paths (Makefile, workflows)"
fi

# ─── C2: No ray.init with GPU args ───────────────────────────────────────
echo "[C2] Checking for ray.init with GPU args..."
if grep -r "ray\.init" --include="*.py" . 2>/dev/null | grep -v "job-router" | grep -v "test" | grep -v "#"; then
    # Check if it's in job-router.py (allowed) or elsewhere (forbidden)
    RAY_INIT_FILES=$(grep -rl "ray\.init" --include="*.py" . 2>/dev/null | grep -v job-router | grep -v test | grep -v __pycache__)
    if [ -n "$RAY_INIT_FILES" ]; then
        echo "  ❌ VIOLATION: ray.init found outside job-router.py"
        echo "     Files: $RAY_INIT_FILES"
        ERRORS=$((ERRORS + 1))
    else
        echo "  ✅ PASS — ray.init only in job-router.py"
    fi
else
    echo "  ✅ PASS — no ray.init found"
fi

# ─── C3: No kubectl apply (excluding ansible k8s role) ──────────────────
echo "[C3] Checking for kubectl apply..."
# kubectl apply in infra/ansible/roles/kubernetes/ is APPROVED (ansible role)
if grep -r "kubectl apply" --include="*.py" --include="*.sh" . 2>/dev/null | \
    grep -v "infra/ansible/roles/kubernetes" | \
    grep -v "pre-push-validate" | \
    grep -v "#.*kubectl apply"; then
    echo "  ❌ VIOLATION: kubectl apply found (requires explicit pipeline approval)"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — kubectl apply only in approved paths (ansible k8s role)"
fi

# ─── C4: ACOS isolation (basic check) ────────────────────────────────────
echo "[C4] Checking ACOS isolation..."
if grep -r "import.*terraform\|from.*terraform\|import.*ansible\|from.*ansible\|import.*kubernetes\|from.*k8s" \
    --include="*.py" acos/ acos_v6/ acos_v7/ acos_v8/ 2>/dev/null | \
    grep -v "__pycache__" | \
    grep -v "acos\.py\|acos_cli\.py"; then
    echo "  ❌ VIOLATION: ACOS isolation violated (infra imports in acos/)"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — ACOS isolation OK"
fi

# ─── C5: Makefile entrypoint exists ──────────────────────────────────────
echo "[C5] Checking Makefile entrypoint..."
if [ ! -f "Makefile" ]; then
    echo "  ❌ VIOLATION: Makefile not found"
    ERRORS=$((ERRORS + 1))
elif ! grep -q "infra-apply" Makefile; then
    echo "  ❌ VIOLATION: infra-apply target not in Makefile"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — Makefile with infra-apply exists"
fi

# ─── C6: job-router.py exists ────────────────────────────────────────────
echo "[C6] Checking job-router.py..."
if [ ! -f "domain/ai_scheduler/job-router.py" ]; then
    echo "  ❌ VIOLATION: job-router.py not found"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — job-router.py exists"
fi

# ─── C7: environments/ directory exists ──────────────────────────────────
echo "[C7] Checking environments/ directory..."
if [ ! -d "infra/terraform/environments" ]; then
    echo "  ❌ VIOLATION: infra/terraform/environments/ not found"
    ERRORS=$((ERRORS + 1))
elif [ ! -f "infra/terraform/environments/staging.tfvars" ]; then
    echo "  ❌ VIOLATION: staging.tfvars not found"
    ERRORS=$((ERRORS + 1))
elif [ ! -f "infra/terraform/environments/production.tfvars" ]; then
    echo "  ❌ VIOLATION: production.tfvars not found"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — environments/ with staging + production tfvars"
fi

# ─── C8: promote.yml exists ─────────────────────────────────────────────
echo "[C8] Checking promote.yml..."
if [ ! -f ".github/workflows/promote.yml" ]; then
    echo "  ❌ VIOLATION: promote.yml not found"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — promote.yml exists"
fi

# ─── C9: rollback.yml exists ─────────────────────────────────────────────
echo "[C9] Checking rollback.yml..."
if [ ! -f ".github/workflows/rollback.yml" ]; then
    echo "  ❌ VIOLATION: rollback.yml not found"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ PASS — rollback.yml exists"
fi

# ─── C10: Shell script permissions ───────────────────────────────────────
echo "[C10] Checking shell script permissions..."
BAD_PERMS=$(find infra/scripts -name "*.sh" -not -executable 2>/dev/null)
if [ -n "$BAD_PERMS" ]; then
    echo "  ⚠️  WARNING: Some scripts not executable: $BAD_PERMS"
    echo "     Run: chmod +x infra/scripts/day-scripts/*.sh"
fi

# ─── Summary ─────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ $ERRORS -gt 0 ]; then
    echo "  ❌ PRE-PUSH VALIDATION FAILED — $ERRORS error(s)"
    echo ""
    echo "  Fix violations before pushing:"
    echo "    • C2: Use job-router.py for GPU allocation"
    echo "    • C4: Move infra deps out of acos/ directory"
    echo "    • C6-C9: Create missing governance files"
    echo ""
    echo "  Or force push (NOT recommended): git push --no-verify"
    echo "═══════════════════════════════════════════════════════════════"
    exit 1
else
    echo "  ✅ ALL CHECKS PASSED — safe to push"
    echo ""
    echo "  Next steps:"
    echo "    git add ."
    echo "    git commit -m 'your message'"
    echo "    git push"
    echo "═══════════════════════════════════════════════════════════════"
    exit 0
fi
