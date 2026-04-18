"""
Control Plane — Policy Engine
Enforces ACOS governance rules on all job submissions.
This is the ONLY interface between control-plane and ACOS.
"""

from dataclasses import dataclass
from typing import Optional
import hashlib
import json

logger = __import__("logging").getLogger(__name__)


@dataclass
class PolicyResult:
    admitted: bool
    reason: Optional[str] = None
    constraints_applied: Optional[list[str]] = None
    policy_hash: Optional[str] = None


class PolicyEngine:
    """
    Policy engine that gates all job submissions.

    Responsibilities:
        1. Load ACOS policy rules (read-only, no subprocess)
        2. Evaluate job against policy constraints
        3. Return admission decision

    CRITICAL: This module MUST NOT call subprocess, os.system,
              or any infrastructure layer. It is purely analytical.
    """

    def __init__(self, policy_rules: Optional[dict] = None):
        self._rules = policy_rules or self._default_rules()
        self._policy_fingerprint = self._compute_fingerprint()

    def _default_rules(self) -> dict:
        """
        Default policy rules.
        In production these are loaded from core/governance.py.
        """
        return {
            "max_concurrent_gpu_jobs": 4,
            "max_queue_depth": 100,
            "allowed_job_types": ["gpu", "cpu", "batch", "inference"],
            "require_gpu_for_types": ["gpu", "inference"],
            "deny_infrastructure_access": True,
        }

    def _compute_fingerprint(self) -> str:
        """Hash of active policy rules for audit trail."""
        return hashlib.sha256(
            json.dumps(self._rules, sort_keys=True).encode()
        ).hexdigest()[:16]

    def admit(self, job) -> dict:
        """
        Evaluate job against policy rules.
        Returns dict with:
            - admitted: bool
            - reason: str (if rejected)
            - constraints_applied: list[str]
            - policy_hash: str
        """
        applied = []
        reasons = []

        # Rule 1: Check job type
        if job.job_type not in self._rules["allowed_job_types"]:
            return {
                "admitted": False,
                "reason": f"job_type '{job.job_type}' not in allowed list",
                "constraints_applied": [],
                "policy_hash": self._policy_fingerprint,
            }
        applied.append(f"type_check:{job.job_type}")

        # Rule 2: GPU availability check (analytical, no system call)
        if job.job_type in self._rules["require_gpu_for_types"]:
            gpu_available = self._check_gpu_analytical(job)
            if not gpu_available:
                return {
                    "admitted": False,
                    "reason": "no GPU capacity available",
                    "constraints_applied": applied,
                    "policy_hash": self._policy_fingerprint,
                }
            applied.append("gpu_check:available")

        # Rule 3: Infrastructure access gate
        if self._rules.get("deny_infrastructure_access"):
            infra_keywords = ["terraform", "kubectl", "ansible", "docker", "systemctl"]
            payload_str = json.dumps(job.payload, default=str).lower()
            if any(kw in payload_str for kw in infra_keywords):
                # Allow only if explicitly whitelisted in payload
                if not job.payload.get("__infra_whitelisted__"):
                    return {
                        "admitted": False,
                        "reason": "infrastructure operations require whitelist flag",
                        "constraints_applied": applied,
                        "policy_hash": self._policy_fingerprint,
                    }
            applied.append("infra_access:conditional")

        return {
            "admitted": True,
            "reason": None,
            "constraints_applied": applied,
            "policy_hash": self._policy_fingerprint,
        }

    def _check_gpu_analytical(self, job) -> bool:
        """
        Analytical GPU availability check.
        This is a heuristic — actual GPU scheduling goes through
        domain/ai_scheduler/job-router.py → Slurm.
        """
        # This should read from a shared state store (e.g., Redis, SLURM sview)
        # For now, allow all GPU jobs (actual scheduling deferred to job-router)
        return True

    def update_rules(self, new_rules: dict) -> str:
        """
        Update policy rules.
        Returns new policy fingerprint.
        """
        self._rules.update(new_rules)
        self._policy_fingerprint = self._compute_fingerprint()
        logger.info(f"Policy rules updated, fingerprint={self._policy_fingerprint}")
        return self._policy_fingerprint

    def get_active_policy(self) -> dict:
        """Return current policy rules and fingerprint."""
        return {
            "rules": self._rules,
            "fingerprint": self._policy_fingerprint,
        }
