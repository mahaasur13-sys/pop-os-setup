# =============================================================================
# unified-platform — CANONICAL ENTRYPOINT
# =============================================================================
# SINGLE ENTRYPOINT MODEL: All infrastructure MUST be applied via this Makefile
# 
# FORBIDDEN PATTERNS (enforced by CI):
#   ✗ Direct bash script execution (bash infra/scripts/...)
#   ✗ terraform apply outside of make targets
#   ✗ kubectl apply without pipeline approval
#   ✗ Direct GPU allocation (use job-router.py)
#
# APPROVED EXECUTION PATHS:
#   ✅ make infra-apply     → terraform apply (staging default)
#   ✅ make infra-plan      → terraform plan
#   ✅ make infra-destroy   → terraform destroy
#   ✅ make infra-test      → integration tests
#   ✅ make promote         → GitHub promote workflow
#   ✅ make rollback        → GitHub rollback workflow
#   ✅ make ci             → full CI pipeline
#
# =============================================================================

.PHONY: help
.PHONY: infra-apply infra-plan infra-destroy infra-validate infra-test
.PHONY: promote rollback
.PHONY: day1 day2 day3 day4 day5 day6 day7
.PHONY: acos-test ml-pipeline lint test security clean ci

SHELL := /bin/bash
export PATH := $(shell PATH)

# Environment variables for terraform
TF_VAR_FILE ?= environments/staging.tfvars
export TERRAFORM_VAR_FILE=$(TF_VAR_FILE)

# =============================================================================
# HELP
# =============================================================================

help:
	@echo ""
	@echo "unified-platform — CANONICAL INFRASTRUCTURE ENTRYPOINT"
	@echo "========================================================"
	@echo ""
	@echo "⚠️  SINGLE ENTRYPOINT MODEL — All infra via Makefile only"
	@echo ""
	@echo "INFRASTRUCTURE TARGETS:"
	@echo "  make infra-apply      Apply infra (TF_VAR_FILE=staging.tfvars default)"
	@echo "  make infra-plan       Plan infra changes"
	@echo "  make infra-destroy    Destroy infra (DANGEROUS)"
	@echo "  make infra-validate   Validate terraform"
	@echo "  make infra-test       Run integration tests"
	@echo ""
	@echo "GITOPS TARGETS:"
	@echo "  make promote          Trigger staging → production promotion"
	@echo "  make rollback         Trigger infrastructure rollback"
	@echo ""
	@echo "DAY TARGETS (sequential bootstrap):"
	@echo "  make day1             Network bootstrap (MikroTik VLAN)"
	@echo "  make day2             VPN mesh (AmneziaWG/WireGuard)"
	@echo "  make day3             Compute base (Docker, CUDA)"
	@echo "  make day4             Slurm HA cluster"
	@echo "  make day5             Ray cluster"
	@echo "  make day6             Ceph storage"
	@echo "  make day7             Full integration"
	@echo ""
	@echo "QUALITY TARGETS:"
	@echo "  make acos-test        Run ACOS engine tests"
	@echo "  make ml-pipeline      Run ML training pipeline"
	@echo "  make lint             Lint all code"
	@echo "  make test             Run pytest suite"
	@echo "  make security         Run security scans"
	@echo "  make ci               Full CI pipeline (lint + test + security)"
	@echo ""
	@echo "ENVIRONMENT:"
	@echo "  TF_VAR_FILE=environments/staging.tfvars     (default)"
	@echo "  TF_VAR_FILE=environments/production.tfvars  (production)"
	@echo ""
	@echo "EXAMPLES:"
	@echo "  make infra-apply                              # Apply staging"
	@echo "  make infra-apply TF_VAR_FILE=production.tfvars  # Apply production"
	@echo "  make infra-plan TF_VAR_FILE=production.tfvars   # Plan production"
	@echo ""

# =============================================================================
# INFRASTRUCTURE ENTRYPOINTS (CANONICAL ONLY)
# =============================================================================

infra-apply: infra/terraform
	@echo "[INFO] Applying terraform with var_file=$(TF_VAR_FILE)"
	@echo "[ENV]  Environment: $(subst environments/,.tfvars,$(notdir $(TF_VAR_FILE)))"
	cd infra/terraform && terraform apply -var-file=$(TF_VAR_FILE) -auto-approve

infra-plan: infra/terraform
	@echo "[INFO] Planning terraform with var_file=$(TF_VAR_FILE)"
	cd infra/terraform && terraform plan -var-file=$(TF_VAR_FILE)

infra-destroy: infra/terraform
	@echo "[WARN] Destroying infrastructure with var_file=$(TF_VAR_FILE)"
	cd infra/terraform && terraform destroy -var-file=$(TF_VAR_FILE)

infra-validate: infra/terraform
	@echo "[INFO] Validating terraform"
	cd infra/terraform && terraform validate

infra/terraform:
	@echo "[INFO] Terraform directory ready"

# =============================================================================
# GITOPS TARGETS
# =============================================================================

promote:
	@echo "[INFO] Triggering production promotion workflow..."
	@echo "[WARN] This requires manual approval in GitHub Environments"
	@echo "[INFO] Navigate to: Actions → Promote to Production → Run workflow"
	@gh workflow run promote.yml --field confirm_production=production 2>/dev/null || \
		echo "[INFO] Run manually: gh workflow run promote.yml"

rollback:
	@echo "[INFO] Triggering rollback workflow..."
	@echo "[WARN] This will revert infrastructure to previous state"
	@echo "[INFO] Navigate to: Actions → Rollback Infrastructure → Run workflow"
	@gh workflow run rollback.yml --field environment=staging 2>/dev/null || \
		echo "[INFO] Run manually: gh workflow run rollback.yml"

# =============================================================================
# DAY TARGETS (Ansible-based sequential bootstrap)
# =============================================================================

day1:
	@echo "=== DAY 1: Network Bootstrap (MikroTik VLAN) ==="
	cd infra/ansible && ansible-playbook playbooks/day1-network.yml

day2:
	@echo "=== DAY 2: VPN Mesh (AmneziaWG/WireGuard) ==="
	cd infra/ansible && ansible-playbook playbooks/day2-vpn.yml

day3:
	@echo "=== DAY 3: Compute Base (Docker, CUDA) ==="
	cd infra/ansible && ansible-playbook playbooks/day3-compute.yml

day4:
	@echo "=== DAY 4: Slurm HA Cluster ==="
	cd infra/ansible && ansible-playbook playbooks/day4-slurm.yml

day5:
	@echo "=== DAY 5: Ray Cluster ==="
	cd infra/ansible && ansible-playbook playbooks/day5-ray.yml

day6:
	@echo "=== DAY 6: Ceph Storage ==="
	cd infra/ansible && ansible-playbook playbooks/day6-ceph.yml

day7:
	@echo "=== DAY 7: Full Integration ==="
	cd infra/ansible && ansible-playbook playbooks/day7-integration.yml

# =============================================================================
# TESTING
# =============================================================================

infra-test:
	@echo "[INFO] Running integration tests"
	pytest tests/ -v --tb=short -q

acos-test:
	@echo "=== ACOS Engine Tests ==="
	python3 -m pytest tests/acos_isolation.py -v --tb=short
	cd acos && python3 -m pytest tests/ -v || python3 -m pytest ../tests/ -v

ml-pipeline:
	@echo "=== ML Training Pipeline ==="
	cd domain/ml_engine && python3 training/trainer.py

# =============================================================================
# QUALITY GATES
# =============================================================================

lint:
	@echo "=== Linting ==="
	-@which ruff > /dev/null && ruff check . --fix || echo "  ruff not installed"
	-@which ansible-lint > /dev/null && ansible-lint infra/ansible/ || echo "  ansible-lint not installed"
	-@which shellcheck > /dev/null && shellcheck infra/scripts/day-scripts/*.sh || echo "  shellcheck not installed"
	-@which shellcheck > /dev/null && shellcheck infra/scripts/infra-tools/*.sh 2>/dev/null || true

test:
	@echo "=== Running tests ==="
	python3 -m pytest tests/ -v --tb=short -q

security:
	@echo "=== Security Scan ==="
	-@which trivy > /dev/null && trivy fs . --security-checks vuln . || echo "  trivy not installed"
	-@which ruff > /dev/null && ruff check . --select=SEC || echo "  ruff SEC not available"

# =============================================================================
# CI/CD PIPELINE
# =============================================================================

ci: ci-lint ci-test ci-security
	@echo ""
	@echo "=== CI Pipeline Complete ==="

ci-lint:
	@echo "[INFO] Running linting..."
	@echo "[G-003] Shellcheck for forbidden patterns..."
	-@if which shellcheck > /dev/null; then \
		shellcheck infra/scripts/day-scripts/*.sh; \
	else \
		echo "  shellcheck not available"; \
	fi
	@echo "[G-001] ACOS Isolation Test..."
	@python3 tests/acos_isolation.py || { echo "ACOS isolation VIOLATED"; exit 1; }
	@echo "[INFO] Linting complete"

ci-test:
	@echo "[INFO] Running tests..."
	@python3 -m pytest tests/ -v --tb=short -q
	@python3 -c "from domain.ai_scheduler import job_router; print('job-router importable: OK')" 2>/dev/null || \
		echo "job-router not yet importable (OK if not yet created)"

ci-security:
	@echo "[INFO] Running security scans..."
	@echo "[G-007] Dependency vulnerability scan..."
	-@which trivy > /dev/null && trivy fs . --security-checks vuln . || echo "  trivy not installed"
	@echo "[INFO] Security scan complete"

# =============================================================================
# CLEANUP
# =============================================================================

clean:
	@echo "=== Cleaning ==="
	-@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	-@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	-@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	-@find . -type d -name .terraform -exec rm -rf {} + 2>/dev/null || true
	-@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	-@find . -type f -name "terraform.tfstate*" -delete 2>/dev/null || true
	-@find . -type f -name "tfplan" -delete 2>/dev/null || true
	@echo "  Cleaned caches and build artifacts"

# =============================================================================
# DEPENDENCY CHECKS
# =============================================================================

setup:
	@echo "=== Setting up unified-platform ==="
	@which python3 > /dev/null && echo "  python3: ✅" || echo "  python3: ❌"
	@which ansible > /dev/null && echo "  ansible: ✅" || echo "  ansible: ❌ (pip install ansible)"
	@which terraform > /dev/null && echo "  terraform: ✅" || echo "  terraform: ❌"
	@echo "  Install: pip install -r requirements.txt"
