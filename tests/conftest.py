import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent

try:
    import kubernetes as _k8s_pkg
    _k8s_path = Path(_k8s_pkg.__file__).parent
    sys.path.insert(0, str(_k8s_path.parent))
except ImportError:
    pass

sys.path.insert(0, str(_ROOT / "kubernetes"))
