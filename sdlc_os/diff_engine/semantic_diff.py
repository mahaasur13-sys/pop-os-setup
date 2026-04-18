"""Semantic diff engine for change classification."""

from __future__ import annotations

from ..sdlc_types import SemanticDiff, DiffType, Severity
from typing import Optional


class ChangeClassifier:
    """
    Classifies file changes into semantic categories.
    
    Categories:
    - STRUCTURAL: new module, deletion, file moves
    - BEHAVIORAL: logic changes, function changes
    - DEPENDENCY: import graph changes
    - CONFIGURATION: config file changes
    """

    STRUCTURAL_PATTERNS = [
        'new_file', 'deleted_file', 'renamed_file',
        '__init__.py', '__main__.py'
    ]

    BEHAVIORAL_PATTERNS = [
        '.py', '.js', '.ts', '.go', '.rs', '.java'
    ]

    CONFIG_PATTERNS = [
        '.yaml', '.yml', '.json', '.toml', '.ini',
        '.env', '.cfg', '.conf', '.tf', '.tfvars',
        'Dockerfile', '.dockerfile', 'Makefile'
    ]

    def classify(self, change_type: str, file_path: str, diff_content: Optional[str] = None) -> SemanticDiff:
        """
        Classify a change into semantic type and severity.
        
        Args:
            change_type: type of change (added, modified, deleted, renamed)
            file_path: path to the changed file
            diff_content: optional diff content for deeper analysis
        
        Returns:
            SemanticDiff with classification
        """
        file_lower = file_path.lower()

        # Determine diff type
        diff_type = self._determine_diff_type(file_lower, change_type, diff_content)

        # Compute severity
        severity = self._compute_severity(diff_type, change_type, file_path)

        # Get affected nodes
        affected = self._extract_affected_nodes(file_path)

        return SemanticDiff(
            diff_type=diff_type,
            severity=severity,
            affected_nodes=affected,
            description=self._build_description(diff_type, change_type, file_path),
            file_paths=[file_path],
            change_count=1
        )

    def _determine_diff_type(self, file_lower: str, change_type: str, diff_content: Optional[str]) -> DiffType:
        """Determine the semantic diff type."""
        # Structural: new or deleted modules
        if change_type in ('added', 'deleted'):
            if any(p in file_lower for p in ['__init__', '__main__', 'test_', '_test.']):
                return DiffType.STRUCTURAL
            if any(p in file_lower for p in ['/core/', '/kernel/', '/engine/']):
                return DiffType.STRUCTURAL
            if any(p in file_lower for p in ['/models/', '/schemas/', '/types.py']):
                return DiffType.STRUCTURAL

        # Configuration files
        if any(p in file_lower for p in self.CONFIG_PATTERNS):
            return DiffType.CONFIGURATION

        # Behavioral: code files
        if any(p in file_lower for p in self.BEHAVIORAL_PATTERNS):
            return DiffType.BEHAVIORAL

        return DiffType.CONFIGURATION

    def _compute_severity(self, diff_type: DiffType, change_type: str, file_path: str) -> Severity:
        """Compute severity based on diff type and change type."""
        file_lower = file_path.lower()

        if change_type == 'deleted':
            return Severity.HIGH

        if diff_type == DiffType.STRUCTURAL:
            if any(p in file_lower for p in ['/core/', '/kernel/', '/main.py']):
                return Severity.HIGH
            return Severity.MEDIUM

        if diff_type == DiffType.CONFIGURATION:
            if 'terraform' in file_lower or 'ansible' in file_lower:
                return Severity.HIGH
            if 'dockerfile' in file_lower:
                return Severity.MEDIUM
            return Severity.LOW

        if diff_type == DiffType.BEHAVIORAL:
            if any(p in file_lower for p in ['/core/', '/engine/']):
                return Severity.MEDIUM
            return Severity.LOW

        return Severity.LOW

    def _extract_affected_nodes(self, file_path: str) -> list[str]:
        """Extract affected module nodes from file path."""
        parts = file_path.strip('/').split('/')
        # Return last 2 path components as node identifiers
        if len(parts) >= 2:
            return ['.'.join(parts[-2:]).replace('.py', '')]
        return [parts[-1]]

    def _build_description(self, diff_type: DiffType, change_type: str, file_path: str) -> str:
        """Build human-readable description."""
        action_map = {
            'added': 'Added',
            'modified': 'Modified',
            'deleted': 'Deleted',
            'renamed': 'Renamed'
        }
        action = action_map.get(change_type, change_type.capitalize())
        type_label = diff_type.value.capitalize()
        return f"{action} {type_label} change in {file_path}"


class SemanticDiffEngine:
    """
    Computes semantic diffs between system states.
    Uses git diff as input but produces classified semantic output.
    """

    def __init__(self):
        self.classifier = ChangeClassifier()

    def compute_diffs(self, changes: list[dict]) -> list[SemanticDiff]:
        """
        Compute semantic diffs from raw change list.
        
        Args:
            changes: list of dicts with 'type', 'path', 'diff' keys
        
        Returns:
            list of SemanticDiff objects
        """
        diffs = []
        for change in changes:
            semantic_diff = self.classifier.classify(
                change_type=change.get('type', 'modified'),
                file_path=change.get('path', ''),
                diff_content=change.get('diff')
            )
            diffs.append(semantic_diff)

        return diffs

    def aggregate_diffs(self, diffs: list[SemanticDiff]) -> dict:
        """
        Aggregate diffs by type for summary reporting.
        
        Returns:
            dict with counts by diff_type and severity
        """
        summary = {
            'by_type': {dt.value: 0 for dt in DiffType},
            'by_severity': {sv.value: 0 for sv in Severity},
            'total': len(diffs)
        }

        for d in diffs:
            summary['by_type'][d.diff_type.value] += 1
            summary['by_severity'][d.severity.value] += 1

        return summary