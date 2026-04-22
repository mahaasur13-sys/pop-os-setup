#!/bin/bash
#===============================================
# engine/runner.sh — v9.0 Execution Engine
# Stage runner with idempotency + resume + dry-run
#===============================================

set -euo pipefail

# Source runtime core
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "${SCRIPT_DIR}/lib/runtime.sh"

# ─── STAGE REGISTRY ──────────────────────────────────────────────────────────
# Ordered list — edit this to change execution order
STAGE_REGISTRY=(
    stage1_preflight
    stage2_update
    stage3_nvidia
    stage4_dev_tools
    stage5_zsh
    stage6_kde
    stage7_docker
    stage8_python_ai
    stage9_cuda
    stage10_hardening
    stage11_ssh
    stage12_optimization
    stage13_tailscale
    stage14_k8s
    stage15_slurm
    stage16_power
    stage17_docker_compose
    stage18_dotfiles
    stage19_monitoring
    stage20_gpu_monitoring
    stage21_cron
    stage22_neovim
    stage23_notifications
    stage24_ssh_gpg
    stage25_backup
    stage26_final
)

# ─── RUN SINGLE STAGE ────────────────────────────────────────────────────────
run_stage() {
    local stage_name="$1"
    local stage_file
    stage_file=$(resolve_stage "$stage_name") || return 1

    # Idempotency — skip if already done
    if is_done "$stage_name"; then
        echo "[SKIP] ${stage_name} — already completed"
        return 0
    fi

    # Mark running
    echo "[RUN]  ${stage_name}"
    echo "       ${stage_file}"

    # Execute
    local start_time=$SECONDS
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        echo "[DRY]  Would execute: bash ${stage_file}"
    else
        if bash "$stage_file"; then
            mark_done "$stage_name"
            local elapsed=$((SECONDS - start_time))
            echo "[OK]   ${stage_name} (${elapsed}s)"
        else
            mark_failed "$stage_name"
            echo "[FAIL] ${stage_name} — see log above"
            return 1
        fi
    fi
}

# ─── RUN PIPELINE ────────────────────────────────────────────────────────────
run_pipeline() {
    local failed=0
    local skipped=0

    # Preflight validation
    if [[ "${DRY_RUN:-0}" != "1" ]]; then
        echo "=== Validating pipeline ==="
        if ! validate_pipeline; then
            echo "PIPELINE VALIDATION FAILED — fix errors before running"
            return 1
        fi
        echo "=== Validation passed (${#STAGE_REGISTRY[@]} stages) ==="
        echo ""
    fi

    for stage_name in "${STAGE_REGISTRY[@]}"; do
        if ! run_stage "$stage_name"; then
            if [[ "${CONTINUE_ON_ERROR:-0}" == "1" ]]; then
                echo "[WARN] Continuing despite failure: ${stage_name}"
                failed=$((failed + 1))
            else
                echo ""
                echo "=== PIPELINE FAILED at: ${stage_name} ==="
                echo "=== Resume with: sudo ./pop-os-setup.sh --resume ==="
                return 1
            fi
        fi
    done

    echo ""
    if [[ $failed -gt 0 ]]; then
        echo "=== PIPELINE COMPLETED with ${failed} failures ==="
    else
        echo "=== PIPELINE COMPLETED SUCCESSFULLY ==="
    fi
}

# ─── RESUME ─────────────────────────────────────────────────────────────────
resume_pipeline() {
    echo "=== RESUME MODE — re-running failed stages ==="
    local failed_stages=()
    for f in "${STATE_DIR}"/*.failed 2>/dev/null; do
        [[ -f "$f" ]] || continue
        local name
        name=$(basename "$f" .failed)
        failed_stages+=("$name")
    done

    if [[ ${#failed_stages[@]} -eq 0 ]]; then
        echo "No failed stages found — running full pipeline"
        run_pipeline
    else
        echo "Found ${#failed_stages[@]} failed stage(s): ${failed_stages[*]}"
        for stage_name in "${failed_stages[@]}"; do
            rm -f "${STATE_DIR}/${stage_name}.failed"
            run_stage "$stage_name" || true
        done
    fi
}

# ─── LIST STAGES ────────────────────────────────────────────────────────────
list_stages() {
    echo "=== Stage Registry (${#STAGE_REGISTRY[@]} stages) ==="
    for stage_name in "${STAGE_REGISTRY[@]}"; do
        local file
        file=$(resolve_stage "$stage_name" 2>/dev/null || echo "NOT FOUND")
        local status="[    ]"
        if is_done "$stage_name"; then
            status="[DONE]"
        elif [[ -f "${STATE_DIR}/${stage_name}.failed" ]]; then
            status="[FAIL]"
        fi
        echo "${status} ${stage_name}"
    done
}

export -f run_stage run_pipeline resume_pipeline list_stages
