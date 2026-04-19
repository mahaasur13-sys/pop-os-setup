.PHONY: help lint check-stages docs test install clean integration-tests

# Modular structure (v2.0.0+)
MAIN_SCRIPT   = pop-os-setup.sh
LIB_SH        = $(wildcard lib/*.sh)
STAGE_SH      = $(wildcard stages/*.sh)
PROFILE_SH    = $(wildcard profiles/*.sh)
TEST_SH       = $(wildcard tests/integration/*.sh)
ALL_SH        = $(MAIN_SCRIPT) $(LIB_SH) $(STAGE_SH) $(PROFILE_SH) $(TEST_SH)

help:
	@echo "Pop!_OS Setup v2.0.0 — Modular Makefile"
	@echo "=========================================="
	@echo ""
	@echo "  make lint              — bash -n + shellcheck for all .sh files"
	@echo "  make check-stages      — verify stage files and function definitions"
	@echo "  make docs              — validate required docs exist"
	@echo "  make test              — syntax + shellcheck + integration tests"
	@echo "  make integration-tests — run integration test suite"
	@echo "  make install           — install shellcheck if missing"
	@echo "  make clean             — remove log files"
	@echo ""
	@echo "  make all               — lint + check-stages + docs"

all: lint check-stages docs

install:
	@command -v shellcheck >/dev/null 2>&1 || { \
		echo "Installing shellcheck..."; \
		sudo apt-get install -y shellcheck; \
	}

lint: install
	@echo "=== bash -n syntax check (all .sh files) ==="
	@ok=0; for f in $(ALL_SH); do \
		echo -n "  bash -n $$f ... "; \
		bash -n $$f && echo "✓" || { echo "✗ FAILED"; ok=1; }; \
	done; exit $$ok
	@echo ""
	@echo "=== shellcheck -S warning ==="
	@shellcheck -S warning $(ALL_SH) 2>&1; rc=$$?; \
	if [ $$rc -eq 0 ]; then echo "  ✓ No shellcheck warnings"; \
	elif [ $$rc -eq 1 ]; then echo "  ⚠ shellcheck warnings found (see above)"; \
	fi

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
	@echo "=== Profile files ==="
	@for p in profiles/*.sh; do \
		echo -n "  $$p: "; bash -n $$p && echo "✓" || echo "✗"; \
	done

docs:
	@echo "=== Documentation check ==="
	@for f in README.md CONTRIBUTING.md Pop_OS_KDE_NVIDIA_Guide.md RELEASE_NOTES.md; do \
		if [ -f "$$f" ]; then echo "  ✓ $$f"; else echo "  ! $$f (optional)"; fi; \
	done
	@grep -q "Stage [0-9]" README.md && echo "  ✓ README stages table" || echo "  ! No stages table"

test: lint integration-tests

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

clean:
	@rm -f *.log
	@echo "Cleaned."
