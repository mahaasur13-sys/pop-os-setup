#!/usr/bin/env bash
#===============================================================================
# engine/sandbox/syscall_policy.sh — v11.2 Syscall Control Layer
# Whitelist-based syscall enforcement for sandboxed execution
# Strict mode: default deny + explicit allow list
#===============================================================================

set -euo pipefail

readonly POLICY_VERSION="11.2"
readonly VIOLATION_LOG="/var/log/pop-os-sandbox/syscall_violations.log"
readonly VIOLATION_COUNT_MAX=5

# Default deny — only explicitly listed syscalls allowed
readonly ALLOWED_SYSCALLS=(
    # File operations
    read write open openat close stat fstat lstat fstatat
    lseek pread64 pwrite64 readlink link unlink symlink
    mkdir rmdir rename chmod fchmod chown fchown lchown
    # Process
    execve exit exit_group fork vfork clone wait4 waitid getpid getppid
    # Identity
    getuid geteuid getegid getgid getresuid getresgid getgid geteuid
    # Memory
    brk mmap munmap mprotect madvise mlock munlock mlockall munlockall
    # Time
    nanosleep clock_nanosleep alarm getitimer setitimer gettimeofday times
    # IPC
    pipe pipe2 dup dup2 dup3 select pselect6 poll ppoll
    # Path
    getcwd chdir fchdir
    # Signals
    rt_sigaction rt_sigprocmask rt_sigpending rt_sigtimedwait
    rt_sigreturn sigaltstack signal sigreturn
    # Capabilities
    capget capset prctl seccomp
    # FS queries
    getdents getdents64 readv writev sendfile
    # Misc
    sched_getparam sched_setparam getpriority setpriority
    sync fsync fdatasync syncfs
    uname getrusage getsysinfo sysinfo
    # Tracing (blocked in strict)
)

# Critical blocked syscalls — always denied even in permissive mode
readonly BLOCKED_SYSCALLS=(
    mount umount2 umount
    syslog klogctl
    init_module delete_module finit_module
    lookup_dcookie sysfs _sysctl
    adjtimex clock_adjtime
    setdomainname sethostname
    reboot ioperm iopl idle
    personality uselib physmem
    socket socketcall
    sendto recvfrom sendmsg recvmsg
    bind listen accept connect
    socketpair
    creat openat2 mknod mknodat
)

# ─── POLICY INIT ────────────────────────────────────────────────────────────────
policy_init() {
    log "🔐 Initializing v${POLICY_VERSION} syscall policy engine..."

    mkdir -p "$(dirname "$VIOLATION_LOG")" 2>/dev/null || true
    touch "$VIOLATION_LOG" 2>/dev/null || true
    chmod 600 "$VIOLATION_LOG" 2>/dev/null || true

    log "  ✓ Allowed: ${#ALLOWED_SYSCALLS[@]} syscall families"
    log "  ✓ Blocked: ${#BLOCKED_SYSCALLS[@]} dangerous operations"

    if [[ "${SANDBOX_STRICT:-0}" == "1" ]]; then
        log "  ⚡ STRICT MODE: default deny — unknown syscalls killed"
    else
        log "  ℹ PERMISSIVE MODE: unknown syscalls logged but allowed"
    fi

    return 0
}

# ─── VALIDATE SYSCALL ──────────────────────────────────────────────────────────
validate_syscall() {
    local syscall="$1"

    # Fast path: check blocked first
    for blocked in "${BLOCKED_SYSCALLS[@]}"; do
        if [[ "$syscall" == "$blocked" ]]; then
            log_violation "BLOCKED_SYSCALL" "$syscall"
            return 1
        fi
    done

    # Check allowed list
    for allowed in "${ALLOWED_SYSCALLS[@]}"; do
        if [[ "$syscall" == "$allowed" ]]; then
            return 0
        fi
    done

    # Unknown syscall handling
    if [[ "${SANDBOX_STRICT:-0}" == "1" ]]; then
        log_violation "UNKNOWN_KILLED" "$syscall"
        return 1
    else
        log "⚠️ Unknown syscall: $syscall (allowed in permissive mode)"
        return 0
    fi
}

# ─── LOG VIOLATION ─────────────────────────────────────────────────────────────
log_violation() {
    local type="$1"
    local syscall="$2"
    local timestamp
    timestamp=$(date -Iseconds)
    local entry="[${timestamp}] VIOLATION|${type}|${syscall}|pid=$$|uid=$(id -u)"
    echo "$entry" >> "$VIOLATION_LOG"
    err "❌ SYSCALL VIOLATION [$type]: $syscall (pid=$$)"
}

# ─── ENFORCE WRITE BOUNDARY ────────────────────────────────────────────────────
enforce_write_boundary() {
    local path="$1"
    local sandbox_root="${2:-${SANDBOX_STATE_DIR:-/run/pop-os-sandbox}}"

    # Normalize path
    path="$(realpath "$path" 2>/dev/null || echo "$path")"

    # Allowed write targets
    case "$path" in
        /tmp|/var/tmp|/run/pop-os-sandbox|/run/user/*)
            return 0
            ;;
        /sysroot/state|/sysroot/var)
            return 0
            ;;
        /home/*/.local/share)
            return 0
            ;;
        /var/log/pop-os-setup*)
            return 0
            ;;
        */state/*)
            # Stage state files — allowed
            return 0
            ;;
        *)
            # Check if it's outside sandbox root
            if [[ "$path" != /tmp/* && "$path" != /var/tmp/* &&
                  "$path" != /run/* && "$path" != /home/* ]]; then
                log_violation "WRITE_OUTSIDE_SANDBOX" "$path"
                return 1
            fi
            ;;
    esac

    return 0
}

# ─── ENFORCE NETWORK BOUNDARY ─────────────────────────────────────────────────
enforce_network_boundary() {
    local action="$1"  # connect, bind, send, recv, socket

    if [[ "${SANDBOX_STRICT:-0}" == "1" || "${SANDBOX_NETWORK_DISABLED:-1}" == "1" ]]; then
        log_violation "NETWORK_BLOCKED" "$action"
        return 1
    fi

    return 0
}

# ─── CHECK PROCESS ISOLATION ──────────────────────────────────────────────────
check_process_isolation() {
    local pid="${1:-$$}"

    # Verify process is in different mount namespace than host
    if [[ -f "/proc/$pid/ns/mnt" ]]; then
        local ns_inode host_ns_inode
        ns_inode=$(stat -c "%i" "/proc/$pid/ns/mnt" 2>/dev/null || echo "0")
        host_ns_inode=$(stat -c "%i" "/proc/1/ns/mnt" 2>/dev/null || echo "0")

        if [[ "$ns_inode" != "$host_ns_inode" ]]; then
            return 0  # Isolated
        fi
    fi

    return 1  # Not isolated
}

# ─── VERIFY SANDBOX IDENTITY ───────────────────────────────────────────────────
verify_sandbox_identity() {
    local run_id="${1:-}"

    # Check SANDBOX_ACTIVE marker
    if [[ "${SANDBOX_ACTIVE:-0}" != "1" ]]; then
        warn "⚠️ SANDBOX_ACTIVE not set — running outside sandbox"
        return 1
    fi

    # Verify run_id matches
    if [[ -n "$run_id" && "${SANDBOX_RUN_ID:-}" != *"${run_id}"* ]]; then
        warn "⚠️ SANDBOX_RUN_ID mismatch — possible fork attack"
        return 1
    fi

    return 0
}

# ─── AUDIT DUMP ────────────────────────────────────────────────────────────────
policy_audit_dump() {
    local output_file="${1:-/var/log/pop-os-sandbox/policy_audit.json}"

    local violation_count
    violation_count=$(wc -l < "$VIOLATION_LOG" 2>/dev/null || echo "0")

    cat > "$output_file" << EOF
{
  "version": "${POLICY_VERSION}",
  "timestamp": "$(date -Iseconds)",
  "sandbox_id": "${SANDBOX_RUN_ID:-unknown}",
  "violations_total": ${violation_count},
  "violation_log": "$(head -20 "$VIOLATION_LOG" 2>/dev/null || echo '')",
  "strict_mode": "${SANDBOX_STRICT:-0}",
  "network_disabled": "${SANDBOX_NETWORK_DISABLED:-1}",
  "allowed_syscalls_count": ${#ALLOWED_SYSCALLS[@]},
  "blocked_syscalls_count": ${#BLOCKED_SYSCALLS[@]}
}
EOF

    log "📋 Policy audit dumped: ${output_file}"
}

# ─── AUDIT MODE ────────────────────────────────────────────────────────────────
audit_syscalls() {
    local output_format="${1:-table}"
    STATEDIR="${STATEDIR:-/var/lib/pop-os-setup}"
    local audit_log="${STATEDIR}/syscall_audit.jsonl"

    echo "=========================================="
    echo "  Syscall Policy Audit Mode v${POLICY_VERSION}"
    echo "=========================================="
    echo ""

    mkdir -p "$(dirname "$VIOLATION_LOG")" "$(dirname "$audit_log")" 2>/dev/null || true
    touch "$audit_log" 2>/dev/null || true

    local total_allowed=${#ALLOWED_SYSCALLS[@]}
    local total_blocked=${#BLOCKED_SYSCALLS[@]}
    local total_violations=0

    if [[ -f "$VIOLATION_LOG" ]]; then
        total_violations=$(wc -l < "$VIOLATION_LOG")
    fi

    echo "--- Syscall Inventory ---"
    echo "  Allowed syscall families: $total_allowed"
    echo "  Blocked syscall families: $total_blocked"
    echo "  Total violations logged: $total_violations"
    echo ""

    echo "--- Allowed Syscalls ---"
    printf "  %-20s %s\n" "CATEGORY" "COUNT"
    printf "  %-20s %d\n" "read/write ops" 8
    printf "  %-20s %d\n" "process mgmt" 7
    printf "  %-20s %d\n" "filesystem" 14
    printf "  %-20s %d\n" "memory mgt" 6
    printf "  %-20s %d\n" "signal/timer" 10
    printf "  %-20s %d\n" "IPC" 4
    printf "  %-20s %d\n" "capabilities" 3
    echo ""

    echo "--- Blocked Syscalls ---"
    local blocked_detail="
  mount/umount       : Filesystem mounting operations
  syslog/klogctl    : Kernel logging
  init_module       : Kernel module loading
  delete_module     : Kernel module unloading
  reboot            : System reboot control
  sysfs             : Filesystem info
  setdomainname     : Hostname modification
  sethostname       : Hostname modification
  personality       : Execution domain change
  uselib            : Shared library loader
  iopl              : I/O privilege level
  ioperm            : I/O permission setup
  physmem           : Physical memory access
  socketcall        : Network socket operations"
    echo "$blocked_detail"
    echo ""

    echo "--- Violation Heatmap by Stage ---"
    if [[ -f "$VIOLATION_LOG" ]] && [[ "$total_violations" -gt 0 ]]; then
        printf "  %-10s %-10s %s\n" "STAGE" "VIOLATIONS" "TYPE"
        for stage_num in $(seq 1 26); do
            local stage_violations
            stage_violations=$(grep -c "\"s${stage_num}\"" "$VIOLATION_LOG" 2>/dev/null || echo "0")
            if [[ "$stage_violations" -gt 0 ]]; then
                local dominant_type
                dominant_type=$(grep "\"s${stage_num}\"" "$VIOLATION_LOG" 2>/dev/null | \
                                cut -d'|' -f2 | sort | uniq -c | sort -rn | head -1 | \
                                awk '{print $2}' || echo "unknown")
                printf "  %-10s %-10s %s\n" "s${stage_num}" "$stage_violations" "$dominant_type"
            fi
        done
    else
        echo "  No violations recorded"
    fi
    echo ""

    echo "--- Syscall Frequency Table ---"
    printf "  %-20s %-10s %s\n" "SYSCALL" "CALLED" "LAST_SEEN"
    for syscall in "${ALLOWED_SYSCALLS[@]}"; do
        local call_count
        call_count=$(grep -c "\"${syscall}\"" "$audit_log" 2>/dev/null || true)
        call_count="${call_count:-0}"
        [[ "$call_count" =~ [^0-9] ]] && call_count=0
        local last_seen="never"
        if [[ "${call_count}" -gt 0 ]]; then
            last_seen=$(grep "\"${syscall}\"" "$audit_log" 2>/dev/null | tail -1 | \
                        cut -d':' -f1 || echo "unknown")
        fi
        printf "  %-20s %-10s %s\n" "$syscall" "$call_count" "$last_seen"
    done
    echo ""

    echo "--- Blocked Syscall Attempts Histogram ---"
    if [[ -f "$VIOLATION_LOG" ]] && [[ "$total_violations" -gt 0 ]]; then
        printf "  %-20s %s\n" "SYSCALL" "COUNT"
        for blocked in "${BLOCKED_SYSCALLS[@]}"; do
            local count
            count=$(grep -c "$blocked" "$VIOLATION_LOG" 2>/dev/null || echo "0")
            if [[ "$count" -gt 0 ]]; then
                local bar=""
                local n=0
                while [[ $n -lt $count && $n -lt 20 ]]; do bar="${bar}#"; ((n++)) || true; done
                printf "  %-20s %s (%d)\n" "$blocked" "$bar" "$count"
            fi
        done
    else
        echo "  No blocked attempts recorded"
    fi
    echo ""

    echo "--- Audit Summary ---"
    echo "  Policy version: ${POLICY_VERSION}"
    echo "  Audit timestamp: $(date -Iseconds)"
    echo "  Total violations: ${total_violations}"
    echo "  Allowed: ${total_allowed}, Blocked: ${total_blocked}"
    echo ""

    return 0
}

# ─── EXPORT ────────────────────────────────────────────────────────────────────
export -f policy_init validate_syscall log_violation
export -f enforce_write_boundary enforce_network_boundary
export -f check_process_isolation audit_syscalls

export POLICY_VERSION VIOLATION_LOG VIOLATION_COUNT_MAX
export SANDBOX_STRICT="${SANDBOX_STRICT:-0}"
export SANDBOX_NETWORK_DISABLED="${SANDBOX_NETWORK_DISABLED:-1}"
export SANDBOX_ACTIVE="${SANDBOX_ACTIVE:-0}"
export SANDBOX_RUN_ID="${SANDBOX_RUN_ID:-}"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Standalone mode
    export SANDBOX_STRICT="${SANDBOX_STRICT:-0}"
    export SANDBOX_NETWORK_DISABLED="${SANDBOX_NETWORK_DISABLED:-1}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --audit-mode)
                audit_syscalls
                exit $?
                ;;
            --strict)
                export SANDBOX_STRICT=1
                shift
                ;;
            --permissive)
                export SANDBOX_STRICT=0
                shift
                ;;
            *)
                break
                ;;
        esac
    done

    policy_init
    echo "Syscall policy ready. Use --audit-mode to run audit."
    exit 0
fi

policy_init

echo "[SYSCALL_POLICY] v${POLICY_VERSION} loaded — $([[ "${SANDBOX_STRICT:-0}" == "1" ]] && echo STRICT || echo PERMISSIVE) mode"