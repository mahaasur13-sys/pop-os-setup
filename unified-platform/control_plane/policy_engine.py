"""
Policy Engine — Admission and Routing Rules

Central authority for job admission decisions.
Maintains a policy fingerprint for audit chaining.
"""

import hashlib
import json
from typing import Optional


class PolicyEngine:
    """
    Policy-based admission control.
    """

    ALLOWED_JOB_TYPES = {
        "gpu", "cpu", "inference", "batch", "service", "data",
        "train", "eval", "export", "preprocess", "postprocess",
    }

    FORBIDDEN_KEYWORDS = [
        "kubectl", "terraform", "ansible", "helm", "docker-compose",
        "rm -rf", "dd if=", "chmod 777", "chmod -R 777",
        "nmap", "curl http://169.254.169.254",
    ]

    def __init__(self):
        self._rules = {
            "max_concurrent_gpu_jobs": 4,
            "max_concurrent_total": 100,
            "allowed_job_types": list(self.ALLOWED_JOB_TYPES),
            "deny_infrastructure_ops": True,
        }
        self._concurrent_gpu = 0
        self._policy_fingerprint = self._compute_fingerprint()

    def admit(self, job) -> dict:
        job_type = getattr(job, "job_type", None) or (job.payload.get("type") if hasattr(job, "payload") else None)
        if not job_type:
            return {"admitted": False, "reason": "no job_type specified"}

        if job_type not in self.ALLOWED_JOB_TYPES:
            return {"admitted": False, "reason": f"job_type '{job_type}' not in allowed list"}

        if job_type == "gpu":
            if self._concurrent_gpu >= self._rules["max_concurrent_gpu_jobs"]:
                return {"admitted": False, "reason": "GPU capacity reached"}

        payload = getattr(job, "payload", {})
        payload_str = json.dumps(payload, default=str)
        for kw in self.FORBIDDEN_KEYWORDS:
            if kw.lower() in payload_str.lower():
                return {"admitted": False, "reason": f"forbidden keyword: {kw}"}

        if job_type == "gpu":
            self._concurrent_gpu += 1

        return {"admitted": True, "reason": "policy_passed"}

    def release(self, job_type: str):
        if job_type == "gpu":
            self._concurrent_gpu = max(0, self._concurrent_gpu - 1)

    def update_rules(self, rules: dict):
        self._rules.update(rules)
        self._policy_fingerprint = self._compute_fingerprint()

    def get_active_policy(self) -> dict:
        return {"rules": self._rules, "fingerprint": self._policy_fingerprint}

    def _compute_fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self._rules, sort_keys=True).encode()
        ).hexdigest()
