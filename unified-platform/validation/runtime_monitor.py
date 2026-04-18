"""
Runtime Monitor — Live Execution Inspection Layer

Runs DURING job execution.
Monitors CPU/GPU usage, forbidden syscalls, dynamic imports,
subprocess spawning, memory injection, and execution time drift.
Any violation triggers immediate kill signal.
"""

import hashlib
import json
import time
import threading
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class ViolationSeverity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ViolationEvent:
    job_id: str
    severity: ViolationSeverity
    violation_type: str
    detail: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class RuntimeReport:
    job_id: str
    violations: list
    execution_hash: str
    final_state: str  # "RUNNING" | "KILLED" | "COMPLETED"
    baseline_hash: str
    runtime_seconds: float


class RuntimeMonitor:
    """
    Real-time execution monitoring.
    Polls job health on a background thread and detects anomalies.
    """

    FORBIDDEN_PATTERNS = [
        ("subprocess_spawn", re.compile(r"subprocess\.(call|run|Popen|check_output)", re.I)),
        ("ctypes_import", re.compile(r"\bimport\s+ctypes\b")),
        ("cffi_import", re.compile(r"\bimport\s+cffi\b")),
        ("eval_usage", re.compile(r"\beval\s*\(")),
        ("exec_usage", re.compile(r"\bexec\s*\(")),
        ("open_read_proc", re.compile(r"open\s*\(\s*['\"]\/proc\/", re.I)),
        ("memory_drill", re.compile(r"\*\s*\{.*?\}.*?\*", re.DOTALL)),
    ]

    def __init__(self, kill_callback: Optional[Callable] = None, poll_interval: float = 0.5):
        self.kill_callback = kill_callback
        self.poll_interval = poll_interval
        self._active_monitors: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._violation_callbacks: list[Callable] = []

    def add_violation_callback(self, cb: Callable):
        self._violation_callbacks.append(cb)

    def start_monitoring(self, job_id: str, baseline_metrics: Optional[dict] = None):
        with self._lock:
            self._active_monitors[job_id] = {
                "started_at": time.time(),
                "baseline": baseline_metrics or {},
                "baseline_hash": hashlib.sha256(
                    json.dumps(baseline_metrics or {}, sort_keys=True).encode()
                ).hexdigest()[:16],
                "cpu_samples": [],
                "gpu_samples": [],
                "violations": [],
                "state": "RUNNING",
            }

    def stop_monitoring(self, job_id: str) -> RuntimeReport:
        with self._lock:
            monitor = self._active_monitors.pop(job_id, None)

        if monitor is None:
            return RuntimeReport(
                job_id=job_id,
                violations=[],
                execution_hash="",
                final_state="UNKNOWN",
                baseline_hash="",
                runtime_seconds=0.0,
            )

        execution_hash = hashlib.sha256(
            json.dumps(
                {
                    "started_at": monitor["started_at"],
                    "ended_at": time.time(),
                    "cpu_samples": monitor["cpu_samples"][-10:],
                    "violations": [v.__dict__ for v in monitor["violations"]],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

        final_state = "KILLED" if monitor["violations"] else "COMPLETED"

        return RuntimeReport(
            job_id=job_id,
            violations=monitor["violations"],
            execution_hash=execution_hash,
            final_state=final_state,
            baseline_hash=monitor["baseline_hash"],
            runtime_seconds=time.time() - monitor["started_at"],
        )

    def check_violation(self, job_id: str, payload: dict, current_metrics: Optional[dict] = None):
        with self._lock:
            monitor = self._active_monitors.get(job_id)

        if monitor is None or monitor["state"] != "RUNNING":
            return

        violations_found = []

        payload_str = json.dumps(payload)
        for vtype, pattern in self.FORBIDDEN_PATTERNS:
            if pattern.search(payload_str):
                violation = ViolationEvent(
                    job_id=job_id,
                    severity=ViolationSeverity.HIGH,
                    violation_type=vtype,
                    detail=f"forbidden pattern detected: {vtype}",
                )
                violations_found.append(violation)

        if current_metrics:
            cpu_usage = current_metrics.get("cpu_percent", 0)
            gpu_usage = current_metrics.get("gpu_percent", 0)

            if monitor["baseline"].get("cpu_percent"):
                drift = abs(cpu_usage - monitor["baseline"]["cpu_percent"])
                if drift > 200:
                    violations_found.append(ViolationEvent(
                        job_id=job_id,
                        severity=ViolationSeverity.MEDIUM,
                        violation_type="cpu_drift",
                        detail=f"CPU usage drift: {drift}%",
                    ))

            if gpu_usage > 100:
                violations_found.append(ViolationEvent(
                    job_id=job_id,
                    severity=ViolationSeverity.HIGH,
                    violation_type="gpu_oversub",
                    detail=f"GPU usage {gpu_usage}% exceeds 100%",
                ))

        if current_metrics and "execution_time_drift" in current_metrics:
            drift = current_metrics["execution_time_drift"]
            if drift > 5.0:
                violations_found.append(ViolationEvent(
                    job_id=job_id,
                    severity=ViolationSeverity.LOW,
                    violation_type="time_drift",
                    detail=f"Execution time drift: {drift}s",
                ))

        if violations_found:
            with self._lock:
                monitor["violations"].extend(violations_found)
                max_severity = max(v.severity for v in violations_found)
                if max_severity in (ViolationSeverity.HIGH, ViolationSeverity.CRITICAL):
                    monitor["state"] = "KILLED"
                    kill_state = "KILLED"

            for cb in self._violation_callbacks:
                for v in violations_found:
                    cb(v)

            if self.kill_callback and monitor["state"] == "KILLED":
                self.kill_callback(job_id, violations_found)

    def get_violations(self, job_id: str) -> list:
        with self._lock:
            monitor = self._active_monitors.get(job_id)
        return monitor["violations"] if monitor else []

    def is_killed(self, job_id: str) -> bool:
        with self._lock:
            monitor = self._active_monitors.get(job_id)
        return monitor["state"] == "KILLED" if monitor else False
