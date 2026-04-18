"""
Control Plane — ACOS Gateway
The ONLY interface between control-plane and ACOS subsystem.

ACOS (acos/) is a strictly isolated deterministic subsystem.
This gateway provides:
    1. Policy rule loading from ACOS contracts
    2. Constraint evaluation requests to ACOS
    3. Deterministic response parsing

CRITICAL BOUNDARY:
    - This gateway imports acos.* but ACOS never imports infra/*
    - No subprocess, os.system, or eval in this module
    - ACOS.compute() is the only allowed ACOS entry point
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ACOSGateway:
    """
    Canonical bridge between control-plane and ACOS.

    ACOS is treated as a PURE FUNCTION:
        input (constraints, context) → output (decision, score)

    It has NO side effects, NO infrastructure access, NO subprocess.
    """

    def __init__(self):
        self._acos = self._load_acos()

    def _load_acos(self):
        """
        Load ACOS subsystem.
        This is the ONLY import from acos/.
        """
        try:
            from acos.scl import AdaptiveConstraintOptimizationSystem
            return AdaptiveConstraintOptimizationSystem()
        except ImportError as e:
            logger.warning(f"ACOS not available: {e}, using fallback")
            return None

    def evaluate_constraints(self, constraints: list, context: dict) -> dict:
        """
        Evaluate constraints via ACOS.

        Args:
            constraints: List of constraint dicts
            context: Execution context (job spec, system state)

        Returns:
            ACOS decision dict with:
                - admitted: bool
                - score: float
                - violations: list[str]
                - corrections: list[str]
        """
        if self._acos is None:
            logger.warning("ACOS unavailable, using permissive fallback")
            return {
                "admitted": True,
                "score": 1.0,
                "violations": [],
                "corrections": [],
            }

        try:
            result = self._acos.compute(constraints=constraints, context=context)
            return result
        except Exception as e:
            logger.error(f"ACOS evaluation failed: {e}")
            return {
                "admitted": False,
                "score": 0.0,
                "violations": [f"acos_compute_error: {e}"],
                "corrections": [],
            }

    def get_governance_rules(self) -> dict:
        """
        Load governance rules from ACOS contracts.
        This is a READ-ONLY operation.
        """
        if self._acos is None:
            return self._default_governance()

        try:
            if hasattr(self._acos, "get_governance_rules"):
                return self._acos.get_governance_rules()
        except Exception as e:
            logger.warning(f"Could not load ACOS governance rules: {e}")

        return self._default_governance()

    def _default_governance(self) -> dict:
        """Fallback governance rules when ACOS unavailable."""
        return {
            "max_retries": 3,
            "timeout_seconds": 300,
            "deny_policy": [],
            "allow_policy": ["*"],
        }

    def health_check(self) -> dict:
        """Check ACOS subsystem health."""
        return {
            "acos_available": self._acos is not None,
            "gateway_operational": True,
        }
