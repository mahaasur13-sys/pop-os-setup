"""Tests for Phase 3 validator system."""

import pytest
from phase3.validator.gate_engine import GateEngine, ValidationReport
from phase3.validator.gates.graph_gate import GraphGate
from phase3.validator.gates.policy_gate import PolicyGate
from phase3.validator.gates.diff_gate import DiffGate
from phase3.validator.gates.determinism_gate import DeterminismGate
from phase3.validator.gates.safety_gate import SafetyGate
from phase3.exceptions import ValidationError


class TestGateEngine:
    """Tests for GateEngine."""
    
    def test_validate_with_no_gates_raises(self):
        """Validate must fail if no gates registered."""
        engine = GateEngine()
        plan = {"actions": []}
        snapshot = {}
        
        with pytest.raises(ValidationError, match="No gates registered"):
            engine.validate(plan, snapshot)
    
    def test_validate_with_invalid_plan_raises(self):
        """Validate must fail if plan is invalid."""
        engine = GateEngine()
        engine.register_gate(GraphGate())
        plan = {}  # Missing 'actions'
        snapshot = {}
        
        with pytest.raises(ValidationError, match="Plan must be a dict with 'actions'"):
            engine.validate(plan, snapshot)
    
    def test_validate_all_gates_pass(self):
        """All gates pass → validation passes."""
        engine = GateEngine()
        engine.register_gate(GraphGate())
        engine.register_gate(SafetyGate())
        
        plan = {"actions": [], "risk": 0.0}
        snapshot = {
            "graph_nodes": [{"module_name": "test", "file_path": "test.py", "node_type": "core"}],
            "graph_edges": []
        }
        
        report = engine.validate(plan, snapshot)
        
        assert report.passed is True
        assert len(report.failed_gates) == 0
    
    def test_validate_one_gate_fails(self):
        """One gate fails → validation fails."""
        engine = GateEngine()
        engine.register_gate(GraphGate())
        engine.register_gate(SafetyGate(risk_threshold=0.3))
        
        plan = {"actions": [], "risk": 0.8}  # High risk
        snapshot = {"graph_nodes": [], "graph_edges": []}
        
        report = engine.validate(plan, snapshot)
        
        assert report.passed is False
        assert "safety_gate" in report.failed_gates
        assert report.risk_score > 0.0
    
    def test_validation_report_raise_if_failed(self):
        """raise_if_failed must raise when validation fails."""
        engine = GateEngine()
        engine.register_gate(SafetyGate(risk_threshold=0.3))
        
        plan = {"actions": [], "risk": 0.8}
        snapshot = {}
        
        report = engine.validate(plan, snapshot)
        
        with pytest.raises(ValidationError, match="Validation failed"):
            report.raise_if_failed()
    
    def test_validation_report_no_raise_if_passed(self):
        """raise_if_failed must NOT raise when validation passes."""
        engine = GateEngine()
        engine.register_gate(SafetyGate())
        
        plan = {"actions": [], "risk": 0.0}
        snapshot = {}
        
        report = engine.validate(plan, snapshot)
        report.raise_if_failed()  # No exception


class TestGraphGate:
    """Tests for GraphGate."""
    
    def test_valid_graph_passes(self):
        """Valid graph with no cycles passes."""
        gate = GraphGate()
        plan = {"actions": []}
        snapshot = {
            "graph_nodes": [
                {"module_name": "a", "file_path": "a.py", "node_type": "core"},
                {"module_name": "b", "file_path": "b.py", "node_type": "service"}
            ],
            "graph_edges": [
                {"from_node": "a", "to_node": "b", "dependency_type": "import"}
            ]
        }
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is True
    
    def test_cycle_detected_fails(self):
        """Cycle in graph fails the gate."""
        gate = GraphGate()
        plan = {"actions": []}
        snapshot = {
            "graph_nodes": [
                {"module_name": "a", "file_path": "a.py", "node_type": "core"},
                {"module_name": "b", "file_path": "b.py", "node_type": "service"},
                {"module_name": "c", "file_path": "c.py", "node_type": "utility"}
            ],
            "graph_edges": [
                {"from_node": "a", "to_node": "b", "dependency_type": "import"},
                {"from_node": "b", "to_node": "c", "dependency_type": "import"},
                {"from_node": "c", "to_node": "a", "dependency_type": "import"}  # Cycle!
            ]
        }
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is False
        assert "cycle" in result.reason.lower()
        assert result.severity == "high"


class TestSafetyGate:
    """Tests for SafetyGate."""
    
    def test_low_risk_passes(self):
        """Low risk plan passes."""
        gate = SafetyGate(risk_threshold=0.5)
        plan = {"actions": [], "risk": 0.2}
        snapshot = {}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is True
    
    def test_high_risk_fails(self):
        """High risk plan fails."""
        gate = SafetyGate(risk_threshold=0.5)
        plan = {"actions": [], "risk": 0.8}
        snapshot = {}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is False
        assert "exceeds threshold" in result.reason
    
    def test_high_risk_action_without_justification_fails(self):
        """High risk action without justification fails."""
        gate = SafetyGate()
        plan = {
            "actions": [
                {"type": "delete_node", "node": "test_module"}
            ],
            "risk": 0.0
        }
        snapshot = {}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is False
        assert "without justification" in result.reason


class TestDiffGate:
    """Tests for DiffGate."""
    
    def test_small_patch_passes(self):
        """Small file count passes."""
        gate = DiffGate(max_files=10)
        plan = {
            "actions": [
                {"type": "modify_file", "file_path": "a.py"},
                {"type": "modify_file", "file_path": "b.py"}
            ]
        }
        snapshot = {}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is True
    
    def test_large_patch_fails(self):
        """Too many files fails."""
        gate = DiffGate(max_files=5)
        plan = {
            "actions": [
                {"type": "modify_file", "file_path": f"{i}.py"}
                for i in range(10)
            ]
        }
        snapshot = {}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is False
        assert "modifies 10 files" in result.reason


class TestDeterminismGate:
    """Tests for DeterminismGate."""
    
    def test_deterministic_plan_passes(self):
        """Deterministic plan passes."""
        gate = DeterminismGate(runs=2)
        plan = {
            "actions": [
                {"type": "create_node", "node": {"module_name": "test", "file_path": "test.py", "node_type": "core"}}
            ]
        }
        snapshot = {"graph_nodes": [], "graph_edges": [], "diffs": []}
        
        result = gate.check(plan, snapshot)
        
        assert result.passed is True


class TestIntegration:
    """Integration tests for full pipeline."""
    
    def test_valid_patch_passes_through_pipeline(self):
        """Valid patch passes all gates and executes."""
        engine = GateEngine()
        engine.register_gate(GraphGate())
        engine.register_gate(SafetyGate())
        
        plan = {
            "actions": [
                {"type": "modify_file", "file_path": "test.py"}
            ],
            "risk": 0.1
        }
        snapshot = {
            "graph_nodes": [],
            "graph_edges": [],
            "diffs": [],
            "drift_score": 0.1
        }
        
        report = engine.validate(plan, snapshot)
        
        assert report.passed is True
        report.raise_if_failed()  # Must not raise
    
    def test_invalid_patch_blocked_at_validator(self):
        """Invalid patch blocked at validator — executor must not run."""
        engine = GateEngine()
        engine.register_gate(GraphGate())
        engine.register_gate(SafetyGate(risk_threshold=0.5))
        
        plan = {
            "actions": [],
            "risk": 0.9  # Too high
        }
        snapshot = {
            "graph_nodes": [],
            "graph_edges": []
        }
        
        report = engine.validate(plan, snapshot)
        
        # Validation must fail
        assert report.passed is False
        
        # Executor would raise ExecutionBlockedError if called
        from phase3.exceptions import ExecutionBlockedError
        with pytest.raises(ValidationError):
            report.raise_if_failed()
