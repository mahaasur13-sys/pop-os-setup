"""
ACOS Gateway — Infrastructure-facing boundary

Entry point for infra-layer callers (Slurm, Ray, K8s operators).
Applies ACOS boundary: infra NEVER calls control_plane — only this gateway.
"""

from typing import Any, Optional


class ACOSGateway:
    """
    Facade for infra-layer callers to submit jobs.
    Enforces ACOS isolation boundary.
    """

    def __init__(self, scheduler=None, audit_logger=None):
        self.scheduler = scheduler
        self.audit_logger = audit_logger

    def submit_job(self, job_spec: dict) -> str:
        if self.audit_logger:
            self.audit_logger.log_event(
                event_type="acos_submit",
                job_id=job_spec.get("type", "unknown"),
                metadata={"spec": job_spec},
            )
        if self.scheduler:
            job_id = self.scheduler.submit(job_spec)
            if self.audit_logger:
                self.audit_logger.log_event(
                    event_type="acos_job_submitted",
                    job_id=job_id,
                    metadata=job_spec,
                )
            return job_id
        return ""

    def get_job_status(self, job_id: str) -> Optional[str]:
        if self.scheduler:
            job = self.scheduler.get_job(job_id)
            if job:
                return job.state.value if hasattr(job, "state") else str(job)
        return None

    def get_queue_depth(self) -> dict:
        if self.scheduler:
            return self.scheduler.get_queue_depth()
        return {}
