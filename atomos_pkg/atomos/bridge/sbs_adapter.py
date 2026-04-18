"""
SBS Adapter — Safe SBS Runtime Integration
==========================================

Loads SBS (System Boundary Spec) runtime WITHOUT sys.path mutation.
Replaces the broken /home/workspace/atom-federation-os import path.

SBS_AVAILABLE STATES:
  - AVAILABLE:     SBS runtime loaded and functional
  - NOT_INSTALLED: sbs package not installed (pip install sbs)
  - PATH_MISSING:  /home/workspace/atom-federation-os does not exist
  - LOAD_FAILED:   import failed for other reasons
"""

from __future__ import annotations

import os
import importlib
from enum import Enum
from typing import Any, Callable, Optional

_SBS_AVAILABLE = False
_SBSEnforcer: Optional[type] = None
_SBS_MODE: Optional[Any] = None
_InvariantViolation: Optional[type] = None
_ViolationPolicy: Optional[type] = None
_ExecutionStage: Optional[type] = None
_SystemBoundarySpec: Optional[type] = None
_GlobalInvariantEngine: Optional[type] = None


class SBSStatus(Enum):
    AVAILABLE = "available"
    NOT_INSTALLED = "not_installed"
    PATH_MISSING = "path_missing"
    LOAD_FAILED = "load_failed"


_SBS_STATUS = SBSStatus.NOT_INSTALLED
_SBS_ERROR_MSG: Optional[str] = None


def _build_collect_state(
    drl_ref: Callable,
    ccl_ref: Callable,
    f2_ref: Callable,
    desc_ref: Callable,
) -> Callable:
    """Build collect_state() closure over layer references."""
    def collect_state() -> dict:
        return {
            "drl": drl_ref() if callable(drl_ref) else drl_ref,
            "ccl": ccl_ref() if callable(ccl_ref) else ccl_ref,
            "f2": f2_ref() if callable(f2_ref) else f2_ref,
            "desc": desc_ref() if callable(desc_ref) else desc_ref,
        }
    return collect_state


def _do_import() -> bool:
    """Attempt to import SBS runtime. Returns True on success."""
    global _SBS_AVAILABLE, _SBSEnforcer, _SBS_MODE
    global _InvariantViolation, _ViolationPolicy, _ExecutionStage
    global _SystemBoundarySpec, _GlobalInvariantEngine
    global _SBS_STATUS, _SBS_ERROR_MSG

    sbs_path = "/home/workspace/atom-federation-os"

    if not os.path.exists(sbs_path):
        _SBS_STATUS = SBSStatus.PATH_MISSING
        _SBS_ERROR_MSG = f"SBS path does not exist: {sbs_path}"
        return False

    try:
        import sys
        # Temporarily extend path — scoped to this function only
        if sbs_path not in sys.path:
            sys.path.insert(0, sbs_path)

        from sbs import (
            SBSRuntimeEnforcer,
            SBS_MODE,
            InvariantViolation,
            ViolationPolicy,
            ExecutionStage,
            SystemBoundarySpec,
            GlobalInvariantEngine,
        )

        _SBSEnforcer = SBSRuntimeEnforcer
        _SBS_MODE = SBS_MODE
        _InvariantViolation = InvariantViolation
        _ViolationPolicy = ViolationPolicy
        _ExecutionStage = ExecutionStage
        _SystemBoundarySpec = SystemBoundarySpec
        _GlobalInvariantEngine = GlobalInvariantEngine
        _SBS_AVAILABLE = True
        _SBS_STATUS = SBSStatus.AVAILABLE
        return True

    except ImportError as e:
        _SBS_STATUS = SBSStatus.NOT_INSTALLED
        _SBS_ERROR_MSG = f"SBS package not installed or import error: {e}"
        return False
    except Exception as e:
        _SBS_STATUS = SBSStatus.LOAD_FAILED
        _SBS_ERROR_MSG = f"SBS load failed: {e}"
        return False


# Attempt import on module load
_do_import()


def get_sbs_runtime() -> dict:
    """
    Returns a dict with SBS runtime components and status.

    Use this instead of importing sbs directly.
    """
    return {
        "available": _SBS_AVAILABLE,
        "status": _SBS_STATUS.value,
        "error": _SBS_ERROR_MSG,
        "SBSRuntimeEnforcer": _SBSEnforcer,
        "SBS_MODE": _SBS_MODE,
        "InvariantViolation": _InvariantViolation,
        "ViolationPolicy": _ViolationPolicy,
        "ExecutionStage": _ExecutionStage,
        "SystemBoundarySpec": _SystemBoundarySpec,
        "GlobalInvariantEngine": _GlobalInvariantEngine,
        "collect_state_builder": _build_collect_state,
    }
