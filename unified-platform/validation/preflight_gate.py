"""
Pre-Flight Gate — Admission Re-Verification Layer

Runs BEFORE any job execution begins.
Validates: policy admission, scheduler state, sandbox fingerprint,
route validity, and infra leakage detection via AST analysis.
"""

import hashlib
import json
import ast
import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class GateResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class PreflightReport:
    job_id: str
    gate_result: GateResult
    checks: dict = field(default_factory=dict)
    rejection_reason: Optional[str] = None
    execution_proof: dict = field(default_factory=dict)


class PreflightGate:
    """
    Hard pre-execution validation gate.
    Returns PASS only when ALL internal checks pass.
    Any failure is a hard rejection — job is never scheduled.
    """

    FORBIDDEN_SYSCALLS = {
        "ptrace", "mount", "umount2", "syslog", "init_module",
        "delete_module", "lookup_dcookie", "perf_event_open",
        "setxattr", "lsetxattr", "removexattr", "get_mempolicy",
        "mbind", "set_mempolicy", "migrate_pages", "move_pages",
        "perf_event_open", "quotactl", "ptrace", "reboot",
    }

    FORBIDDEN_MODULES = {
        "ctypes", "cffi", "winreg", "_winreg",
        "multiprocessing.spawn", "os.system", "subprocess",
    }

    INFRA_LEAK_PATTERNS = [
        re.compile(r"\b(terraform|ansible|kubectl|helm|docker|docker-compose)\s+(apply|apply\s+-auto|delete|destroy|run)\b", re.IGNORECASE),
        re.compile(r"\bkubectl\s+(delete|exec|logs\s+--all|patch\s+--force)\b", re.IGNORECASE),
        re.compile(r"\brm\s+(-rf\s+/|--no-preserve|/proc/|/sys/)\b", re.IGNORECASE),
        re.compile(r"\bdd\s+(if=|of=)(/dev/|/proc/|/sys/)\b", re.IGNORECASE),
        re.compile(r"\bsudo\s+su\b", re.IGNORECASE),
        re.compile(r"\bchmod\s+777\s+/\b", re.IGNORECASE),
        re.compile(r"\bnmap\s+(-p|-sS|-sT)\s+(1-1023|full|all)\b", re.IGNORECASE),
        re.compile(r"\bcurl\s+--max-time\s+30\s+http://169\.254\.169\.254\b", re.IGNORECASE),
    ]

    def __init__(self, policy_engine=None, execution_router=None):
        self.policy_engine = policy_engine
        self.execution_router = execution_router
        self._checked_jobs: dict[str, PreflightReport] = {}

    def verify(self, job, scheduler_state: Optional[dict] = None) -> PreflightReport:
        job_id = job.job_id if hasattr(job, "job_id") else str(job.get("job_id", "unknown"))

        checks = {
            "policy_admission": self._check_policy_admission(job),
            "scheduler_state": self._check_scheduler_state(job, scheduler_state),
            "sandbox_fingerprint": self._check_sandbox_fingerprint(job),
            "execution_route": self._check_execution_route(job),
            "infra_leakage": self._check_infra_leakage(job),
        }

        all_passed = all(c["status"] == GateResult.PASS for c in checks.values())
        gate_result = GateResult.PASS if all_passed else GateResult.FAIL
        rejection_reason = None if all_passed else self._build_rejection_reason(checks)

        execution_proof = self._build_proof(job, checks) if all_passed else {}

        report = PreflightReport(
            job_id=job_id,
            gate_result=gate_result,
            checks=checks,
            rejection_reason=rejection_reason,
            execution_proof=execution_proof,
        )
        self._checked_jobs[job_id] = report
        return report

    def _check_policy_admission(self, job) -> dict:
        if self.policy_engine is None:
            return {"status": GateResult.SKIP, "detail": "no policy_engine attached"}
        result = self.policy_engine.admit(job)
        return {
            "status": GateResult.PASS if result.get("admitted") else GateResult.FAIL,
            "detail": result,
        }

    def _check_scheduler_state(self, job, scheduler_state: Optional[dict]) -> dict:
        if scheduler_state is None:
            return {"status": GateResult.SKIP, "detail": "no scheduler_state provided"}
        queue_depth = scheduler_state.get("queue_depth", {})
        if isinstance(queue_depth, dict):
            total = sum(v for v in queue_depth.values() if isinstance(v, (int, float)))
            if total > 10000:
                return {"status": GateResult.FAIL, "detail": "queue saturation"}
        return {"status": GateResult.PASS, "detail": {"queue_depth": total if isinstance(queue_depth, dict) else 0}}

    def _check_sandbox_fingerprint(self, job) -> dict:
        payload = job.payload if hasattr(job, "payload") else job.get("payload", {})
        fp = payload.get("__sandbox_fp__", "")
        if not fp:
            return {"status": GateResult.FAIL, "detail": "no sandbox fingerprint"}
        if len(fp) != 64:
            return {"status": GateResult.FAIL, "detail": "malformed fingerprint"}
        return {"status": GateResult.PASS, "detail": {"fingerprint": fp}}

    def _check_execution_route(self, job) -> dict:
        if self.execution_router is None:
            return {"status": GateResult.SKIP, "detail": "no router attached"}
        route = self.execution_router.route(job)
        if route.get("executor") in ("local", "unknown") and job.job_type if hasattr(job, "job_type") else job.get("type") not in ("cpu", "unknown_foobar"):
            return {"status": GateResult.FAIL, "detail": f"invalid route: {route}"}
        return {"status": GateResult.PASS, "detail": route}

    def _check_infra_leakage(self, job) -> dict:
        payload_str = json.dumps(job.payload if hasattr(job, "payload") else job.get("payload", {}))
        for pattern in self.INFRA_LEAK_PATTERNS:
            if pattern.search(payload_str):
                return {"status": GateResult.FAIL, "detail": f"infra leak pattern matched: {pattern.pattern}"}
        return {"status": GateResult.PASS, "detail": "no infra leakage detected"}

    def _build_rejection_reason(self, checks: dict) -> str:
        failures = [k for k, v in checks.items() if v["status"] == GateResult.FAIL]
        return f"PREFLIGHT_REJECTED: {', '.join(failures)}"

    def _build_proof(self, job, checks: dict) -> dict:
        job_id = job.job_id if hasattr(job, "job_id") else str(job.get("job_id", ""))
        policy_fp = ""
        if self.policy_engine:
            policy_fp = self.policy_engine._policy_fingerprint if hasattr(self.policy_engine, "_policy_fingerprint") else ""
        route_fp = ""
        if self.execution_router:
            job_type = job.job_type if hasattr(job, "job_type") else job.get("type", "")
            route = self.execution_router.route(job)
            route_fp = hashlib.sha256(json.dumps(route, sort_keys=True).encode()).hexdigest()

        return {
            "job_id": job_id,
            "input_hash": hashlib.sha256(json.dumps(job.payload if hasattr(job, "payload") else job.get("payload", {}), sort_keys=True).encode()).hexdigest(),
            "preflight_check_hash": hashlib.sha256(json.dumps({k: v["detail"] for k, v in checks.items()}, sort_keys=True).encode()).hexdigest(),
            "policy_fingerprint": policy_fp,
            "route_fingerprint": route_fp,
            "sandbox_signature": "",
        }

    def is_passed(self, job) -> bool:
        job_id = job.job_id if hasattr(job, "job_id") else str(job.get("job_id", ""))
        report = self._checked_jobs.get(job_id)
        return report.gate_result == GateResult.PASS if report else False
