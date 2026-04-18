"""
Execution Router — Job-to-Executor Routing

Routes jobs to the appropriate executor (Slurm, Ray, Kubernetes, Local).
Supports custom route overrides.
"""

from typing import Optional


class ExecutionRouter:
    """
    Routes jobs to executors based on job type.
    """

    DEFAULT_ROUTES = {
        "gpu": {"executor": "slurm", "partition": "gpu"},
        "cpu": {"executor": "slurm", "partition": "cpu"},
        "batch": {"executor": "slurm", "partition": "batch"},
        "train": {"executor": "slurm", "partition": "gpu"},
        "eval": {"executor": "slurm", "partition": "gpu"},
        "inference": {"executor": "ray", "runtime": "inference"},
        "service": {"executor": "kubernetes", "namespace": "default"},
        "data": {"executor": "slurm", "partition": "cpu"},
        "export": {"executor": "local"},
        "preprocess": {"executor": "slurm", "partition": "cpu"},
        "postprocess": {"executor": "slurm", "partition": "cpu"},
    }

    def __init__(self):
        self._custom_routes: dict = {}

    def route(self, job) -> dict:
        job_type = getattr(job, "job_type", None) or (job.get("type") if isinstance(job, dict) else None)
        if job_type in self._custom_routes:
            return self._custom_routes[job_type]
        return self.DEFAULT_ROUTES.get(job_type, {"executor": "local", "partition": "default"})

    def add_route(self, job_type: str, route: dict):
        self._custom_routes[job_type] = route

    def get_route(self, job_type: str) -> dict:
        return self._custom_routes.get(job_type) or self.DEFAULT_ROUTES.get(job_type, {"executor": "local"})
