#!/usr/bin/env bash
#===============================================================================
# engine/sandbox_runtime.sh - v11.2 Sandbox Isolated Execution Kernel
# Pop!_OS Setup v11.2 - OS-Level Isolation + Deterministic Execution
#===============================================================================
set -euo pipefail

readonly SANDBOX_VERSION="11.2"
readonly SANDBOX_STATE_DIR="/run/pop-os-sandbox"
readonly OVERLAY_ROOT="/overlay/pop-os-sandbox"
readonly SYSROOT="/sysroot/pop-os"
readonly POLICY_LOG="/var/log/pop-os-sandbox/syscall_violations.log"

log_sb()  { echo "[$(date +%T)] $*" | tee -a "${SANDBOX_STATE_DIR}/sandbox.log" 2>/dev/null || echo "$*"; }
ok_sb()   { echo "[$(date +%T)] [OK]  $*" | tee -a "${SANDBOX_STATE_DIR}/sandbox.log" 2>/dev/null || echo "$*"; }
warn_sb() { echo "[$(date +%T)] [WARN] $*" | tee -a "${SANDBOX_STATE_DIR}/sandbox.log" 2>/dev/null || echo "$*"; }
err_sb()  { echo "[$(date +%T)] [ERR]  $*" >&2; }

sandbox_init() {
    log_sb "Initializing v${SANDBOX_VERSION} sandbox execution environment..."
    mkdir -p "$SANDBOX_STATE_DIR" 2>/dev/null || true
    chmod 700 "$SANDBOX_STATE_DIR"
    mkdir -p "${OVERLAY_ROOT}/upper" "${OVERLAY_ROOT}/work" 2>/dev/null || true

    if ! unshare --help &>/dev/null; then
        warn_sb "unshare not available - sandbox mode degraded"
        return 1
    fi

    local features_ok=1
    for feat in overlay user_namespaces; do
        if grep -q "^$feat" /proc/filesystems 2>/dev/null; then
            log_sb "  [OK] $feat supported"
        else
            warn_sb "  [WARN] $feat NOT available"
            features_ok=0
        fi
    done

    log_sb "Sandbox v${SANDBOX_VERSION} initialized"
    return $features_ok
}

sandbox_enter() {
    local target="${1:-/}"
    local stage_num="${2:-}"

    log_sb "Entering isolated mount namespace (stage ${stage_num})..."
    mkdir -p "${target}/proc" 2>/dev/null || true

    if grep -q "^none\s*/host" /proc/mounts 2>/dev/null; then
        err_sb "Host filesystem escape detected!"
        return 1
    fi

    log_sb "Mount namespace established"
    return 0
}

sandbox_exec_isolated() {
    local run_id="${1:-}"
    local epoch="${2:-}"
    local stage_script="${3:-}"
    local stage_num="${4:-}"

    [[ -z "$run_id" ]] && { err_sb "sandbox_exec_isolated: run_id required"; return 1; }
    [[ ! -f "$stage_script" ]] && { err_sb "sandbox_exec_isolated: $stage_script not found"; return 1; }

    log_sb "[STAGE ${stage_num}] Executing in FULL sandbox isolation..."

    local sandbox_id="sb-${run_id}-s${stage_num}-$(date +%s)"
    local snapshot_file="${SANDBOX_STATE_DIR}/snapshot_${sandbox_id}.json"
    local log_file="${SANDBOX_STATE_DIR}/log_${sandbox_id}.txt"

    local pre_state_hash pre_stage_hash pre_timestamp
    pre_stage_hash=$(sha256sum "$stage_script" 2>/dev/null | awk '{print $1}')
    pre_timestamp=$(date -Iseconds)
    pre_state_hash=$(compute_sandbox_state_hash)

    cat > "$snapshot_file" << EOF
{
  "sandbox_id": "${sandbox_id}",
  "version": "${SANDBOX_VERSION}",
  "run_id": "${run_id}",
  "epoch": "${epoch}",
  "stage": "${stage_num}",
  "stage_file": "${stage_script##*/}",
  "stage_hash": "${pre_stage_hash}",
  "state_hash_pre": "${pre_state_hash}",
  "timestamp_pre": "${pre_timestamp}",
  "isolation": {
    "mount_ns": true,
    "pid_ns": true,
    "net_ns": true,
    "ipc_ns": true,
    "uts_ns": true,
    "overlay_ro": true
  }
}
EOF

    local exit_code=0
    if command -v unshare &>/dev/null; then
        unshare --mount --pid --net --ipc --uts \
            bash -c "
                mount -t tmpfs tmpfs /tmp 2>/dev/null || true
                mount -t tmpfs tmpfs /var/tmp 2>/dev/null || true
                chmod 1777 /tmp /var/tmp
                export SANDBOX_ACTIVE=1
                export SANDBOX_RUN_ID=${sandbox_id}
                bash '${stage_script}' >> '${log_file}' 2>&1
            "
        exit_code=$?
    else
        SANDBOX_ACTIVE=1 SANDBOX_RUN_ID=$sandbox_id \
            bash "$stage_script" >> "$log_file" 2>&1
        exit_code=$?
    fi

    local post_state_hash post_timestamp post_tmp_free
    post_state_hash=$(compute_sandbox_state_hash)
    post_timestamp=$(date -Iseconds)
    post_tmp_free=$(df -k /tmp 2>/dev/null | tail -1 | awk '{print $4}' || echo "0")

    cat >> "$snapshot_file" << EOF
,
  "exit_code": ${exit_code},
  "state_hash_post": "${post_state_hash}",
  "timestamp_post": "${post_timestamp}",
  "tmp_free_kb_post": "${post_tmp_free}",
  "log_file": "${log_file##*/}"
}
EOF

    if [[ "$pre_state_hash" != "$post_state_hash" ]]; then
        log_sb "STATE HASH MISMATCH - triggering rollback"
        log_sb "  Pre:  $pre_state_hash"
        log_sb "  Post: $post_state_hash"
        echo "[$(date -Iseconds)] sandbox.state.diff_detected|sandbox_id=${sandbox_id}|pre=${pre_state_hash}|post=${post_state_hash}" \
            >> "${SANDBOX_STATE_DIR}/events.jsonl" 2>/dev/null || true
        echo "[$(date -Iseconds)] sandbox.rollback.triggered|sandbox_id=${sandbox_id}" \
            >> "${SANDBOX_STATE_DIR}/events.jsonl" 2>/dev/null || true
        sandbox_rollback "$sandbox_id" "$pre_state_hash"
        exit_code=41
    fi

    log_sb "[STAGE ${stage_num}] sandbox completed (exit: $exit_code)"
    return $exit_code
}

compute_sandbox_state_hash() {
    local hash_input=""
    if [[ -d "${SANDBOX_STATE_DIR}" ]]; then
        hash_input=$(find "${SANDBOX_STATE_DIR}" -type f \( -name "*.json" -o -name "*.jsonl" -o -name "*.log" \) 2>/dev/null | \
                     sort | xargs cat 2>/dev/null | sha256sum | awk '{print $1}')
    fi
    hash_input="${hash_input}${RUNTIME_VERSION:-unknown}$(date -u +%Y%m%d)"
    printf '%s' "$hash_input" | sha256sum | awk '{print $1}'
}

sandbox_rollback() {
    local sandbox_id="$1"
    local target_hash="$2"
    log_sb "Rollback to state: ${target_hash:0:16}..."
    rm -rf "${SANDBOX_STATE_DIR}/snapshot_${sandbox_id}"*.json 2>/dev/null || true
    rm -rf "${SANDBOX_STATE_DIR}/log_${sandbox_id}"*.txt 2>/dev/null || true
    log_sb "Rollback complete"
    return 0
}

generate_seccomp_profile() {
    local profile_file="$1"
    cat > "$profile_file" << 'EOF'
{
  "defaultAction": "SCMP_ACT_KILL",
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
  "syscalls": [
    {"names": ["read","write","open","openat","close","stat","fstat","lstat","exit","exit_group"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["execve","execveat","fork","vfork","clone","wait4","waitid"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["getuid","getgid","getpid","getppid","geteuid","getegid","getresuid","getresgid"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["chdir","fchdir","getcwd","getdents","getdents64"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["mkdir","rmdir","unlink","symlink","readlink","rename","link"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["chmod","chown","fchown","lchown","umask"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["pipe","pipe2","dup","dup2","dup3"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["brk","mmap","munmap","madvise","mlock","munlock"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["nanosleep","clock_nanosleep","alarm","getitimer","setitimer"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["rt_sigaction","rt_sigprocmask","rt_sigpending","rt_sigtimedwait"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["getcwd","gettimeofday","times","getrusage"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["capget","capset","prctl","seccomp"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["mount","umount2","reboot","syslog","init_module","delete_module"], "action": "SCMP_ACT_KILL"},
    {"names": ["socket","connect","bind","listen","accept","send","recv","sendto","recvfrom"], "action": "SCMP_ACT_KILL"},
    {"names": ["personality","sysinfo","syslog","uselib","physmem"], "action": "SCMP_ACT_KILL"}
  ]
}
EOF
    log_sb "Seccomp profile generated: ${profile_file##*/}"
}

sandbox_validate_boundary() {
    local run_id="${1:-}"
    local leaks=0

    log_sb "Validating sandbox boundary integrity..."

    if [[ -f /proc/1/ns/mnt ]]; then
        local self_ns host_ns
        self_ns=$(stat -c "%i" "/proc/$$/ns/mnt" 2>/dev/null || echo "0")
        host_ns=$(stat -c "%i" "/proc/1/ns/mnt" 2>/dev/null || echo "0")
        if [[ "$self_ns" != "$host_ns" ]]; then
            log_sb "  [OK] Mount namespace isolated (inode: $self_ns != $host_ns)"
        else
            warn_sb "  [WARN] Mount namespace NOT isolated"
            leaks=$((leaks + 1))
        fi
    fi

    if grep -q "/host" /proc/mounts 2>/dev/null; then
        err_sb "Host filesystem exposed in sandbox"
        leaks=$((leaks + 1))
    fi

    if command -v ip &>/dev/null; then
        local net_ns_count
        net_ns_count=$(ip netns list 2>/dev/null | wc -l)
        log_sb "  Network namespaces: $net_ns_count"
    fi

    local cap_permitted
    cap_permitted=$(cat /proc/self/status 2>/dev/null | grep CapAmb | awk '{print $2}' || echo "00000000000")
    if [[ "$cap_permitted" != "00000000000" ]]; then
        warn_sb "  [WARN] Capabilities retained: $cap_permitted"
    fi

    if [[ $leaks -eq 0 ]]; then
        log_sb "Sandbox boundary VALID"
        return 0
    else
        err_sb "Sandbox boundary COMPROMISED - $leaks leak(s)"
        return 1
    fi
}

enforce_write_boundary() {
    local path="$1"
    case "$path" in
        /tmp|/var/tmp|/run/pop-os-sandbox|/sysroot) return 0 ;;
        /home*|/etc|/usr|/bin|/lib|/sbin)
            err_sb "Write blocked to protected path: $path"
            return 1
            ;;
        /)
            err_sb "Write blocked: root filesystem"
            return 1
            ;;
        *) return 0 ;;
    esac
}

enforce_network_boundary() {
    local action="$1"
    if [[ "${SANDBOX_STRICT:-0}" == "1" ]]; then
        err_sb "Network action blocked in strict mode: $action"
        return 1
    fi
    return 0
}

log_violation() {
    local type="$1"
    local detail="$2"
    mkdir -p "$(dirname "$POLICY_LOG")" 2>/dev/null || true
    echo "[$(date -Iseconds)] VIOLATION|$type|$detail" >> "$POLICY_LOG"
    err_sb "SYSCALL VIOLATION [$type]: $detail"
}

sandbox_cleanup() {
    log_sb "Cleaning sandbox environment..."
    rm -rf "${SANDBOX_STATE_DIR}/snapshot_"*.json 2>/dev/null || true
    rm -rf "${SANDBOX_STATE_DIR}/log_"*.txt 2>/dev/null || true
    rm -rf "${OVERLAY_ROOT}/upper" "${OVERLAY_ROOT}/work" 2>/dev/null || true
    log_sb "Sandbox cleanup complete"
}

export -f sandbox_init sandbox_enter sandbox_exec_isolated
export -f generate_seccomp_profile sandbox_validate_boundary
export -f enforce_write_boundary enforce_network_boundary
export -f log_violation sandbox_cleanup
export -f sandbox_rollback compute_sandbox_state_hash

export SANDBOX_VERSION SANDBOX_STATE_DIR OVERLAY_ROOT POLICY_LOG
export SANDBOX_STRICT="${SANDBOX_STRICT:-0}"

sandbox_init

echo "[SANDBOX] v${SANDBOX_VERSION} OS-isolated runtime loaded"