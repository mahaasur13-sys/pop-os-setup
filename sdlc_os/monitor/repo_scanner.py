"""Repository scanner for SDLC OS."""

import os
import re
from typing import Optional
from pathlib import Path


class RepoScanner:
    """
    Scans repository and builds file inventory.
    Stateless - only produces file lists.
    """

    # File patterns for different languages
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java',
        '.cpp', '.c', '.h', '.hpp', '.cs', '.rb', '.php'
    }

    CONFIG_EXTENSIONS = {
        '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.conf',
        '.tf', '.tfvars', '.env'
    }

    INFRA_EXTENSIONS = {
        '.sh', '.dockerfile', 'dockerfile'
    }

    IGNORE_DIRS = {
        '.git', '__pycache__', '.pytest_cache', 'node_modules',
        '.venv', 'venv', '.tox', 'build', 'dist', '.eggs',
        '*.egg-info', '.mypy_cache', '.ruff_cache', '.terraform',
        'vendor', 'target', '.idea', '.vscode'
    }

    def __init__(self):
        self._import_patterns = {
            '.py': re.compile(r'^(?:from|import)\s+(\S+)', re.MULTILINE),
            '.js': re.compile(r'^(?:const|import|require)\s+[\'""]?(\S+)', re.MULTILINE),
            '.ts': re.compile(r'^(?:const|import|require)\s+[\'""]?(\S+)', re.MULTILINE),
            '.go': re.compile(r'^(?:import|require)\s+"?(\S+)', re.MULTILINE),
        }

    def scan(self, repo_path: str, max_depth: int = 10) -> list[dict]:
        """
        Scan repository and return file list with metadata.
        
        Args:
            repo_path: path to repository root
            max_depth: maximum directory traversal depth
        
        Returns:
            list of dicts with 'path', 'line_count', 'imports', 'extension'
        """
        files = []
        repo_path = Path(repo_path).resolve()

        for root, dirs, filenames in os.walk(repo_path):
            # Limit depth
            depth = len(Path(root).relative_to(repo_path).parts)
            if depth > max_depth:
                dirs.clear()
                continue

            # Filter ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith('.')]

            for filename in filenames:
                file_path = Path(root) / filename

                # Skip hidden files
                if filename.startswith('.'):
                    continue

                ext = file_path.suffix.lower()
                if ext not in self.CODE_EXTENSIONS and ext not in self.CONFIG_EXTENSIONS:
                    if not self._is_infra_file(filename):
                        continue

                file_info = self._extract_file_info(file_path)
                if file_info:
                    files.append(file_info)

        return files

    def _is_infra_file(self, filename: str) -> bool:
        """Check if filename indicates infrastructure file."""
        infra_names = {'dockerfile', 'makefile', 'jenkinsfile', 'taskfile'}
        return filename.lower() in infra_names

    def _extract_file_info(self, file_path: Path) -> Optional[dict]:
        """Extract metadata from a single file."""
        try:
            stat = file_path.stat()
            ext = file_path.suffix.lower()

            line_count = 0
            imports = []

            # Read and count lines for small files
            if stat.st_size < 1024 * 1024:  # < 1MB
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    line_count = len(content.splitlines())

                    # Extract imports
                    pattern = self._import_patterns.get(ext)
                    if pattern:
                        imports = pattern.findall(content)
                        imports = [i.split('.')[0] for i in imports if i]
                except Exception:
                    pass

            return {
                'path': str(file_path),
                'extension': ext,
                'size': stat.st_size,
                'line_count': line_count,
                'imports': imports[:20]  # Limit to 20 imports per file
            }
        except Exception:
            return None

    def get_repo_stats(self, files: list[dict]) -> dict:
        """
        Compute repository statistics from file list.
        
        Returns:
            dict with code_lines, file_count, lang_breakdown, etc.
        """
        stats = {
            'total_files': len(files),
            'code_lines': 0,
            'by_extension': {},
            'infra_files': 0
        }

        infra_extensions = {'.sh', '.tf', '.yaml', '.yml', '.dockerfile'}

        for f in files:
            stats['code_lines'] += f.get('line_count', 0)
            ext = f.get('extension', 'unknown')
            stats['by_extension'][ext] = stats['by_extension'].get(ext, 0) + 1
            if ext in infra_extensions:
                stats['infra_files'] += 1

        return stats