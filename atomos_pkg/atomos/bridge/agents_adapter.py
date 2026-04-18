"""
Agents Adapter — Safe, Deterministic Import Bridge
=================================================

Loads PolicyKernelV4 from agents/policy_kernel_v4.py WITHOUT sys.path mutation.

Uses importlib.util for explicit module loading — no side effects on sys.path.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

_AGENTS_PATH = Path("/home/workspace/agents")
_POLICY_KERNEL_V4_PATH = _AGENTS_PATH / "policy_kernel_v4.py"

# Lazy-loaded references
_PolicyKernelV4: Optional[type] = None
_kernel_cache: dict = {}


def _resolve_agents_path() -> Path:
    """Resolve the agents directory path."""
    if _AGENTS_PATH.exists() and _AGENTS_PATH.is_dir():
        return _AGENTS_PATH
    raise RuntimeError(
        f"agents/ directory not found at {_AGENTS_PATH}. "
        "Cannot load PolicyKernelV4."
    )


def load_policy_kernel_v4(
    cache: bool = True,
    sandboxed: bool = False,
) -> "PolicyKernelV4":
    """
    Load PolicyKernelV4 from agents/policy_kernel_v4.py via importlib.

    Args:
        cache: Re-use a cached instance (default True). Pass False to force reload.
        sandboxed: If True, wrap instance in sandboxed proxy (future work).

    Returns:
        PolicyKernelV4 instance.

    Raises:
        RuntimeError: If agents/policy_kernel_v4.py is not found or fails to load.
    """
    global _PolicyKernelV4, _kernel_cache

    if cache and "pk_v4" in _kernel_cache:
        return _kernel_cache["pk_v4"]

    if _PolicyKernelV4 is None:
        # Step 1: verify file exists
        if not _POLICY_KERNEL_V4_PATH.exists():
            raise RuntimeError(
                f"PolicyKernelV4 not found at {_POLICY_KERNEL_V4_PATH}. "
                "Check that agents/policy_kernel_v4.py exists."
            )

        # Step 2: load module spec explicitly (no sys.path modification)
        spec = importlib.util.spec_from_file_location(
            "policy_kernel_v4",
            _POLICY_KERNEL_V4_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Failed to create module spec for {_POLICY_KERNEL_V4_PATH}."
            )

        # Step 3: execute module into isolated namespace
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Step 4: extract the class
        if not hasattr(module, "PolicyKernelV4"):
            available = [
                name
                for name in dir(module)
                if not name.startswith("_")
            ]
            raise RuntimeError(
                f"policy_kernel_v4.py has no 'PolicyKernelV4' class. "
                f"Available: {available}"
            )
        _PolicyKernelV4 = module.PolicyKernelV4

    # Step 5: instantiate
    instance = _PolicyKernelV4()

    if cache:
        _kernel_cache["pk_v4"] = instance

    return instance


def invalidate_cache() -> None:
    """Force next load_policy_kernel_v4() to reload from disk."""
    global _PolicyKernelV4, _kernel_cache
    _PolicyKernelV4 = None
    _kernel_cache.clear()


def list_loaded_agents_modules() -> list[str]:
    """Return names of known modules in agents/ directory."""
    if not _AGENTS_PATH.exists():
        return []
    return [
        f.stem
        for f in _AGENTS_PATH.iterdir()
        if f.is_file() and f.suffix == ".py" and not f.name.startswith("_")
    ]
