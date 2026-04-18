"""
ATOMFederationOS v4.0 — ADMISSION CONTROL SYSTEM
P1 FIX: Load shedding + queue prioritization + SLA enforcement

Admission Rule:
  IF cpu_usage > threshold OR queue_depth > limit:
      reject OR degrade priority
"""
from __future__ import annotations
import time, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from collections import defaultdict


class AdmissionVerdict(Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"
    DEGRADED = "degraded"      # admitted but lower priority
    QUEUED = "queued"          # held until capacity available
    SHED = "shed"             # permanently dropped (over limit)


@dataclass
class SLAPolicy:
    max_queue_depth: int = 100
    cpu_threshold_pct: float = 80.0
    ram_threshold_gb: float = 28.0
    gpu_threshold_pct: float = 90.0
    degrade_threshold_pct: float = 60.0  # degrade below this
    max_pending_sec: float = 30.0         # SLA: max time in queue
    hard_limit_tasks: int = 1000         # absolute cap


@dataclass
class AdmissionRecord:
    task_id: str
    verdict: AdmissionVerdict
    original_priority: int
    assigned_priority: int
    reason: str
    cpu_usage_at_admission: float
    queue_depth_at_admission: int
    timestamp: float


class AdmissionController:
    """
    Admission Control + Load Shedding + SLA Enforcement.
    Protects system from overload by rejecting or degrading low-priority work.
    """

    def __init__(self, policy: Optional[SLAPolicy] = None):
        self.policy = policy or SLAPolicy()
        self._records: List[AdmissionRecord] = []
        self._queue_depth = 0
        self._total_admitted = 0
        self._total_rejected = 0
        self._total_degraded = 0
        self._total_shed = 0
        self._lock = threading.Lock()
        self._node_loads: Dict[str, dict] = defaultdict(dict)

    # ── Load Sampling ────────────────────────────────────────────────

    def update_node_load(self, node_id: str, cpu_pct: float, ram_gb: float, gpu_pct: float = 0.0):
        self._node_loads[node_id] = {
            "cpu_pct": cpu_pct,
            "ram_gb": ram_gb,
            "gpu_pct": gpu_pct,
            "updated_at": time.time(),
        }

    def get_cluster_load(self) -> dict:
        if not self._node_loads:
            return {"avg_cpu": 0.0, "max_cpu": 0.0, "avg_ram": 0.0, "total_tasks": self._queue_depth}
        cpus = [l["cpu_pct"] for l in self._node_loads.values()]
        rams = [l["ram_gb"] for l in self._node_loads.values()]
        return {
            "avg_cpu": sum(cpus) / len(cpus),
            "max_cpu": max(cpus),
            "avg_ram": sum(rams) / len(rams),
            "max_ram": max(rams),
            "total_tasks": self._queue_depth,
        }

    # ── Admission Decision ─────────────────────────────────────────────

    def evaluate(self, task: dict, priority: Optional[int] = None) -> AdmissionRecord:
        """
        Evaluate whether a task should be admitted.
        Returns AdmissionRecord with verdict.
        """
        task_id = task.get("id", f"task-{time.time_ns()}")
        priority = priority if priority is not None else task.get("priority", 3)
        cpu = task.get("cpu", 1.0)
        ram = task.get("ram", 10.0)
        gpu = task.get("gpu", 0.0)

        load = self.get_cluster_load()
        cpu_at_admission = load["avg_cpu"]
        depth_at_admission = self._queue_depth

        verdict = AdmissionVerdict.ADMITTED
        reason = "ok"

        # Check hard cap
        if self._queue_depth >= self.policy.hard_limit_tasks:
            verdict = AdmissionVerdict.SHED
            reason = f"hard_limit_reached: {self.policy.hard_limit_tasks}"
        # Check queue depth
        elif self._queue_depth >= self.policy.max_queue_depth:
            verdict = AdmissionVerdict.REJECTED
            reason = f"queue_full: {self._queue_depth}/{self.policy.max_queue_depth}"
        # Check CPU threshold
        elif cpu_at_admission >= self.policy.cpu_threshold_pct:
            if priority <= 2:
                verdict = AdmissionVerdict.REJECTED
                reason = f"cpu_overload: {cpu_at_admission:.1f}% >= {self.policy.cpu_threshold_pct}%"
            else:
                verdict = AdmissionVerdict.DEGRADED
                reason = f"cpu_high_degraded: {cpu_at_admission:.1f}%"
        # Check RAM threshold
        elif load.get("avg_ram", 0) >= self.policy.ram_threshold_gb:
            verdict = AdmissionVerdict.QUEUED
            reason = f"ram_pressure: {load['avg_ram']:.1f}GB"
        # Check GPU threshold
        elif gpu > 0 and load.get("max_gpu", 0) >= self.policy.gpu_threshold_pct:
            verdict = AdmissionVerdict.REJECTED
            reason = f"gpu_full"
        # Degrade low-priority under medium load
        elif cpu_at_admission >= self.policy.degrade_threshold_pct and priority > 3:
            verdict = AdmissionVerdict.DEGRADED
            reason = f"load_degraded: {cpu_at_admission:.1f}% >= {self.policy.degrade_threshold_pct}%"
        else:
            verdict = AdmissionVerdict.ADMITTED
            reason = f"ok: cpu={cpu_at_admission:.1f}%, queue={self._queue_depth}"

        assigned_priority = priority
        if verdict == AdmissionVerdict.DEGRADED:
            assigned_priority = min(priority + 2, 5)  # Push to lower priority
            self._total_degraded += 1
        elif verdict == AdmissionVerdict.ADMITTED:
            self._total_admitted += 1
        elif verdict == AdmissionVerdict.REJECTED or verdict == AdmissionVerdict.SHED:
            self._total_rejected += 1
        elif verdict == AdmissionVerdict.QUEUED:
            self._queue_depth += 1

        record = AdmissionRecord(
            task_id=task_id,
            verdict=verdict,
            original_priority=priority,
            assigned_priority=assigned_priority,
            reason=reason,
            cpu_usage_at_admission=cpu_at_admission,
            queue_depth_at_admission=depth_at_admission,
            timestamp=time.time(),
        )

        with self._lock:
            self._records.append(record)
            if verdict not in (AdmissionVerdict.REJECTED, AdmissionVerdict.SHED):
                self._queue_depth += 1
            if len(self._records) > 5000:
                self._records = self._records[-2500:]

        return record

    # ── SLA Monitoring ─────────────────────────────────────────────────

    def check_sla_violations(self, max_pending_sec: Optional[float] = None) -> List[dict]:
        """Find tasks that have been in queue too long."""
        max_sec = max_pending_sec or self.policy.max_pending_sec
        now = time.time()
        violations = []
        with self._lock:
            for rec in self._records:
                if rec.verdict == AdmissionVerdict.QUEUED:
                    wait = now - rec.timestamp
                    if wait > max_sec:
                        violations.append({
                            "task_id": rec.task_id,
                            "wait_sec": round(wait, 2),
                            "original_priority": rec.original_priority,
                            "assigned_priority": rec.assigned_priority,
                            "cpu_at_admission": rec.cpu_usage_at_admission,
                        })
        return violations

    # ── Metrics ───────────────────────────────────────────────────────

    def admission_rate(self) -> float:
        total = self._total_admitted + self._total_rejected + self._total_shed
        if total == 0:
            return 1.0
        return self._total_admitted / total

    def rejection_rate(self) -> float:
        total = self._total_admitted + self._total_rejected + self._total_shed
        if total == 0:
            return 0.0
        return self._total_rejected / total

    def stats(self) -> dict:
        return {
            "queue_depth": self._queue_depth,
            "total_admitted": self._total_admitted,
            "total_rejected": self._total_rejected,
            "total_degraded": self._total_degraded,
            "total_shed": self._total_shed,
            "admission_rate": f"{self.admission_rate():.1%}",
            "rejection_rate": f"{self.rejection_rate():.1%}",
            "policy": {
                "cpu_threshold_pct": self.policy.cpu_threshold_pct,
                "max_queue_depth": self.policy.max_queue_depth,
                "hard_limit_tasks": self.policy.hard_limit_tasks,
            },
            "cluster_load": self.get_cluster_load(),
        }


def demo():
    ac = AdmissionController()

    # Simulate cluster load
    for nid in ["node-A", "node-B"]:
        ac.update_node_load(nid, cpu_pct=75.0, ram_gb=20.0)

    print("=== Admission Under Load (75% CPU) ===")
    for i in range(5):
        task = {"id": f"t{i}", "cpu": 1, "ram": 10, "priority": 2}
        rec = ac.evaluate(task)
        print(f"  {rec.task_id}: {rec.verdict.value} — {rec.reason}")

    # Bump CPU to 85% (over threshold)
    for nid in ["node-A", "node-B"]:
        ac.update_node_load(nid, cpu_pct=85.0, ram_gb=28.0)

    print("\n=== Admission Over CPU Threshold (85%) ===")
    for i in range(5):
        task = {"id": f"t{i+5}", "cpu": 1, "ram": 10, "priority": 4}
        rec = ac.evaluate(task)
        print(f"  {rec.task_id}: {rec.verdict.value} — {rec.reason}")

    print("\n=== Stats ===")
    import json
    print(json.dumps(ac.stats(), indent=2, default=str))


if __name__ == "__main__":
    demo()
