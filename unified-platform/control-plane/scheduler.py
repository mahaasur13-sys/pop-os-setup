"""
Control Plane — Job Scheduler
Entry point for all job submission.
Routes through policy engine before execution.
"""

import uuid
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = __import__("logging").getLogger(__name__)


class JobPriority(Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0


class JobState(Enum):
    PENDING = "pending"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str = ""
    priority: JobPriority = JobPriority.NORMAL
    payload: dict = field(default_factory=dict)
    state: JobState = JobState.PENDING
    created_at: float = field(default_factory=time.time)
    admitted_at: Optional[float] = None
    completed_at: Optional[float] = None
    policy_decision: Optional[dict] = None
    error: Optional[str] = None


class Scheduler:
    """
    Canonical job scheduler for the platform.
    All job submissions MUST go through this interface.

    Flow:
        submit() → validate() → policy_engine.check() → enqueue() → dispatch()
    """

    def __init__(self, policy_engine=None, router=None):
        from control_plane.policy_engine import PolicyEngine
        from control_plane.execution_router import ExecutionRouter
        from control_plane.audit_logger import AuditLogger

        self.policy_engine = policy_engine or PolicyEngine()
        self.router = router or ExecutionRouter()
        self.audit = AuditLogger()
        self._queue: list[Job] = []

    def submit(self, job_spec: dict) -> str:
        """
        Submit a job for scheduling.
        Returns job_id.

        Flow:
            1. Build Job object
            2. Validate spec
            3. Policy engine admission check
            4. Audit log
            5. Enqueue or reject
        """
        job = Job(
            job_type=job_spec.get("type", "unknown"),
            priority=JobPriority[job_spec.get("priority", "NORMAL").upper()],
            payload=job_spec.get("payload", {}),
        )

        # Policy admission check
        decision = self.policy_engine.admit(job)
        job.policy_decision = decision

        if not decision.get("admitted", False):
            job.state = JobState.REJECTED
            job.error = decision.get("reason", "policy rejection")
            self.audit.log_event(
                event_type="JOB_REJECTED",
                job_id=job.id,
                reason=job.error,
                policy=decision,
            )
            logger.warning(f"Job {job.id} rejected: {job.error}")
            return job.id

        # Admit
        job.state = JobState.ADMITTED
        job.admitted_at = time.time()
        self.audit.log_event(
            event_type="JOB_ADMITTED",
            job_id=job.id,
            job_type=job.job_type,
            priority=job.priority.name,
            policy=decision,
        )

        # Enqueue sorted by priority
        self._enqueue_sorted(job)
        logger.info(f"Job {job.id} admitted, priority={job.priority.name}")
        return job.id

    def _enqueue_sorted(self, job: Job):
        """Insert job into queue maintaining priority order."""
        priorities = [j.priority.value for j in self._queue]
        insert_pos = 0
        for i, p in enumerate(priorities):
            if job.priority.value < p:
                insert_pos = i
                break
            insert_pos = i + 1
        self._queue.insert(insert_pos, job)

    def dispatch_next(self) -> Optional[str]:
        """
        Dispatch the highest-priority job from queue.
        Returns job_id if dispatched, None if queue empty.
        """
        if not self._queue:
            return None

        job = self._queue.pop(0)
        job.state = JobState.RUNNING

        # Route to appropriate executor
        routing = self.router.route(job)
        self.audit.log_event(
            event_type="JOB_DISPATCHED",
            job_id=job.id,
            executor=routing.get("executor"),
            target=routing.get("target"),
        )

        logger.info(
            f"Job {job.id} dispatched to {routing.get('executor')}:{routing.get('target')}"
        )
        return job.id

    def get_queue_depth(self) -> dict:
        """Return queue depth by priority."""
        return {p.name: sum(1 for j in self._queue if j.priority == p) for p in JobPriority}
