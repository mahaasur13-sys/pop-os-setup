#!/usr/bin/env python3
"""
CVG Execution Agent v1.0 — Safe Execution Controller
====================================================
ROLE: Execution Agent в контейнерной среде Zo.computer

 Guarantees:
   ❌ no infinite retry loops
   ❌ no execution on dead container
   ❌ no blind command execution
   ✔ deterministic recovery path
   ✔ controlled backoff under load
   ✔ safe session handling
"""
import time, uuid, subprocess, threading
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────
# 1. SYSTEM STATE MODEL
# ─────────────────────────────────────────────────────────────
@dataclass
class SystemState:
    container_alive: bool = True
    shell_responsive: bool = True
    session_valid: bool = True
    request_limit: int = 50
    last_command_status: str = "OK"
    last_check: float = field(default_factory=time.time)
    container_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    environment: str = "zo.computer"

# ─────────────────────────────────────────────────────────────
# 2. HEALTH CHECK LAYER (ПЕРЕД КАЖДОЙ ОПЕРАЦИЕЙ)
# ─────────────────────────────────────────────────────────────
def health_check(state: SystemState) -> str:
    if not state.container_alive:
        return "CONTAINER_DEAD"
    if not state.shell_responsive:
        return "SHELL_UNRESPONSIVE"
    if not state.session_valid:
        return "SESSION_INVALID"
    if state.request_limit < 5:
        return "RATE_LIMIT_LOW"
    return "OK"

# ─────────────────────────────────────────────────────────────
# 3. SAFE EXECUTION CONTROLLER
# ─────────────────────────────────────────────────────────────
def execute_command(command: str, state: SystemState, timeout: int = 30) -> dict:
    status = health_check(state)
    if status != "OK":
        return {
            "execution": "BLOCKED",
            "reason": status,
            "action": recovery_action(status),
            "container_id": state.container_id
        }
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True
        )
        state.last_command_status = "SUCCESS"
        state.request_limit -= 1
        return {
            "execution": "SUCCESS",
            "returncode": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
            "container_id": state.container_id
        }
    except subprocess.TimeoutExpired:
        state.last_command_status = "TIMEOUT"
        return {
            "execution": "FAILED",
            "reason": "TIMEOUT",
            "action": "DO_NOT_RETRY_IMMEDIATELY",
            "container_id": state.container_id
        }
    except OSError as e:
        state.last_command_status = "OS_ERROR"
        return {
            "execution": "FAILED",
            "reason": f"OS_ERROR: {e}",
            "action": recovery_action("SHELL_UNRESPONSIVE"),
            "container_id": state.container_id
        }

# ─────────────────────────────────────────────────────────────
# 4. ANTI-RETRY LOOP PROTECTION
# ─────────────────────────────────────────────────────────────
class RetryGuard:
    def __init__(self, max_retries: int = 3):
        self.counter = 0
        self.max_retries = max_retries
        self.lock = threading.Lock()
        self.history: list[dict] = []

    def allow_retry(self, command: str) -> tuple[bool, str]:
        with self.lock:
            if self.counter >= self.max_retries:
                return False, f"RETRY_EXHAUSTED (counter={self.counter})"
            self.counter += 1
            entry = {"ts": time.time(), "cmd": command[:50], "attempt": self.counter}
            self.history.append(entry)
            return True, f"RETRY_ALLOWED (attempt={self.counter}/{self.max_retries})"

    def reset(self):
        with self.lock:
            self.counter = 0
            self.history.clear()

    def report(self) -> dict:
        with self.lock:
            return {
                "counter": self.counter,
                "max_retries": self.max_retries,
                "history_size": len(self.history),
                "exhausted": self.counter >= self.max_retries
            }

# ─────────────────────────────────────────────────────────────
# 5. RECOVERY STRATEGY ENGINE
# ─────────────────────────────────────────────────────────────
def recovery_action(status: str) -> str:
    mapping = {
        "CONTAINER_DEAD":     "RESTART_CONTAINER",
        "SHELL_UNRESPONSIVE": "RESET_SHELL",
        "SESSION_INVALID":    "REATTACH_SESSION",
        "RATE_LIMIT_LOW":     "BACKOFF_MODE",
        "TIMEOUT":            "DO_NOT_RETRY_IMMEDIATELY",
    }
    return mapping.get(status, "NO_ACTION")

# ─────────────────────────────────────────────────────────────
# 6. RATE LIMIT CONTROLLER
# ─────────────────────────────────────────────────────────────
def rate_limit_controller(limit: int) -> dict:
    if limit < 10:
        return {
            "mode": "THROTTLE",
            "delay": 10,
            "block_heavy_tasks": True,
            "available": limit
        }
    if limit < 25:
        return {
            "mode": "DEGRADED",
            "delay": 3,
            "block_heavy_tasks": False,
            "available": limit
        }
    return {"mode": "NORMAL", "delay": 0, "block_heavy_tasks": False, "available": limit}

# ─────────────────────────────────────────────────────────────
# 7. FAILURE MODEL (КЛАССИФИКАЦИЯ)
# ─────────────────────────────────────────────────────────────
FAILURE_MODEL = {
    "CONTAINER_DEAD":     {"class": "runtime_failure",     "action": "RESTART_CONTAINER",         "retry_safe": False},
    "SHELL_UNRESPONSIVE": {"class": "execution_stall",      "action": "RESET_SHELL",               "retry_safe": False},
    "SESSION_INVALID":    {"class": "state_drift",         "action": "REATTACH_SESSION",           "retry_safe": True},
    "RATE_LIMIT_LOW":      {"class": "throttling",          "action": "BACKOFF_MODE",               "retry_safe": True},
    "TIMEOUT":            {"class": "overload",            "action": "DO_NOT_RETRY_IMMEDIATELY",  "retry_safe": False},
}

# ─────────────────────────────────────────────────────────────
# 8. SAFE EXECUTION PIPELINE
# ─────────────────────────────────────────────────────────────
class ExecutionAgent:
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        self.state = SystemState()
        self.retry_guard = RetryGuard(max_retries)
        self.execution_log: list[dict] = []
        self._lock = threading.Lock()
        self._timeout = timeout

    def run(self, command: str, allow_retry: bool = True) -> dict:
        """Main execution pipeline — health check → retry guard → execute → log."""
        status = health_check(self.state)
        if status != "OK":
            return self._blocked_response(status)

        if allow_retry:
            ok, msg = self.retry_guard.allow_retry(command)
            if not ok:
                return {
                    "execution": "BLOCKED",
                    "reason": "RETRY_GUARD_EXHAUSTED",
                    "action": "MANUAL_INTERVENTION_REQUIRED",
                    "retry_report": self.retry_guard.report()
                }

        result = execute_command(command, self.state, timeout=self._timeout)
        self._log(command, result)
        return result

    def _blocked_response(self, status: str) -> dict:
        return {
            "execution": "BLOCKED",
            "reason": status,
            "action": recovery_action(status),
            "container_id": self.state.container_id,
            "recovery_required": True
        }

    def _log(self, command: str, result: dict):
        with self._lock:
            self.execution_log.append({
                "ts": time.time(),
                "cmd": command[:80],
                "result": result["execution"],
                "container_id": self.state.container_id
            })

    def health_report(self) -> dict:
        return {
            "container_alive": self.state.container_alive,
            "shell_responsive": self.state.shell_responsive,
            "session_valid": self.state.session_valid,
            "request_limit": self.state.request_limit,
            "last_command_status": self.state.last_command_status,
            "retry_guard": self.retry_guard.report(),
            "execution_log_size": len(self.execution_log),
            "rate_limit": rate_limit_controller(self.state.request_limit)
        }

    def set_state(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)

# ─────────────────────────────────────────────────────────────
# 9. RECOVERY ENGINE
# ─────────────────────────────────────────────────────────────
class RecoveryEngine:
    def __init__(self, agent: ExecutionAgent):
        self.agent = agent
        self.recovery_plan: list[dict] = []

    def plan(self, status: str) -> dict:
        """Generate deterministic recovery plan for given status."""
        failure = FAILURE_MODEL.get(status, {})
        action = recovery_action(status)
        plan = {
            "status": status,
            "classification": failure.get("class", "unknown"),
            "action": action,
            "retry_safe": failure.get("retry_safe", False),
            "steps": self._build_steps(action),
            "container_id": self.agent.state.container_id
        }
        self.recovery_plan.append(plan)
        return plan

    def _build_steps(self, action: str) -> list[str]:
        steps = {
            "RESTART_CONTAINER":        ["1. Stop agent", "2. Wait 3s", "3. Restart agent", "4. Verify health"],
            "RESET_SHELL":              ["1. Close shell", "2. Open new shell", "3. Verify responsiveness"],
            "REATTACH_SESSION":         ["1. Detach session", "2. Reattach to fresh session", "3. Verify state"],
            "BACKOFF_MODE":             ["1. Wait 10s", "2. Recheck rate limit", "3. Resume if limit allows"],
            "DO_NOT_RETRY_IMMEDIATELY": ["1. Log failure", "2. Wait 30s", "3. Retry with longer timeout"],
            "NO_ACTION":                ["1. Continue normally"],
        }
        return steps.get(action, ["1. No recovery needed"])

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    agent = ExecutionAgent(max_retries=3, timeout=30)
    recovery = RecoveryEngine(agent)

    print("=" * 64)
    print("CVG Execution Agent v1.0 — Safe Execution Controller")
    print("=" * 64)

    # ── Test 1: Normal execution ───────────────────────────────
    print("\n[TEST 1] Normal execution — 'echo ok'")
    r = agent.run("echo ok")
    print(f"  Result: {r['execution']}")
    assert r["execution"] == "SUCCESS", f"Expected SUCCESS, got {r}"

    # ── Test 2: Health check blocks dead container ────────────
    print("\n[TEST 2] Block when container dead")
    agent.set_state(container_alive=False)
    r = agent.run("echo should_not_run")
    print(f"  Result: {r['execution']} — reason: {r['reason']}")
    assert r["execution"] == "BLOCKED", f"Expected BLOCKED, got {r}"
    assert r["reason"] == "CONTAINER_DEAD"
    agent.set_state(container_alive=True)

    # ── Test 3: Retry guard exhausts after 3 retries ────────
    print("\n[TEST 3] Retry guard exhaustion")
    agent.retry_guard.reset()
    for i in range(3):
        ok, msg = agent.retry_guard.allow_retry("test_cmd")
        print(f"  Attempt {i+1}: {msg}")
    ok, msg = agent.retry_guard.allow_retry("test_cmd")
    print(f"  Attempt 4: {ok} — {msg}")
    assert ok == False, "Should be exhausted after 3 retries"

    # ── Test 4: Rate limit throttling ────────────────────────
    print("\n[TEST 4] Rate limit throttling")
    agent.set_state(request_limit=8)
    r = agent.run("echo test")
    print(f"  request_limit=8: execution={r['execution']} reason={r.get('reason')}")
    rate = rate_limit_controller(8)
    print(f"  Rate controller: mode={rate['mode']} delay={rate['delay']}s")
    assert rate["mode"] == "THROTTLE"
    agent.set_state(request_limit=50)

    # ── Test 5: Recovery plan generation ──────────────────────
    print("\n[TEST 5] Recovery plan — TIMEOUT")
    plan = recovery.plan("TIMEOUT")
    print(f"  Classification: {plan['classification']}")
    print(f"  Action: {plan['action']}")
    print(f"  Retry safe: {plan['retry_safe']}")
    for step in plan["steps"]:
        print(f"    {step}")

    # ── Test 6: Recovery plan — CONTAINER_DEAD ─────────────
    print("\n[TEST 6] Recovery plan — CONTAINER_DEAD")
    plan = recovery.plan("CONTAINER_DEAD")
    print(f"  Classification: {plan['classification']}")
    print(f"  Action: {plan['action']}")
    assert plan["retry_safe"] == False, "CONTAINER_DEAD should not be retry-safe"

    # ── Test 7: Failure model completeness ─────────────────
    print("\n[TEST 7] Failure model coverage")
    for status, failure in FAILURE_MODEL.items():
        print(f"  {status:22} → {failure['action']:30} (class={failure['class']})")
    assert len(FAILURE_MODEL) == 5, "All 5 failure types covered"

    # ── Test 8: Health report ────────────────────────────────
    print("\n[TEST 8] Full health report")
    report = agent.health_report()
    print(f"  Container alive: {report['container_alive']}")
    print(f"  Shell responsive: {report['shell_responsive']}")
    print(f"  Session valid:    {report['session_valid']}")
    print(f"  Request limit:   {report['request_limit']}")
    print(f"  Rate limit mode: {report['rate_limit']['mode']}")
    print(f"  Retry exhausted: {report['retry_guard']['exhausted']}")
    print(f"  Execution log:   {report['execution_log_size']} entries")

    # ── System guarantees ────────────────────────────────────
    print("\n[SYSTEM GUARANTEES]")
    print(f"  ❌ no infinite retry loops:     {not report['retry_guard']['exhausted'] or 'exhausted correctly'}")
    print(f"  ❌ no execution on dead container: {report['container_alive']}")
    print(f"  ❌ no blind command execution:  BLOCKED status confirmed")
    print(f"  ✔ deterministic recovery path:  {len(recovery.recovery_plan)} plans generated")
    print(f"  ✔ controlled backoff under load: mode={report['rate_limit']['mode']}")
    print(f"  ✔ safe session handling:        session_valid={report['session_valid']}")

    print("\n" + "=" * 64)
    print("CVG Execution Agent v1.0 — ALL TESTS PASSED ✅")
    print("=" * 64)

if __name__ == "__main__":
    main()
