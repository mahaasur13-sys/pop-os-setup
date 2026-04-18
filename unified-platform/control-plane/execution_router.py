"""
Control Plane — Execution Router
Routes admitted jobs to appropriate executors:
  - Slurm (GPU / batch)
  - Ray (distributed AI)
  - Kubernetes (long-running services)
  - Local (dev/test)

CRITICAL: This module handles routing DECISIONS only.
Actual execution (subprocess, kubectl, etc.) MUST happen in
domain/ai_scheduler/job-router.py or infra layer.
This module NEVER calls subprocess directly.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)


# Routing table: job_type → executor config
EXECUTOR_MAP = {
    "gpu": {"executor": "slurm", "partition": "gpu", "binary": "srun"},
    "cpu": {"executor": "slurm", "partition": "cpu", "binary": "srun"},
    "batch": {"executor": "slurm", "partition": "batch", "binary": "sbatch"},
    "inference": {"executor": "ray", "runtime": "inference", "binary": "ray"},
    "distributed_ai": {"executor": "ray", "runtime": "training", "binary": "ray"},
    "service": {"executor": "kubernetes", "runtime": "k8s", "manifest_dir": "infra/k8s/manifests/"},
    "dev": {"executor": "local", "runtime": "local", "binary": "python"},
}


class ExecutionRouter:
    """
    Deterministic job router based on job type.

    Flow:
        job → determine executor → return routing manifest
              ↓
        domain/ai_scheduler/job-router.py picks up the manifest
              ↓
        Actual execution in infra layer (Slurm/Ray/K8s)
    """

    def __init__(self):
        self._route_table = EXECUTOR_MAP.copy()
        self._custom_routes: dict = {}

    def route(self, job) -> dict:
        """
        Determine executor for a job.
        Returns routing manifest:
            {
                "executor": str,       # slurm | ray | k8s | local
                "target": str,         # partition/node or service name
                "binary": str,         # srun | ray | kubectl | python
                "manifest": dict,      # executor-specific config
            }
        """
        job_type = job.job_type

        # Check custom routes first
        if job_type in self._custom_routes:
            route = self._custom_routes[job_type]
            logger.info(f"Job {job.id} routed via custom route: {route['executor']}")
            return route

        # Use standard routing table
        if job_type not in self._route_table:
            logger.warning(f"Unknown job type '{job_type}', defaulting to local")
            return {
                "executor": "local",
                "target": "localhost",
                "binary": "python",
                "manifest": {},
            }

        route = self._route_table[job_type]
        route = {"job_id": job.id, **route}

        logger.info(
            f"Job {job.id} routed to {route['executor']}:{route.get('partition', route.get('runtime', 'default'))}"
        )
        return route

    def add_route(self, job_type: str, route: dict) -> None:
        """Add or override a routing rule."""
        self._custom_routes[job_type] = route
        logger.info(f"Custom route registered for job_type={job_type}")

    def remove_route(self, job_type: str) -> bool:
        """Remove a custom route, revert to default."""
        if job_type in self._custom_routes:
            del self._custom_routes[job_type]
            logger.info(f"Custom route removed for job_type={job_type}")
            return True
        return False

    def list_routes(self) -> dict:
        """Return full routing table (default + custom)."""
        return {**self._route_table, **self._custom_routes}

    def get_executor_for_job(self, job_type: str) -> Optional[str]:
        """Quick lookup: which executor handles this job type?"""
        if job_type in self._custom_routes:
            return self._custom_routes[job_type].get("executor")
        return self._route_table.get(job_type, {}).get("executor")
