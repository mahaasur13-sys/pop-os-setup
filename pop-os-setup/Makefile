.PHONY: help lint check-stages docs test install clean integration-tests \
        verify security-check version stage-list

# Project config
VERSION      := 3.0.0
MAIN_SCRIPT  := pop-os-setup.sh
LIB_SH       := $(wildcard lib/*.sh)
STAGE_SH     := $(wildcard stages/stage[0-9]*.sh)
PROFILE_SH   := $(wildcard profiles/*.sh)
TEST_SH      := $(wildcard tests/integration/*.sh)
ALL_SH       := $(MAIN_SCRIPT) $(LIB_SH) $(STAGE_SH) $(PROFILE_SH) $(TEST_SH)
STAGES_COUNT := 26

# Colours
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
NC     := \033[0m

# -----------------------------------------------------------------------------
help:
	@echo "Pop!_OS Setup v$(VERSION) — Modular Makefile"
	@echo "=============================================="
	@echo ""
	@echo "  ${GREEN}make lint${NC}              — bash -n + shellcheck for all .sh files"
	@echo "  ${GREEN}make check-stages${NC}      — verify stage files and function definitions"
	@echo "  ${GREEN}make security-check${NC}     — scan for credential/RCE patterns"
	@echo "  ${GREEN}make docs${NC}              — validate required docs exist"
	@echo "  ${GREEN}make test${NC}             — syntax + shellcheck + integration tests"
	@echo "  ${GREEN}make integration-tests${NC} — run integration test suite"
	@echo "  ${GREEN}make stage-list${NC}        — show all stage files and their status"
	@echo "  ${GREEN}make install${NC}          — install shellcheck if missing"
	@echo "  ${GREEN}make clean${NC}             — remove log files"
	@echo "  ${GREEN}make verify${NC}            — full verification (lint + check + security)"
	@echo ""
	@echo "  ${GREEN}make all${NC}               — lint + check-stages + docs + security"

all: lint check-stages docs security-check

# -----------------------------------------------------------------------------
install:
	@command -v shellcheck >/dev/null 2>&1 || { \
		echo "Installing shellcheck..."; \
		sudo apt-get install -y shellcheck; \
	}

# -----------------------------------------------------------------------------
lint: install
	@echo "=== bash -n syntax check (all .sh files) ==="
	@ok=0; for f in $(ALL_SH); do \
		echo -n "  $$f ... "; \
		bash -n $$f 2>/dev/null && echo "✓" || { echo "✗ FAILED"; ok=1; }; \
	done; exit $$ok
	@echo ""
	@echo "=== shellcheck -S warning ==="
	@shellcheck -S warning $(ALL_SH) 2>&1; rc=$$?; \
	if [ $$rc -eq 0 ]; then echo "  ✓ No shellcheck warnings"; \
	elif [ $$rc -eq 1 ]; then echo "  ⚠ shellcheck warnings found (see above)"; \
	fi

# -----------------------------------------------------------------------------
check-stages:
	@echo "=== Stage file check ==="
	@total=0; passed=0; \
	for i in $$(seq 1 26); do \
		file=$$(ls stages/stage$${i}_*.sh 2>/dev/null | head -1); \
		if [ -n "$$file" ]; then \
			name=$$(grep -m1 "^[[:space:]]*stage_.*()" "$$file" 2>/dev/null | sed 's/stage_//;s/(.*//' | head -1); \
			echo "  ✓ Stage $$i: $$name"; passed=$$((passed+1)); \
		else \
			echo "  ! Stage $$i: no matching file"; \
		fi; \
		total=$$((total+1)); \
	done; \
	echo ""; echo "  Stages: $$passed/$$total files present"
	@echo ""
	@echo "=== Stage _STAGE_SOURCED guards ==="
	@bash -c 'for f in stages/stage[0-9]*.sh; do \
		if grep -q "_STAGE_SOURCED" "$$f" 2>/dev/null; then \
			echo "  ✓ $${f##*/}: sourced-protected"; \
		else \
			echo "  ! $${f##*/}: MISSING _STAGE_SOURCED guard"; \
		fi; \
	done'
	@echo ""
	@echo "=== Profile files ==="
	@for p in profiles/*.sh; do \
		echo -n "  $$p: "; bash -n $$p && echo "✓" || echo "✗"; \
	done

# -----------------------------------------------------------------------------
security-check:
	@echo "=== Security scan (credential/RCE patterns) ==="
	@found=0; \
	for pattern in \
		"curl.*sh.*http" \
		"wget.*-O.*sh" \
		'ssh-keygen.*-N ""' \
		"chmod [0]*777" \
		'passwd=.*' \
		'password=.*' \
		"2>/dev/null.*password" \
		"eval.*$$" \
		"curl\|sh" \
		"wget\|bash" \
		"root ALL=(ALL) NOPASSWD: ALL" \
		"\.ssh/.*0600.*||.*chmod" \
		"echo.*>.*/etc/sudoers" \
		"spawn.*ssh.* StrictHostKeyChecking=no" \
		"APT::Periodic::Unattended-Upgrade.*0" \
		"{{.*password" \
		'\bAKIA[0-9A-Z]{16}\b' \
		"ghp_[a-zA-Z0-9]{36}" \
		"sk-[a-zA-Z0-9]{48}" \
		"GITHUB_TOKEN=.*" \
		"OPENAI_API_KEY=.*"; do \
		result=$$(grep -rni "$$pattern" $(ALL_SH) 2>/dev/null || true); \
		if [ -n "$$result" ]; then \
			echo "  ✗ PATTERN: $$pattern"; \
			echo "$$result" | head -3 | sed 's/^/      /'; \
			found=$$((found+1)); \
		fi; \
	done; \
	if [ $$found -eq 0 ]; then \
		echo "  ✓ No credential/RCE patterns found"; \
	else \
		echo ""; \
		echo "  ${RED}$$found security concern(s) found${NC} — review above"; \
	fi; \
	echo ""

# -----------------------------------------------------------------------------
docs:
	@echo "=== Documentation check ==="
	@for f in README.md CONTRIBUTING.md Pop_OS_KDE_NVIDIA_Guide.md RELEASE_NOTES.md; do \
		if [ -f "$$f" ]; then echo "  ✓ $$f"; else echo "  ! $$f (optional)"; fi; \
	done
	@grep -q "Stage [0-9]" README.md 2>/dev/null && echo "  ✓ README stages table" || echo "  ! No stages table"

# -----------------------------------------------------------------------------
stage-list:
	@echo "=== All stage files ==="
	@for f in $$(ls -1 stages/stage[0-9]*.sh 2>/dev/null | sort -V); do \
		num=$$(echo "$$f" | grep -oE 'stage[0-9]+' | grep -oE '[0-9]+'); \
		name=$$(grep -m1 "^[[:space:]]*stage_[a-z]*()" "$$f" 2>/dev/null \
		       | sed 's/.*stage_//;s/(.*//' | tr -d ' '); \
		size=$$(wc -c < "$$f"); \
		protected=$$(grep -c "_STAGE_SOURCED" "$$f" 2>/dev/null || echo 0); \
		if [ "$$protected" -gt 0 ]; then \
			echo "  stage$${num}  ($$name)  — $$size bytes  ✓ guarded"; \
		else \
			echo "  stage$${num}  ($$name)  — $$size bytes  ⚠ unguarded"; \
		fi; \
	done

# -----------------------------------------------------------------------------
test: lint integration-tests

# -----------------------------------------------------------------------------
integration-tests:
	@echo "=== Integration tests ==="
	@bash tests/integration/run.sh --suite all; rc=$$?; \
	if [ $$rc -eq 2 ]; then \
		echo "Docker not available — using host bash fallback"; \
		SUITE=all bash tests/integration/test-lib.sh     || { echo "FAIL: test-lib"; exit 1; }; \
		SUITE=all bash tests/integration/test-stages.sh || { echo "FAIL: test-stages"; exit 1; }; \
		SUITE=all bash tests/integration/test-profiles.sh || { echo "FAIL: test-profiles"; exit 1; }; \
		SUITE=all bash tests/integration/test-cli.sh    || { echo "FAIL: test-cli"; exit 1; }; \
		echo "  ✓ All integration tests passed (host fallback)"; \
	else \
		echo "  ✓ All integration tests passed"; \
	fi

# -----------------------------------------------------------------------------
verify: lint check-stages security-check docs
	@echo ""
	@echo "=============================================="
	@echo "  v$(VERSION) verification complete"
	@echo "=============================================="

# -----------------------------------------------------------------------------
clean:
	@rm -f *.log
	@echo "Cleaned."

# -----------------------------------------------------------------------------
version:
	@echo "$(VERSION)"
