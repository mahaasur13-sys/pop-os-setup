"""
Enforcement Kernel — Kill-Switch + Rollback Trigger Layer

Central enforcement authority for Phase 4.
Receives events from all validation layers and applies severity-based
enforcement actions: warnings, job termination, sandbox reset,
and full control-plane freeze.
"""

import hashlib
import json
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class EnforcementSeverity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class EnforcementAction:
    action_id: str
    job_id: Optional[str]
    severity: EnforcementSeverity
    action_type: str  # "warn" | "block_retry" | "terminate" | "sandbox_reset" | "freeze_control_plane"
    reason: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class EnforcementKernel:
    """
    Central kill-switch and rollback authority.
    All validation events flow through here for enforcement decisions.
    """

    def __init__(self):
        self._control_plane_frozen = False
        self._frozen_reason: Optional[str] = None
        self._blocked_jobs: set = set()
        self._action_log: list[EnforcementAction] = []
        self._lock = threading.Lock()
        self._callbacks: dict[str, list[Callable]] = {
            "terminate": [],
            "sandbox_reset": [],
            "freeze": [],
            "warn": [],
        }

    def register_callback(self, event_type: str, cb: Callable):
        if event_type in self._callbacks:
            self._callbacks[event_type].append(cb)

    def enforce(
        self,
        job_id: str,
        severity: EnforcementSeverity,
        reason: str,
        metadata: Optional[dict] = None,
    ) -> EnforcementAction:
        if self._control_plane_frozen and severity != EnforcementSeverity.CRITICAL:
            action = EnforcementAction(
                action_id=hashlib.sha256(f"{job_id}{time.time()}".encode()).hexdigest()[:16],
                job_id=job_id,
                severity=severity,
                action_type="deferred_during_freeze",
                reason=f"Deferred during freeze: {reason}",
                metadata=metadata or {},
            )
            with self._lock:
                self._action_log.append(action)
            return action

        action_type = self._severity_to_action(severity)
        action = EnforcementAction(
            action_id=hashlib.sha256(f"{job_id}{time.time()}".encode()).hexdigest()[:16],
            job_id=job_id,
            severity=severity,
            action_type=action_type,
            reason=reason,
            metadata=metadata or {},
        )

        with self._lock:
            self._action_log.append(action)

        if severity == EnforcementSeverity.CRITICAL:
            self._freeze_control_plane(reason)
        elif action_type == "terminate":
            self._do_terminate(job_id)
        elif action_type == "sandbox_reset":
            self._do_sandbox_reset(job_id)
        elif action_type == "block_retry":
            self._blocked_jobs.add(job_id)

        for cb in self._callbacks.get(action_type, []):
            try:
                cb(action)
            except Exception:
                pass

        return action

    def _severity_to_action(self, severity: EnforcementSeverity) -> str:
        mapping = {
            EnforcementSeverity.LOW: "warn",
            EnforcementSeverity.MEDIUM: "block_retry",
            EnforcementSeverity.HIGH: "terminate",
            EnforcementSeverity.CRITICAL: "freeze_control_plane",
        }
        return mapping[severity]

    def _do_terminate(self, job_id: str):
        for cb in self._callbacks["terminate"]:
            try:
                cb(job_id)
            except Exception:
                pass

    def _do_sandbox_reset(self, job_id: str):
        for cb in self._callbacks["sandbox_reset"]:
            try:
                cb(job_id)
            except Exception:
                pass

    def _freeze_control_plane(self, reason: str):
        with self._lock:
            self._control_plane_frozen = True
            self._frozen_reason = reason
        for cb in self._callbacks["freeze"]:
            try:
                cb(reason)
            except Exception:
                pass

    def unfreeze(self, reason: str = "manual_unfreeze"):
        with self._lock:
            self._control_plane_frozen = False
            self._frozen_reason = None
        return EnforcementAction(
            action_id=hashlib.sha256(f"unfreeze{time.time()}".encode()).hexdigest()[:16],
            job_id=None,
            severity=EnforcementSeverity.LOW,
            action_type="unfreeze",
            reason=reason,
        )

    def is_job_blocked(self, job_id: str) -> bool:
        return job_id in self._blocked_jobs

    def is_frozen(self) -> tuple[bool, Optional[str]]:
        return self._control_plane_frozen, self._frozen_reason

    def get_action_log(self, job_id: Optional[str] = None) -> list[EnforcementAction]:
        with self._lock:
            if job_id is None:
                return list(self._action_log)
            return [a for a in self._action_log if a.job_id == job_id]

    def clear_block(self, job_id: str):
        with self._lock:
            self._blocked_jobs.discard(job_id)
