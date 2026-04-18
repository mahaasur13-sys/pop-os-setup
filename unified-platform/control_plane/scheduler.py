"""
Scheduler — Priority-based Job Queue

Provides job submission, priority ordering, and dispatch.
Jobs flow through policy_engine.admit() before being enqueued.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class JobPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class JobState(Enum):
    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Job:
    job_id: str
    job_type: str
    priority: int
    payload: dict
    state: JobState = JobState.PENDING
    submitted_at: float = field(default_factory=lambda: __import__("time").time())
    admitted_at: Optional[float] = None


class Scheduler:
    """
    Priority-based job scheduler with policy admission gate.
    """

    def __init__(self, policy_engine=None):
        self.policy_engine = policy_engine
        self._jobs: dict[str, Job] = {}
        self._queues: dict[int, list[str]] = {p.value: [] for p in JobPriority}
        self._admitted_count = 0
        self._rejected_count = 0

    def submit(self, spec: dict) -> str:
        job_type = spec.get("type", "unknown")
        priority_str = spec.get("priority", "NORMAL")
        priority = getattr(JobPriority, priority_str.upper(), JobPriority.NORMAL).value
        payload = spec.get("payload", {})

        job_id = hashlib.sha256(f"{uuid.uuid4()}{priority}{job_type}".encode()).hexdigest()[:16]

        job = Job(
            job_id=job_id,
            job_type=job_type,
            priority=priority,
            payload=payload,
            state=JobState.PENDING,
        )

        admitted = False
        if self.policy_engine is not None:
            result = self.policy_engine.admit(job)
            admitted = result.get("admitted", False)
        else:
            admitted = True

        if admitted:
            job.state = JobState.ADMITTED
            job.admitted_at = __import__("time").time()
            self._queues[priority].append(job_id)
            self._admitted_count += 1
        else:
            job.state = JobState.REJECTED
            self._rejected_count += 1

        self._jobs[job_id] = job
        return job_id

    def dispatch_next(self) -> Optional[Job]:
        for priority in sorted(self._queues.keys(), reverse=True):
            queue = self._queues[priority]
            while queue:
                job_id = queue.pop(0)
                job = self._jobs.get(job_id)
                if job and job.state == JobState.ADMITTED:
                    job.state = JobState.RUNNING
                    return job
        return None

    def get_queue_depth(self) -> dict:
        return {p.name: len(q) for p, q in self._queues.items()}

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def complete_job(self, job_id: str, result: dict):
        job = self._jobs.get(job_id)
        if job:
            job.state = JobState.COMPLETED

    def fail_job(self, job_id: str, reason: str):
        job = self._jobs.get(job_id)
        if job:
            job.state = JobState.FAILED
