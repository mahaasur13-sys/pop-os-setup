"""Shared dataclasses and models for SDLC OS."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import json
from datetime import datetime, timezone


class NodeType(Enum):
    """Type classification for graph nodes."""
    CORE = "core"
    SERVICE = "service"
    UTILITY = "utility"
    INFRA = "infra"
    UNKNOWN = "unknown"


class DependencyType(Enum):
    """Classification of dependency relationships."""
    IMPORT = "import"
    RUNTIME = "runtime"
    CONFIG = "config"
    DATA = "data"


class DiffType(Enum):
    """Classification of semantic diff types."""
    STRUCTURAL = "structural"
    BEHAVIORAL = "behavioral"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"


class Severity(Enum):
    """Severity levels for drift signals."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DriftLevel(Enum):
    """System drift classification."""
    STABLE = "stable"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class Node:
    """Represents a module/file node in the dependency graph."""
    module_name: str
    file_path: str
    node_type: NodeType
    line_count: int = 0
    imports: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['node_type'] = self.node_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'Node':
        data['node_type'] = NodeType(data['node_type'])
        return cls(**data)


@dataclass
class Edge:
    """Represents a dependency edge between nodes."""
    from_node: str
    to_node: str
    dependency_type: DependencyType

    def to_dict(self) -> dict:
        d = asdict(self)
        d['dependency_type'] = self.dependency_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'Edge':
        data['dependency_type'] = DependencyType(data['dependency_type'])
        return cls(**data)


@dataclass
class SemanticDiff:
    """Represents a classified semantic change."""
    diff_type: DiffType
    severity: Severity
    affected_nodes: list[str]
    description: str
    file_paths: list[str] = field(default_factory=list)
    change_count: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d['diff_type'] = self.diff_type.value
        d['severity'] = self.severity.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'SemanticDiff':
        data['diff_type'] = DiffType(data['diff_type'])
        data['severity'] = Severity(data['severity'])
        return cls(**data)


@dataclass
class DriftSignal:
    """Represents a detected drift anomaly."""
    signal_type: str
    level: DriftLevel
    affected_components: list[str]
    description: str
    drift_score_delta: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d['level'] = self.level.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'DriftSignal':
        data['level'] = DriftLevel(data['level'])
        return cls(**data)


@dataclass
class SystemStateSnapshot:
    """
    Canonical system state representation.
    This is the primary output of the SDLC OS scan.
    """
    graph_nodes: list[dict]
    graph_edges: list[dict]
    diffs: list[dict]
    drift_score: float
    drift_level: DriftLevel
    anomalies: list[dict]
    metrics: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    repo_path: str = ""

    def to_dict(self) -> dict:
        return {
            'graph_nodes': self.graph_nodes,
            'graph_edges': self.graph_edges,
            'diffs': self.diffs,
            'drift_score': self.drift_score,
            'drift_level': self.drift_level.value,
            'anomalies': self.anomalies,
            'metrics': self.metrics,
            'timestamp': self.timestamp,
            'repo_path': self.repo_path
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str) -> None:
        with open(path, 'w') as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: dict) -> 'SystemStateSnapshot':
        data['drift_level'] = DriftLevel(data['drift_level'])
        return cls(**data)