#!/usr/bin/env python3
"""
ACOS Isolation Test — CI Gate G-001
====================================
ACOS modules MUST be pure computation.
They MUST NOT import any infra dependencies.

FORBIDDEN IMPORTS (enforced by CI):
    ✗ terraform
    ✗ ansible
    ✗ kubernetes / k8s
    ✗ kubectl
    ✗ infra
    ✗ infra_scripts

This test scans ALL acos*/ modules and verifies zero violations.
FAIL = CI HARD FAIL (blocks promotion)
"""

import ast
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Root of unified-platform
ROOT = Path(__file__).parent.parent

FORBIDDEN_IMPORTS = {
    "terraform",
    "ansible",
    "kubernetes",
    "k8s",
    "kubectl",
    "infra",
    "infra_scripts",
    "boto3",       # AWS SDK — not allowed in ACOS
    "docker",       # Docker SDK — not allowed in ACOS
    "subprocess",  # No shell execution in ACOS (safety)
}

# Modules that are allowed to import certain things
# (acos.py, acos_cli.py are entrypoints, not pure domain)
ACOS_PURE_DIRS = [
    ROOT / "acos",
    ROOT / "acos_v6",
    ROOT / "acos_v7",
    ROOT / "acos_v8",
]

# Files to skip (entrypoints, not pure domain)
SKIP_FILES = {
    "acos.py",
    "acos_cli.py",
    "acos_correction/rca_engine.py",
    "tests/acos_isolation.py",
}


class ImportScanner(ast.NodeVisitor):
    """AST visitor that collects import statements."""
    
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.imports: List[str] = []
        self.from_imports: List[str] = []
        self.violations: List[Tuple[str, str]] = []
    
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name.split('.')[0])
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.from_imports.append(node.module.split('.')[0])
        for alias in node.names:
            if node.module:
                self.from_imports.append(f"{node.module}.{alias.name}".split('.')[0])
        self.generic_visit(node)


def scan_file(filepath: Path) -> List[Tuple[str, str]]:
    """Scan a Python file for forbidden imports."""
    scanner = ImportScanner(filepath)
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read(), filename=str(filepath))
        scanner.visit(tree)
    except SyntaxError as e:
        return [(str(filepath), f"SYNTAX ERROR: {e}")]
    
    violations = []
    for imp in scanner.imports + scanner.from_imports:
        root = imp.split('.')[0]
        if root in FORBIDDEN_IMPORTS:
            violations.append((str(filepath), f"forbidden import: {imp}"))
    
    return violations


def scan_directory(directory: Path) -> List[Tuple[str, str]]:
    """Recursively scan directory for Python files."""
    all_violations = []
    for root, dirs, files in os.walk(directory):
        # Skip hidden and cache directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        
        for file in files:
            if not file.endswith('.py'):
                continue
            if file in SKIP_FILES:
                continue
            
            filepath = Path(root) / file
            # Skip if relative path matches skip pattern
            rel = str(filepath.relative_to(ROOT))
            if any(rel.startswith(s) for s in SKIP_FILES):
                continue
            
            violations = scan_file(filepath)
            all_violations.extend(violations)
    
    return all_violations


def test_acos_isolation():
    """
    Test: ACOS modules must NOT import infra dependencies.
    
    This is a CI HARD GATE (G-001).
    Failure blocks promotion to production.
    """
    print("\n" + "="*70)
    print("ACOS ISOLATION TEST — CI GATE G-001")
    print("="*70)
    
    all_violations = []
    
    for acos_dir in ACOS_PURE_DIRS:
        if not acos_dir.exists():
            print(f"\n⚠️  Directory not found: {acos_dir}")
            continue
        
        print(f"\n📁 Scanning: {acos_dir.relative_to(ROOT)}")
        violations = scan_directory(acos_dir)
        
        if violations:
            print(f"  ❌ {len(violations)} VIOLATION(S) FOUND")
            for filepath, msg in violations:
                rel_path = filepath.replace(str(ROOT) + "/", "")
                print(f"     - {rel_path}: {msg}")
            all_violations.extend(violations)
        else:
            print(f"  ✅ PASS — no violations")
    
    # Also scan domain/ai_scheduler for forbidden patterns
    ai_scheduler = ROOT / "domain" / "ai_scheduler"
    if ai_scheduler.exists():
        print(f"\n📁 Scanning: domain/ai_scheduler")
        violations = scan_directory(ai_scheduler)
        for filepath, msg in violations:
            rel_path = filepath.replace(str(ROOT) + "/", "")
            if "infra" in msg.lower() or "terraform" in msg.lower():
                print(f"  ❌ VIOLATION: {rel_path}: {msg}")
                all_violations.append((filepath, msg))
    
    print("\n" + "="*70)
    if all_violations:
        print(f"❌ FAILED — {len(all_violations)} violation(s) found")
        print("\nACOS ISOLATION VIOLATIONS DETECTED:")
        for filepath, msg in all_violations:
            print(f"  • {filepath}: {msg}")
        print("\n🔒 ACOS modules must be PURE COMPUTATION.")
        print("   They must NOT import infrastructure dependencies.")
        print("   This is a HARD CI GATE — fix violations before promoting.")
        print("="*70)
        
        # CI HARD FAIL
        assert False, f"ACOS isolation violated: {len(all_violations)} forbidden import(s) found"
    else:
        print("✅ PASSED — Zero violations")
        print("\n🔒 ACOS isolation confirmed: pure computation only")
        print("="*70)


if __name__ == "__main__":
    test_acos_isolation()
    print("\n✅ All ACOS isolation tests passed")
    sys.exit(0)
