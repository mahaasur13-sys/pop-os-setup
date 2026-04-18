# Integration Tests — pop-os-setup

## Philosophy

Integration tests validate that the script's building blocks — library functions, stage files, profiles, and CLI parsing — work correctly when sourced and invoked together. Tests run in an isolated container environment (Ubuntu 24.04 as base) with the repository mounted, simulating real execution without requiring actual hardware (NVIDIA GPU, real network, etc.).

**Key principles:**
- **No real side-effects** — tests mock or skip actual system-modifying commands
- **Idempotent** — safe to run multiple times
- **CI-ready** — no interactive prompts, clear pass/fail exit codes
- **Fast** — no container image pulls during test execution (Docker must already be available)

## Test Matrix

| Test File | What it Validates | Environment |
|-----------|-------------------|-------------|
| `test-lib.sh` | Library functions from `lib/` load and execute correctly | Isolated bash |
| `test-stages.sh` | Each stage file is syntactically valid and can be sourced | Isolated bash |
| `test-profiles.sh` | Each profile sets the correct `ENABLE_*` variables | Isolated bash |
| `test-cli.sh` | CLI argument parsing (`--profile`, `--dry-run`, `--help`, etc.) | Isolated bash |

## Running Tests

```bash
# Run all tests
make integration-tests

# Run individual test
bash tests/integration/test-lib.sh
bash tests/integration/test-stages.sh
bash tests/integration/test-profiles.sh
bash tests/integration/test-cli.sh

# With Docker (full container isolation)
bash tests/integration/run.sh --suite all
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All tests passed |
| `1` | One or more tests failed |
| `2` | Test infrastructure missing (Docker not available) |