"""
ATOMOS Bridge Layer — Runtime Boundary Normalization
=====================================================

Provides controlled, deterministic import paths between:
  - atomos_pkg (structured runtime)
  - agents/    (flat compute substrate)

No sys.path mutation at runtime. All imports go through this layer.
"""

from atomos.bridge.agents_adapter import load_policy_kernel_v4
from atomos.bridge.sbs_adapter import get_sbs_runtime

__all__ = [
    "load_policy_kernel_v4",
    "get_sbs_runtime",
]
