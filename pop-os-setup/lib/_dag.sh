#!/bin/bash
#=======================================================================
# lib/_dag.sh — DAG Execution Engine v4.1
#=======================================================================
# Deterministic orchestrator: MANIFEST-driven, state-aware, rollback-safe
#=======================================================================

[[ -n "${_DAG_SOURCED:-}" ]] && return 0 || _DAG_SOURCED=1

# ─── INTERNAL STATE ──────────────────────────────────────────────────────
declare -A _DAG_NODES
declare -A _DAG_ADJACENCY
declare -A _DAG_REVERSE
declare -A _DAG_DEGREE
declare -A _DAG_VISITED
declare -A _DAG_LOCKED
declare -g _DAG_TOPO_ORDER=""

# ─── LIFECYCLE CONSTANTS ───────────────────────────────────────────────────
readonly LC_INIT="INIT"
readonly LC_CHECK="CHECK"
readonly LC_EXEC="EXEC"
readonly LC_VERIFY="VERIFY"
readonly LC_COMMIT="COMMIT"
readonly LC_ROLLBACK="ROLLBACK"
readonly LC_FAILED="FAILED"
readonly LC_SKIPPED="SKIPPED"
readonly LC_DONE="DONE"

# ─── API: load_manifest ────────────────────────────────────────────────────
load_manifest() {
    local manifest="${1:-${BASEDIR}/MANIFEST.json}"

    if [[ ! -f "$manifest" ]]; then
        _dag_err "MANIFEST not found: $manifest"
        return 1
    fi

    local count=0
    while IFS= read -r line; do
        local id name run_if deps provides version stage_file
        id=$(echo "$line" | base64 -d | jq -r '.id')
        name=$(echo "$line" | base64 -d | jq -r '.name')
        run_if=$(echo "$line" | base64 -d | jq -r '.run_if // "true"')
        deps=$(echo "$line" | base64 -d | jq -r '(.depends // []) | join(" ")')
        provides=$(echo "$line" | base64 -d | jq -r '(.provides // []) | join(" ")')
        version=$(echo "$line" | base64 -d | jq -r '.version')
        stage_file=$(echo "$line" | base64 -d | jq -r '.stage_file // ""')

        _DAG_NODES["$id"]="{\"id\":\"$id\",\"name\":\"$name\",\"run_if\":\"$run_if\",\
\"depends\":\"$deps\",\"provides\":\"$provides\",\
\"version\":\"$version\",\"stage_file\":\"$stage_file\"}"
        _DAG_ADJACENCY["$id"]="$deps"
        _DAG_DEGREE["$id"]=0

        for dep in $deps; do
            _DAG_REVERSE["$dep"]="${_DAG_REVERSE[$dep]:-} $id"
        done

        ((count++))
    done < <(jq -r '.stages[] | @base64' "$manifest" 2>/dev/null)

    _dag_info "MANIFEST loaded: $count stages"
    return 0
}

# ─── API: build_dag ─────────────────────────────────────────────────────────
build_dag() {
    local profile_filter="${1:-}"

    # Compute in-degrees
    for node in "${!_DAG_NODES[@]}"; do
        local run_if deps dep_count=0
        run_if=$(echo "${_DAG_NODES[$node]}" | jq -r '.run_if')
        deps="${_DAG_ADJACENCY[$node]}"

        # Profile filter
        if [[ -n "$profile_filter" ]] && \
           ! _eval_condition "$run_if" "$profile_filter"; then
            _DAG_DEGREE["$node"]=-1  # Mark as skipped
            continue
        fi

        # Count unmet dependencies
        for dep in $deps; do
            local dep_status
            dep_status="$(_state_get "$dep")"
            if [[ "$dep_status" != "$LC_DONE" ]]; then
                ((dep_count++))
            fi
        done
        _DAG_DEGREE["$node"]=$dep_count
    done

    # Kahn's algorithm — collect zero in-degree nodes
    local queue=""
    for node in "${!_DAG_NODES[@]}"; do
        if [[ "${_DAG_DEGREE[$node]}" == "0" ]]; then
            queue="$queue $node"
        fi
    done

    _DAG_TOPO_ORDER=""
    local visited=0 total=${#_DAG_NODES[@]}
    declare -A _DAG_VISITED

    while [[ -n "$queue" ]]; do
        local node="${queue# *}"
        queue="${queue# $node}"

        if [[ "${_DAG_VISITED[$node]}" == "1" ]]; then
            _dag_err "Cycle detected at: $node"
            return 1
        fi
        _DAG_VISITED[$node]=1

        _DAG_TOPO_ORDER="${_DAG_TOPO_ORDER} $node"
        ((visited++))

        local dependents="${_DAG_REVERSE[$node]}"
        for dependent in $dependents; do
            if [[ "${_DAG_DEGREE[$dependent]}" -ge 0 ]]; then
                ((_DAG_DEGREE[$dependent]--))
                if [[ "${_DAG_DEGREE[$dependent]}" == "0" ]]; then
                    queue="$queue $dependent"
                fi
            fi
        done
    done

    if [[ $visited -ne $total ]]; then
        _dag_err "DAG cycle detected (visited $visited/$total)"
        return 1
    fi

    _dag_info "DAG built: $total stages"
    return 0
}

# ─── API: get_topo_order ────────────────────────────────────────────────────
get_topo_order() {
    echo "$_DAG_TOPO_ORDER"
}

# ─── API: run_stage ─────────────────────────────────────────────────────────
run_stage() {
    local stage="$1"
    local node_data="${_DAG_NODES[$stage]:-}"

    if [[ -z "$node_data" ]]; then
        _dag_err "[$stage] Unknown stage"
        return 1
    fi

    local status="$(_state_get "$stage")"

    # Already done
    if [[ "$status" == "$LC_DONE" ]]; then
        _dag_info "[$stage] Already executed — skip"
        return 3
    fi

    # Locked
    if [[ "${_DAG_LOCKED[$stage]}" == "1" ]]; then
        _dag_err "[$stage] Stage locked (concurrent execution?)"
        return 1
    fi
    _DAG_LOCKED[$stage]=1

    # INIT
    local name
    name=$(echo "$node_data" | jq -r '.name')
    _dag_stage "$stage" "INIT" "$name"
    _state_set "$stage" "$LC_INIT" "Initializing"

    # CHECK
    if ! _lc_check "$stage" "$node_data"; then
        _lc_rollback "$stage" "$LC_CHECK"
        return 1
    fi

    # EXECUTE
    if ! _lc_execute "$stage" "$node_data"; then
        _lc_rollback "$stage" "$LC_EXEC"
        return 1
    fi

    # VERIFY
    if ! _lc_verify "$stage" "$node_data"; then
        _lc_rollback "$stage" "$LC_VERIFY"
        return 1
    fi

    # COMMIT
    _state_set "$stage" "$LC_DONE" "Completed $(date -Iseconds)"
    _DAG_LOCKED[$stage]=0
    _dag_ok "[$stage] DONE"
    return 0
}

# ─── LIFECYCLE: CHECK ───────────────────────────────────────────────────────
_lc_check() {
    local stage="$1" node_data="$2"
    _dag_info "[$stage] CHECK"

    local stage_file
    stage_file=$(echo "$node_data" | jq -r '.stage_file // empty')

    # File exists?
    if [[ -n "$stage_file" ]] && [[ ! -f "${BASEDIR}/${stage_file}" ]]; then
        _dag_err "[$stage] File not found: ${BASEDIR}/${stage_file}"
        return 1
    fi

    # Dependencies satisfied?
    local deps
    deps=$(echo "$node_data" | jq -r '(.depends // []) | join(" ")')
    for dep in $deps; do
        local dep_status="$(_state_get "$dep")"
        if [[ "$dep_status" != "$LC_DONE" ]]; then
            _dag_err "[$stage] Dependency not met: $dep (status=$dep_status)"
            return 1
        fi
    done

    _dag_ok "[$stage] CHECK passed"
    return 0
}

# ─── LIFECYCLE: EXECUTE ─────────────────────────────────────────────────────
_lc_execute() {
    local stage="$1" node_data="$2"
    _dag_info "[$stage] EXEC"

    local stage_file
    stage_file=$(echo "$node_data" | jq -r '.stage_file // empty')

    if [[ -z "$stage_file" ]]; then
        _dag_info "[$stage] No-op stage"
        _state_set "$stage" "$LC_DONE" "No-op stage"
        return 0
    fi

    local full_path="${BASEDIR}/${stage_file}"

    (
        set -e
        source "$full_path" 2>&1
    )
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        _dag_err "[$stage] Exit code: $rc"
        return 1
    fi

    return 0
}

# ─── LIFECYCLE: VERIFY ─────────────────────────────────────────────────────
_lc_verify() {
    local stage="$1" node_data="$2"
    _dag_info "[$stage] VERIFY"

    local provides
    provides=$(echo "$node_data" | jq -r '(.provides // []) | join(" ")')

    for feature in $provides; do
        if ! _feature_exists "$feature"; then
            _dag_err "[$stage] VERIFY fail: $feature not found"
            return 1
        fi
    done

    _dag_ok "[$stage] VERIFY passed"
    return 0
}

# ─── LIFECYCLE: ROLLBACK ────────────────────────────────────────────────────
_lc_rollback() {
    local stage="$1" phase="$2"
    _dag_err "[$stage] ROLLBACK — $phase"

    _state_set "$stage" "$LC_ROLLBACK" "Failed at $phase"
    _DAG_LOCKED[$stage]=0
}

# ─── INTERNAL ──────────────────────────────────────────────────────────────
_eval_condition() {
    local run_if="$1" profile="$2"
    [[ "$run_if" == "true" ]] && return 0
    [[ "$run_if" == "false" ]] && return 1

    if [[ "$run_if" =~ ^ENABLE_[A-Z_]+= ]]; then
        local var="${run_if%%=*}" val="${run_if#*=}"
        [[ "${!var}" == "$val" ]] && return 0
        return 1
    fi

    if [[ "$run_if" =~ ^profile==(.+) ]]; then
        [[ "$profile" == "${BASH_REMATCH[1]}" ]] && return 0
        return 1
    fi

    return 0
}

_feature_exists() {
    local feature="$1"
    case "$feature" in
        docker)         command -v docker             &>/dev/null ;;
        nvim|neovim)    command -v nvim               &>/dev/null ;;
        zsh)            command -v zsh                &>/dev/null ;;
        kubectl)        command -v kubectl            &>/dev/null ;;
        k3s)            command -v k3s                &>/dev/null ;;
        tailscale)      command -v tailscale          &>/dev/null ;;
        python3|python) command -v python3            &>/dev/null ;;
        docker-compose) command -v docker-compose     &>/dev/null ;;
        ufw)            command -v ufw                &>/dev/null ;;
        fail2ban)       command -v fail2ban           &>/dev/null ;;
        *)              _dag_warn "Unknown feature: $feature"; return 1 ;;
    esac
}

# ─── LOGGING (namespace isolated) ─────────────────────────────────────────
_dag_info()  { echo "[INFO]  $(date '+%H:%M:%S') $*" >&2; }
_dag_ok()    { echo "[OK]    $(date '+%H:%M:%S') $*" >&2; }
_dag_warn()  { echo "[WARN]  $(date '+%H:%M:%S') $*" >&2; }
_dag_err()   { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }
_dag_stage() { echo "[STAGE] $(date '+%H:%M:%S') =$2= $3" >&2; }

# ─── INLINE STATE ACCESSORS (no source dependency) ──────────────────────────
# These are provided by _state.sh — we call them if available
_state_get() {
    local stage="$1"
    # Delegate to state layer if loaded
    if declare -f get_state >/dev/null 2>&1; then
        get_state "$stage"
    else
        echo ""
    fi
}

_state_set() {
    local stage="$1" status="$2" msg="$3"
    if declare -f set_state >/dev/null 2>&1; then
        set_state "$stage" "$status" "$msg"
    fi
}
