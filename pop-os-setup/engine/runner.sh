#!/usr/bin/env bash
#===============================================
# engine/runner.sh v9.1 — Production Stage Runner
#===============================================
# Idempotent, state-aware, dry-run compatible.
# Использует lib/runtime.sh для всех путей.
#===============================================

set -euo pipefail

[[ -n "${_RUNNER_SOURCED:-}" ]] && return 0 || export _RUNNER_SOURCED=1

# ─── STAGE REGISTRY ──────────────────────────
# ВСЕ stages в порядке выполнения
STAGE_REGISTRY=(
    "preflight"
    "system_update"
    "nvidia"
    "power"
    "display_manager"
    "dev_tools"
    "docker"
    "zsh"
    "neovim"
    "tailscale"
    "firewall"
    "python"
    "ollama"
    "kubectl"
    "k3s"
    "longhorn"
    "metallb"
    "cilium"
    "rook_ceph"
    "minio"
    "monitoring"
    "backup"
    "hardening"
    "ssh_gpg"
    "cron"
    "notifications"
    "final"
)

# ─── INTERNAL HELPERS ─────────────────────────

_trace() {
    local msg="[$1] ${2:-}"
    echo "[$(date +%H:%M:%S)] ${msg}" >> "${LOG_DIR}/runner.trace"
}

# ════════════════════════════════════════════════
# STAGE EXECUTION ENGINE
# ════════════════════════════════════════════════

run_stage() {
    local stage_name="${1:-}"
    local stage_file

    [[ -z "$stage_name" ]] && { err "run_stage: name required"; return 1; }

    stage_file=$(ls "${STAGEDIR}"/stage*_"${stage_name}".sh 2>/dev/null | head -1)

    if [[ -z "$stage_file" || ! -f "$stage_file" ]]; then
        err "Stage not found: ${stage_name}"
        return 1
    fi

    local state
    state=$(get_state "$stage_name")

    # Skip если уже SUCCESS и не FORCE
    if [[ "$state" == "$STATE_SUCCESS" ]] && [[ "${FORCE:-0}" != "1" ]]; then
        ok "[${stage_name}] — already done, skipping"
        return 0
    fi

    # Skip если SKIPPED
    if [[ "$state" == "$STATE_SKIPPED" ]]; then
        ok "[${stage_name}] — skipped"
        return 0
    fi

    # Помечаем RUNNING
    mark_running "$stage_name"

    step "$stage_name" "?"

    if is_dry_run; then
        ok "[DRY-RUN] Would run: ${stage_name}"
        ok "[DRY-RUN] File: ${stage_file}"
        mark_skipped "$stage_name"
        return 0
    fi

    # Выполняем
    local start=$SECONDS
    if bash "$stage_file"; then
        mark_success "$stage_name"
        ok "[${stage_name}] — done (${SECONDS}s)"
        return 0
    else
        mark_failed "$stage_name"
        err "[${stage_name}] — FAILED (${SECONDS}s)"
        return 1
    fi
}

# ════════════════════════════════════════════════
# PIPELINE RUNNER
# ════════════════════════════════════════════════

run_pipeline() {
    local failed=0
    local skipped=0
    local ran=0

    for stage_name in "${STAGE_REGISTRY[@]}"; do
        # Check skip list
        if [[ " ${SKIP_STAGES:-} " =~ " ${stage_name} " ]]; then
            mark_skipped "$stage_name"
            ok "[${stage_name}] — skipped by SKIP_STAGES"
            skipped=$((skipped + 1))
            continue
        fi

        if run_stage "$stage_name"; then
            ran=$((ran + 1))
        else
            if [[ "${CONTINUE_ON_ERROR:-0}" == "1" ]]; then
                warn "Continuing after failure: ${stage_name}"
                failed=$((failed + 1))
            else
                err "Pipeline aborted at: ${stage_name}"
                err "Resume: SCRIPT_ROOT=${SCRIPT_ROOT} bash ${ENGINEDIR}/runner.sh --resume"
                return 1
            fi
        fi
    done

    ok "Pipeline: ${ran} ran, ${skipped} skipped, ${failed} failed"
    [[ $failed -gt 0 ]] && return 1 || return 0
}

# ════════════════════════════════════════════════
# RESUME — перезапуск failed stages
# ════════════════════════════════════════════════

resume_pipeline() {
    local count=0
    local resumed=0
    local failed=0

    # Собираем все failed stages
    local failed_names=()
    for sf in "${STATE_DIR}"/.*.state; do
        [[ -f "$sf" ]] || continue
        local name
        name=$(basename "$sf" | sed 's/^\.//; s/\.state$//')
        if [[ "$(get_state "$name")" == "$STATE_FAILED" ]]; then
            failed_names+=("$name")
        fi
    done

    count=${#failed_names[@]}
    if [[ $count -eq 0 ]]; then
        ok "No failed stages to resume"
        return 0
    fi

    info "Resuming ${count} failed stage(s): ${failed_names[*]}"
    export FORCE=1

    for name in "${failed_names[@]}"; do
        if run_stage "$name"; then
            resumed=$((resumed + 1))
        else
            failed=$((failed + 1))
        fi
    done

    ok "Resume: ${resumed} recovered, ${failed} still failing"
    [[ $failed -gt 0 ]] && return 1 || return 0
}

# ════════════════════════════════════════════════
# LIST STAGES
# ════════════════════════════════════════════════

list_stages() {
    echo ""
    echo "=== Stage Registry (${#STAGE_REGISTRY[@]} stages) ==="
    local total=0 done=0 fail=0 skip=0 pend=0
    for stage_name in "${STAGE_REGISTRY[@]}"; do
        total=$((total + 1))
        local s
        s=$(get_state "$stage_name")
        local icon="[     ]"
        case "$s" in
            SUCCESS)  icon="[DONE ]"; done=$((done + 1)) ;;
            FAILED)   icon="[FAIL ]"; fail=$((fail + 1)) ;;
            SKIPPED)  icon="[SKIP ]"; skip=$((skip + 1)) ;;
            RUNNING)  icon="[RUN  ]" ;;
            *)        icon="[     ]"; pend=$((pend + 1)) ;;
        esac
        local stage_file
        stage_file=$(ls "${STAGEDIR}"/stage*_"${stage_name}".sh 2>/dev/null | head -1)
        local num="?"
        [[ -n "$stage_file" ]] && num=$(basename "$stage_file" | sed 's/stage//; s/_.*//')
        printf "%s %-2s %s\n" "$icon" "$num" "$stage_name"
    done
    echo ""
    echo "Total: ${total} | Done: ${done} | Fail: ${fail} | Skip: ${skip} | Pending: ${pend}"
}

# ════════════════════════════════════════════════
# DRY-RUN ALL
# ════════════════════════════════════════════════

dry_run_all() {
    export DRY_RUN=1
    info "DRY-RUN mode — no changes will be made"
    run_pipeline
}

# ════════════════════════════════════════════════
# VALIDATE
# ════════════════════════════════════════════════

validate_pipeline() {
    local errors=0
    info "Validating runtime..."
    if ! source "${LIBDIR}/runtime.sh" 2>/dev/null; then
        err "Runtime validation FAILED"
        return 1
    fi

    info "Validating stages..."
    for stage_name in "${STAGE_REGISTRY[@]}"; do
        local sf
        sf=$(ls "${STAGEDIR}"/stage*_"${stage_name}".sh 2>/dev/null | head -1)
        if [[ -z "$sf" ]]; then
            err "MISSING: stage file for '${stage_name}'"
            errors=$((errors + 1))
        elif ! bash -n "$sf" 2>/dev/null; then
            err "SYNTAX ERROR: ${sf}"
            errors=$((errors + 1))
        fi
    done

    if [[ $errors -eq 0 ]]; then
        ok "All ${#STAGE_REGISTRY[@]} stages valid"
        return 0
    else
        err "${errors} validation error(s)"
        return 1
    fi
}

# ─── CLI PARSER ─────────────────────────────────

_usage() {
    cat << 'EOF'
engine/runner.sh v9.1

Usage: sudo ./runner.sh [COMMAND] [OPTIONS]

Commands:
  run           Run all stages (default)
  validate      Validate pipeline
  dry-run       Preview all stages
  list          Show stage registry
  resume        Re-run failed stages
  run <name>    Run single stage

Options:
  --force       Re-run completed stages
  --skip STAGE  Skip named stage(s)
  --continue    Continue on failure
  --dry-run     Preview mode

Examples:
  sudo ./runner.sh                  # full run
  sudo DRY_RUN=1 ./runner.sh         # preview
  sudo ./runner.sh --resume          # resume failures
  sudo ./runner.sh --validate       # check all
  sudo ./runner.sh run docker        # single stage
EOF
}

_main() {
    local cmd="${1:-run}"; shift || true

    case "$cmd" in
        run)        run_pipeline "$@" ;;
        validate)   validate_pipeline ;;
        dry-run)    dry_run_all ;;
        list)       list_stages ;;
        resume)     resume_pipeline ;;
        *)
            # Попытка найти stage по имени
            if [[ -f "${STAGEDIR}"/stage*_"${cmd}".sh ]]; then
                run_stage "$cmd"
            else
                err "Unknown command: $cmd"; _usage; return 1
            fi
            ;;
    esac
}

[[ "${BASH_SOURCE[0]}" != "${0}" ]] || _main "$@"