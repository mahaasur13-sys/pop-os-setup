"""
Bridge contract — atomos_pkg → agents/ substrate.

Single, explicit entry point for PolicyKernelV4 and other agents/ exports.
No sys.path manipulation. No implicit imports.

Usage:
    from atomos.bridge.policy_bridge import get_policy_kernel

    pk = get_policy_kernel()   # returns PolicyKernelV4 singleton
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING

# ── Resolve agents/ substrate path ─────────────────────────────────────────────
_AGENTS_ROOT = Path("/home/workspace/agents")
if not _AGENTS_ROOT.exists():
    raise RuntimeError(
        f"Bridge failure: agents/ substrate not found at {_AGENTS_ROOT}. "
        "Ensure /home/workspace/agents exists."
    )


def _import_file(module_name: str, file_path: Path):
    """Import a Python module directly from an absolute file path.

    Equivalent to: importlib.import_module(module_name)
    but loads from explicit file, bypassing sys.path.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot create module spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    # Add to sys.modules so subsequent imports (if any) hit the cached version
    import sys
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def get_policy_kernel():
    """Return a PolicyKernelV4 instance.

    Module is loaded once and cached in sys.modules under 'agents.policy_kernel_v4'.
    Returns
    -------
    PolicyKernelV4
        Initialised instance (singleton per process).

    Raises
    ------
    RuntimeError
        If agents/policy_kernel_v4.py is missing or cannot be loaded.
    """
    cached_name = "agents.policy_kernel_v4"
    if cached_name in import.modules:   # type: ignore[attr-defined]
        return import.modules[cached_name].PolicyKernelV4()

    pk_path = _AGENTS_ROOT / "policy_kernel_v4.py"
    if not pk_path.exists():
        raise RuntimeError(
            f"Bridge failure: PolicyKernelV4 not found at {pk_path}"
        )

    _import_file("agents.policy_kernel_v4", pk_path)
    import agents.policy_kernel_v4 as pk_mod   # noqa: E402  (sys.modules hit)
    return pk_mod.PolicyKernelV4()


if TYPE_CHECKING:
    from agents.policy_kernel_v4 import PolicyKernelV4  # noqa: F401