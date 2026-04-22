#!/bin/bash
#==================================================
# patch-stages.sh — Apply runtime.sh standard to all stages
# Idempotent: safe to run multiple times
#==================================================

set -euo pipefail
cd "$(dirname "$0")/.."
SCRIPT_ROOT=$(pwd)
STAGEDIR="${SCRIPT_ROOT}/stages"
PATCH_LOG="/tmp/patch-stages.log"
echo "=== patch-stages.sh started at $(date) ===" > "$PATCH_LOG"

count=0
for f in stages/stage*.sh; do
    [[ -f "$f" ]] || continue
    echo -n "Patching: $f ... " | tee -a "$PATCH_LOG"

    local fname
    fname=$(basename "$f" .sh)

    local content
    content=$(cat "$f")

    # Skip if already has runtime.sh
    if echo "$content" | grep -q 'source.*lib/runtime.sh'; then
        echo "SKIP (already has runtime.sh)" | tee -a "$PATCH_LOG"
        continue
    fi

    # Build new header
    local header="#!/bin/bash
#==================================================
# $(basename "$f") — patched by patch-stages.sh v8.0
#==================================================

# Safety + idempotency guard
[[ \"\${_STAGE_SOURCED:-}\" == \"yes\" ]] && return 0

# Runtime core (auto-resolves paths)
source \"\$(dirname \"\${BASH_SOURCE[0]}\")/../lib/runtime.sh\"
stage_guard || return 0

# Safety
set -euo pipefail
"

    # Strip old headers, source lines, hardcoded paths
    local stripped
    stripped=$(echo "$content" | sed '/^#!/d' | sed '/^source.*logging\.sh/d' | sed '/^source.*utils\.sh/d' | sed '/^source.*installer\.sh/d' | sed '/^source.*profiles\.sh/d' | sed '/^source.*bootstrap\.sh/d' | sed '/^SCRIPT_DIR=/d' | sed '/^LIBDIR=/d' | sed '/^STAGEDIR=/d' | sed '/^_STAGE_SOURCED/d')

    # Extract function body (everything after first function definition)
    local func_body
    func_body=$(echo "$stripped" | sed '1,/^[[:space:]]*stage_/d')

    # Build final content
    local new_content="${header}
# ─── $(basename "$f") ────────────────────────────────
${func_body}
"

    echo "$new_content" > "$f"
    chmod +x "$f"
    local lines
    lines=$(echo "$new_content" | wc -l)
    echo "PATCHED (${lines} lines)" | tee -a "$PATCH_LOG"
    count=$((count + 1))
done

echo ""
echo "=== Patched $count stage files ==="
echo "Log: $PATCH_LOG"
