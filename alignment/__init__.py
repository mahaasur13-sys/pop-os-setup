"""
alignment/ — v10.0 Reality Alignment Layer

Closed-loop self-correction for atom-federation-os.

Modules:
    drift_detector.py          — L1/L2/L3 drift detection + DriftEngine
    plan_reality_comparator.py — binds PlannedDAG ↔ ExecutionTrace
    rollback_engine_v2.py      — branching rollback (never deletes events)
"""
from .drift_detector import (
    DriftType,
    DriftSeverity,
    ExecutedNode,
    ExecutionTrace,
    PlannedNode,
    PlannedDAG,
    Layer1Result,
    Layer2Result,
    Layer3Result,
    CompositeDriftReport,
    StructuralDriftDetector,
    CausalOrderDriftDetector,
    SemanticFidelityDetector,
    DriftEngine,
)
from .plan_reality_comparator import (
    NodeMapping,
    CausalBinding,
    PlanRealityBinding,
    PlanRealityComparator,
)
from .rollback_engine_v2 import (
    RollbackType,
    RollbackScope,
    RollbackPlan,
    RollbackResult,
    RollbackDecider,
    RollbackPlanner,
    RollbackExecutor,
)
