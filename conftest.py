import sys
from pathlib import Path
import importlib

_ROOT = Path(__file__).parent

# Find pip-installed kubernetes package path
try:
    import kubernetes as _k8s_pkg
    _k8s_path = Path(_k8s_pkg.__file__).parent
    # Prepend pip path FIRST so 'from kubernetes import client' uses pip package
    sys.path.insert(0, str(_k8s_path.parent))
except ImportError:
    pass  # kubernetes not installed — tests will fail anyway

# Now add local atom_operator so 'from atom_operator...' works
sys.path.insert(0, str(_ROOT / "kubernetes"))
