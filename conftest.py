import sys
from pathlib import Path

_ROOT = Path(__file__).parent
print(f"[conftest] loaded from {_ROOT}, sys.path[:3] = {sys.path[:3]}")

# ← ДОБАВЛЕНО: приоритет для pip-пакета atomos_pkg с реальным ExecutionLoop
# atomos_pkg/ — это pip-пакет с реальным atomos.core.execution_loop.
# Добавляем atomos_pkg/ в sys.path (НЕ atomos_pkg/atomos/core).
# Это позволяет 'from atomos.core.execution_loop import ...' найти модуль.
sys.path.insert(0, str(_ROOT.parent / "atomos_pkg"))
print(f"[conftest] after atomos_pkg: sys.path[:3] = {sys.path[:3]}")

# Find pip-installed kubernetes package path
try:
    import kubernetes as _k8s_pkg
    _k8s_path = Path(_k8s_pkg.__file__).parent
    sys.path.insert(0, str(_k8s_path.parent))
except ImportError:
    pass

# Now add local atom_operator so 'from atom_operator...' works
sys.path.insert(0, str(_ROOT / "kubernetes"))