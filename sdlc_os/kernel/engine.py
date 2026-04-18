"""Kernel engine - orchestrates SDLC OS execution."""

from __future__ import annotations

from typing import Optional, Callable
from enum import Enum

from ..sdlc_types import SystemStateSnapshot, DriftLevel
from ..graph.dag import DAG, DependencyMapper
from ..diff_engine.semantic_diff import SemanticDiffEngine
from ..monitor.drift_detector import DriftDetector
from ..monitor.repo_scanner import RepoScanner


class ExecutionStage(Enum):
    """SDLC OS execution stages in order."""
    SCAN = "scan"
    BUILD_GRAPH = "build_graph"
    COMPUTE_DIFF = "compute_diff"
    DETECT_DRIFT = "detect_drift"
    ASSEMBLE_SNAPSHOT = "assemble_snapshot"


class Kernel:
    """
    SDLC OS Kernel - orchestrates the execution pipeline.
    
    Responsibilities:
    - Route execution steps in correct order
    - Enforce deterministic pipeline execution
    - Ensure all stages complete before output
    
    Kernel does NOT:
    - Modify any data
    - Perform healing or patching
    - Mutate graph state
    - Make autonomous decisions beyond routing
    """

    def __init__(self):
        self.scanner = RepoScanner()
        self.mapper = DependencyMapper()
        self.diff_engine = SemanticDiffEngine()
        self.drift_detector = DriftDetector()
        self._execution_log: list[dict] = []

    def execute(self, repo_path: str) -> SystemStateSnapshot:
        """
        Execute full SDLC OS scan pipeline.
        
        Pipeline stages (in order):
        1. SCAN - repository discovery
        2. BUILD_GRAPH - dependency mapping
        3. COMPUTE_DIFF - semantic change analysis
        4. DETECT_DRIFT - architecture drift detection
        5. ASSEMBLE_SNAPSHOT - produce canonical output
        
        Args:
            repo_path: path to repository
        
        Returns:
            SystemStateSnapshot - canonical system state
        """
        self._log_stage(ExecutionStage.SCAN, "starting")

        # Stage 1: Scan repository
        files = self.scanner.scan(repo_path)
        repo_stats = self.scanner.get_repo_stats(files)
        self._log_stage(ExecutionStage.SCAN, f"found {len(files)} files")

        # Stage 2: Build dependency graph
        self._log_stage(ExecutionStage.BUILD_GRAPH, "building DAG")
        nodes, edges = self.mapper.build_graph(files)
        dag = DAG()
        for node in nodes:
            dag.add_node(node)
        for edge in edges:
            try:
                dag.add_edge(edge)
            except Exception:
                pass  # Skip edges that would create cycles

        self._log_stage(ExecutionStage.BUILD_GRAPH, f"DAG: {dag.node_count()} nodes, {dag.edge_count()} edges")

        # Stage 3: Compute semantic diffs
        self._log_stage(ExecutionStage.COMPUTE_DIFF, "analyzing changes")
        diffs = []
        for f in files:
            from ..sdlc_types import DiffType, Severity
            diffs.append({
                'type': 'repository_scan',
                'path': f['path'],
                'diff': None
            })
        semantic_diffs = self.diff_engine.compute_diffs(diffs)
        diff_summary = self.diff_engine.aggregate_diffs(semantic_diffs)

        # Stage 4: Detect drift
        self._log_stage(ExecutionStage.DETECT_DRIFT, "computing drift score")
        snapshot = SystemStateSnapshot(
            graph_nodes=[n.to_dict() for n in nodes],
            graph_edges=[e.to_dict() for e in edges],
            diffs=[d.to_dict() for d in semantic_diffs],
            drift_score=0.0,
            drift_level=DriftLevel.STABLE,
            anomalies=[],
            metrics={
                'repo_stats': repo_stats,
                'diff_summary': diff_summary
            },
            repo_path=repo_path
        )

        drift_score, drift_level, anomalies = self.drift_detector.compute_drift(snapshot)
        self.drift_detector.update_previous_state(snapshot)

        snapshot.drift_score = drift_score
        snapshot.drift_level = drift_level
        snapshot.anomalies = [a.to_dict() for a in anomalies]

        # Stage 5: Assemble snapshot
        self._log_stage(ExecutionStage.ASSEMBLE_SNAPSHOT, "complete")

        return snapshot

    def _log_stage(self, stage: ExecutionStage, status: str) -> None:
        """Log execution stage for observability."""
        self._execution_log.append({
            'stage': stage.value,
            'status': status,
        })

    def get_execution_log(self) -> list[dict]:
        """Return execution log for debugging."""
        return self._execution_log


class Policy:
    """
    Policy engine for SDLC OS.
    Defines rules and thresholds for system behavior.
    """

    # Drift thresholds
    DRIFT_THRESHOLD_STABLE = 0.3
    DRIFT_THRESHOLD_DEGRADED = 0.7

    # Severity thresholds
    SEVERITY_THRESHOLDS = {
        'structural': 0.6,
        'behavioral': 0.4,
        'dependency': 0.5,
        'configuration': 0.3
    }

    @classmethod
    def is_acceptable_drift(cls, drift_score: float) -> bool:
        """Check if drift score is within acceptable range."""
        return drift_score < cls.DRIFT_THRESHOLD_STABLE

    @classmethod
    def requires_attention(cls, drift_score: float) -> bool:
        """Check if drift score requires attention."""
        return drift_score >= cls.DRIFT_THRESHOLD_STABLE

    @classmethod
    def is_critical(cls, drift_score: float) -> bool:
        """Check if drift score indicates critical state."""
        return drift_score >= cls.DRIFT_THRESHOLD_DEGRADED


class Router:
    """
    Routes execution based on system state and policy.
    Determines next action based on current snapshot.
    """

    def __init__(self):
        self.policy = Policy()

    def should_heal(self, snapshot: SystemStateSnapshot) -> bool:
        """
        Determine if healing should be triggered.
        MVP: Always False (healing not implemented yet).
        """
        # MVP does not implement healing
        return False

    def should_escalate(self, snapshot: SystemStateSnapshot) -> bool:
        """Determine if human escalation is needed."""
        return snapshot.drift_level == DriftLevel.CRITICAL

    def get_recommended_actions(self, snapshot: SystemStateSnapshot) -> list[str]:
        """
        Get list of recommended actions based on state.
        MVP: Returns observations only.
        """
        actions = []

        if snapshot.drift_score > 0:
            actions.append("Review drift score and anomalies")

        if snapshot.drift_level == DriftLevel.CRITICAL:
            actions.append("Investigate critical architectural drift")

        if len(snapshot.anomalies) > 0:
            actions.append(f"Analyze {len(snapshot.anomalies)} detected anomalies")

        return actions