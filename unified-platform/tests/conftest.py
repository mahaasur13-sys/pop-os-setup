"""
conftest.py — pytest configuration

Must be loaded BEFORE any test module imports,
to ensure unified-platform root is on sys.path.
"""

import sys
import os

# Add unified-platform root so control_plane, validation, acos packages are importable
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
