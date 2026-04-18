.PHONY: help lint lint-shells check-stages test docs install clean

SHELL_SCRIPTS = $(wildcard *.sh)
MAIN_SCRIPT    = pop-os-setup-v5.sh

help:
	@echo "Pop!_OS Setup — Makefile"
	@echo "========================"
	@echo ""
	@echo "  make lint          — shellcheck + bash -n for all .sh files"
	@echo "  make check-stages  — verify stage functions exist in main script"
	@echo "  make docs          — validate required docs exist"
	@echo "  make test          — dry-run syntax check (bash -n)"
	@echo "  make install       — install shellcheck if missing"
	@echo "  make clean         — remove log files"
	@echo ""
	@echo "  make all           — lint + check-stages + docs"

all: lint check-stages docs

install:
	@command -v shellcheck >/dev/null 2>&1 || { \
		echo "Installing shellcheck..."; \
		sudo apt-get install -y shellcheck; \
	}

lint: install
	@echo "=== Shell script lint ==="
	@for f in $(SHELL_SCRIPTS); do \
		echo -n "  bash -n $$f ... "; \
		bash -n $$f && echo "✓" || { echo "✗ FAILED"; exit 1; }; \
	done
	@echo ""
	@echo "=== shellcheck (warnings+) ==="
	@shellcheck -x -S warning $(SHELL_SCRIPTS) 2>&1 || true

check-stages:
	@echo "=== Stage function check ==="
	@echo "Functions defined: $$(grep -cE '^[a-z_][a-z_0-9]*\(' $(MAIN_SCRIPT))"
	@echo "Stage comments:    $$(grep -cE '^[[:space:]]*# Stage [0-9]' $(MAIN_SCRIPT))"
	@echo ""
	@echo "Stage functions detected:"
	@grep -E '^[a-z_][a-z_0-9]*\(' $(MAIN_SCRIPT) | grep -vE '^log\(|^check_|^(ask_|gpu_|run_|main)' | head -20
	@echo ""
	@echo "Stage comment blocks:"
	@grep -E '^[[:space:]]*# Stage [0-9]' $(MAIN_SCRIPT) || echo "  (none — stages defined as functions, not comments)"

docs:
	@echo "=== Documentation check ==="
	@for f in README.md CONTRIBUTING.md Pop_OS_KDE_NVIDIA_Guide.md; do \
		if [ -f "$$f" ]; then echo "  ✓ $$f"; else echo "  ✗ $$f MISSING"; exit 1; fi; \
	done
	@grep -q "Stage [0-9]" README.md && echo "  ✓ README stages table" || { echo "  ✗ No stages table"; exit 1; }

test: lint

clean:
	@rm -f *.log
	@echo "Cleaned."