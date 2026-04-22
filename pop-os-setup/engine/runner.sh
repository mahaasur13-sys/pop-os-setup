#!/usr/bin/env bash
#===============================================
# engine/runner.sh v9.2 — Production Pipeline Runner
#===============================================
# 26-stage pipeline with fault isolation, checkpoint,
# parallel-safety, rollback, and structured observability.
#===============================================

[[ -n "${_RUNNER_SOURCED:-}" ]] && return 0 || _RUNNER_SOURCED=1

# ═══════════════════════════════════════════════════════════
# STAGE REGISTRY — Explicit order
# ═══════════════════════════════════════════════════════════

declare -a STAGE_REGISTRY=(
    "stage01_preflight"
    "stage02_system_update"
    "stage03_nvidia"
    "stage04_power"
    "stage05_display_manager"
    "stage06_dev_tools"
    "stage07_docker"
    "stage08_zsh"
    "stage09_neovim"
    "stage10_hardening"
    "stage11_firewall"
    "stage12_python"
    "stage13_tailscale"
    "stage14_k8s"
    "stage15_monitoring"
    "stage16_storage"
    "stage17_docker_compose"
    "stage18_backup"
    "stage19_notifications"
    "stage20_cron"
    "stage21_final"
)

# ═══════════════════════════════════════════════════════════
# PIPELINE EXECUTION
# ═══════════════════════════════════════════════════════════

run_stage() {
    local stage="$1"
    local stage_file

    stage_file=$(resolve_stage "$stage" 2>/dev/null)
    if [[ ! -f "$stage_file" ]]; then
        err "[$stage] file not found at $STAGEDIR"
        return 1
    fi

    # Skip if already done
    if is_done "$stage"; then
        ok "[$stage] already done — skipping"
        return 0
    fi

    # Snapshot before execution
    snapshot_stage "$stage"

    # Check dependency
    validate_dependency "$stage" || {
        warn "[$stage] dependency not met — skipping"
        mark_stage "$stage" "SKIPPED"
        return 0
    }

    # Execute with fault isolation
    CURRENT_STAGE="$stage"
    install_trap

    local start end duration
    start=$(date +%s%3N)

    if is_dry_run; then
        log "[DRY-RUN] Would run: $stage"
        mark_stage "$stage" "SUCCESS"
        _emit_event "$stage" "DRY-RUN" "0"
        restore_trap
        return 0
    fi

    # Source stage (triggers stage_* function)
    if ! source "$stage_file" 2>&1 | tee -a "${LOG_DIR}/${stage}.log"; then
        end=$(date +%s%3N)
        duration=$((end - start))
        err "[$stage] execution failed"
        mark_stage "$stage" "FAILED"
        _emit_event "$stage" "FAILED" "$duration"
        restore_trap

        # Recovery policy
        case "$RECOVERY_POLICY" in
            skip)
                warn "Skipping $stage due to RECOVERY_POLICY=skip"
                mark_stage "$stage" "SKIPPED"
                return 0
                ;;
            retry)
                warn "Retry policy not yet implemented — abort"
                ;;
            abort|*)
                set_safe_mode
                return 1
                ;;
        esac
        return 1
    fi

    # Call stage function if defined
    local stage_func="stage_${stage#stage}"
    if declare -f "$stage_func" >/dev/null 2>&1; then
        if "$stage_func" 2>&1 | tee -a "${LOG_DIR}/${stage}.log"; then
            end=$(date +%s%3N)
            duration=$((end - start))
            mark_stage "$stage" "SUCCESS"
            _emit_event "$stage" "SUCCESS" "$duration"
        else
            end=$(date +%s%3N)
            duration=$((end - start))
            mark_stage "$stage" "FAILED"
            _emit_event "$stage" "FAILED" "$duration"
            restore_trap

            if [[ "$RECOVERY_POLICY" == "skip" ]]; then
                mark_stage "$stage" "SKIPPED"
                return 0
            fi
            set_safe_mode
            return 1
        fi
    else
        # No function — just source, consider done
        mark_stage "$stage" "SUCCESS"
        _emit_event "$stage" "SUCCESS" "$(( $(date +%s%3N) - start ))"
    fi

    restore_trap
    return 0
}

run_pipeline() {
    local failed=0
    local skipped=0
    local total=${#STAGE_REGISTRY[@]}

    log "═══ PIPELINE START ($total stages) ═══"

    # Acquire lock
    if ! acquire_lock; then
        err "Cannot acquire lock — another run in progress"
        return 1
    fi

    # Validate before run
    if ! validate_all; then
        err "Pipeline validation failed"
        release_lock
        return 1
    fi

    local i=1
    for stage in "${STAGE_REGISTRY[@]}"; do
        log "[$i/$total] Stage: $stage"
        if ! run_stage "$stage"; then
            err "Pipeline aborted at $stage"
            failed=1
            break
        fi
        ((i++)) || true
    done

    release_lock

    if ((failed)); then
        log "═══ PIPELINE FAILED ═══"
        log "Run: --resume to recover from last success"
        return 1
    else
        log "═══ PIPELINE COMPLETE ═══"
        return 0
    fi
}

resume_pipeline() {
    local failed_stages=()

    log "═══ RESUME MODE ═══"

    for state_file in "${STATE_DIR}"/*.state; do
        [[ -f "$state_file" ]] || continue
        local stage state
        stage=$(basename "$state_file" .state)
        state=$(cat "$state_file")

        if [[ "$state" == "FAILED" ]]; then
            failed_stages+=("$stage")
        fi
    done

    if (( ${#failed_stages[@]} == 0 )); then
        ok "No failed stages — pipeline complete"
        return 0
    fi

    log "Will retry: ${failed_stages[*]}"

    for stage in "${failed_stages[@]}"; do
        # Restore checkpoint if exists
        if [[ -f "${CHECKPOINT_DIR}/${stage}.checkpoint" ]]; then
            restore_checkpoint "$stage"
        fi

        if run_stage "$stage"; then
            ok "[$stage] recovered"
        else
            err "[$stage] recovery failed"
            return 1
        fi
    done

    ok "Resume complete"
    return 0
}

# ═══════════════════════════════════════════════════════════
# DRY RUN / VALIDATE
# ═══════════════════════════════════════════════════════════

dry_run_all() {
    log "═══ DRY-RUN PREVIEW ($ENV_COUNT stages) ═══"
    export DRY_RUN=1

    local i=1
    for stage in "${STAGE_REGISTRY[@]}"; do
        local file
        file=$(get_stage_file "${i}" 2>/dev/null || echo "not found")
        if [[ -f "$file" ]]; then
            ok "[DRY-RUN] $i: $stage → $(basename "$file")"
        else
            warn "[DRY-RUN] $i: $stage → FILE NOT FOUND"
        fi
        ((i++)) || true
    done

    log "DRY-RUN complete — no changes made"
    return 0
}

validate_pipeline() {
    log "═══ PIPELINE VALIDATION ═══"

    local errors=0

    # Lock check
    if [[ -f "$LOCK_FILE" ]]; then
        warn "Lock file exists: $LOCK_FILE"
    else
        ok "Lock: clean"
    fi

    # Directory checks
    for dir in "$STAGEDIR" "$STATE_DIR" "$LOG_DIR" "$CHECKPOINT_DIR"; do
        if [[ -d "$dir" ]]; then
            ok "Dir OK: $dir"
        else
            err "Missing dir: $dir"
            ((errors++))
        fi
    done

    # Stage count
    local stage_count
    stage_count=$(find "$STAGEDIR" -maxdepth 1 -name "stage*.sh" 2>/dev/null | wc -l)
    ok "Stages found: $stage_count/${#STAGE_REGISTRY[@]}"

    # Syntax check
    local syntax_errors=0
    for f in "${STAGEDIR}"/*.sh; do
        [[ -f "$f" ]] || continue
        if ! bash -n "$f" 2>/dev/null; then
            err "SYNTAX ERROR: $(basename "$f")"
            ((syntax_errors++))
        fi
    done

    if ((syntax_errors > 0)); then
        err "$syntax_errors syntax error(s)"
        ((errors += syntax_errors))
    else
        ok "All stage syntax: valid"
    fi

    # DAG check
    if ! validate_dag; then
        ((errors++))
    fi

    if ((errors == 0)); then
        ok "Pipeline validation: PASSED"
    else
        err "Pipeline validation: $errors error(s)"
    fi

    return $((errors > 0 ? 1 : 0))
}

list_stages() {
    local i=1
    echo ""
    echo "Stage Registry (${#STAGE_REGISTRY[@]} stages):"
    echo "────────────────────────────────────────────"

    for stage in "${STAGE_REGISTRY[@]}"; do
        local file state
        file=$(get_stage_file "$i" 2>/dev/null || echo "")
        state=$(get_stage_state "$stage")
        local state_icon
        case "$state" in
            SUCCESS) state_icon="✅" ;;
            FAILED)  state_icon="❌" ;;
            SKIPPED) state_icon="⏭" ;;
            RUNNING) state_icon="🔄" ;;
            PENDING) state_icon="⏳" ;;
            RETRYING) state_icon="🔁" ;;
            *)       state_icon="──" ;;
        esac

        if [[ -n "$file" && -f "$file" ]]; then
            printf "%s %2d. %-25s %s\n" "$state_icon" "$i" "$stage" "$state"
        else
            printf "⚠️ %2d. %-25s %s\n" "$i" "$stage" "NOT FOUND"
        fi
        ((i++)) || true
    done
    echo "────────────────────────────────────────────"
    echo "Run log: $RUN_LOG"
    echo ""
}

# ═══════════════════════════════════════════════════════════
# ROLLBACK
# ═══════════════════════════════════════════════════════════

rollback_last() {
    local last_stage="$1"
    warn "Rolling back: $last_stage"
    rollback_stage "$last_stage"
    mark_stage "$last_stage" "PENDING"
}

rollback_all() {
    warn "Full rollback requested"
    rollback_pipeline
    rm -f "${STATE_DIR}"/*.state 2>/dev/null || true
    ok "All state cleared"
}