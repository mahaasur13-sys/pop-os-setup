"""
Tests for Phase 4 Validation Gate components.
Run with: pytest tests/test_validation_gate.py -v
"""

import pytest
import tempfile
import hashlib
import json
import os
import time

# conftest.py already sets sys.path — no need to duplicate here.


class TestPreflightGate:
    """Test pre-flight rejection correctness."""

    def test_gpu_job_passes_preflight(self):
        from validation import PreflightGate
        from control_plane import Scheduler

        scheduler = Scheduler()
        preflight = PreflightGate()
        job_id = scheduler.submit({"type": "gpu", "priority": "HIGH", "payload": {"__sandbox_fp__": "a" * 64}})
        job = scheduler._jobs[job_id]

        report = preflight.verify(job, {"queue_depth": {"HIGH": 0}})
        assert report.gate_result.value == "PASS"

    def test_unknown_type_rejected_at_preflight(self):
        from validation import PreflightGate
        from control_plane.scheduler import Job

        preflight = PreflightGate()
        job = Job(job_type="malware", priority=1, payload={})
        report = preflight.verify(job)
        assert report.gate_result.value == "FAIL"
        assert "policy_admission" in report.rejection_reason

    def test_infra_leak_rejected(self):
        from validation import PreflightGate
        from control_plane.scheduler import Job

        preflight = PreflightGate()
        job = Job(job_type="gpu", priority=1, payload={"kubectl": "delete pods --all", "__sandbox_fp__": "a" * 64})
        report = preflight.verify(job)
        assert report.gate_result.value == "FAIL"
        assert "infra_leakage" in report.rejection_reason

    def test_no_sandbox_fp_rejected(self):
        from validation import PreflightGate, GateResult
        from control_plane.scheduler import Job

        preflight = PreflightGate()
        job = Job(job_type="cpu", priority=1, payload={})
        report = preflight.verify(job)
        assert report.gate_result.value == "FAIL"

    def test_queue_saturation_rejected(self):
        from validation import PreflightGate, GateResult
        from control_plane.scheduler import Job

        preflight = PreflightGate()
        job = Job(job_type="cpu", priority=1, payload={"__sandbox_fp__": "a" * 64})
        saturated_state = {"queue_depth": {"HIGH": 15000}}
        report = preflight.verify(job, saturated_state)
        assert report.gate_result.value == "FAIL"


class TestRuntimeMonitor:
    """Test runtime kill-switch activation."""

    def test_clean_job_not_killed(self):
        from validation import RuntimeMonitor

        monitor = RuntimeMonitor()
        job_id = "test-clean-job"
        monitor.start_monitoring(job_id)
        monitor.check_violation(job_id, {"type": "gpu", "model": "llama3"})
        is_killed = monitor.is_killed(job_id)
        monitor.stop_monitoring(job_id)
        assert is_killed is False

    def test_subprocess_pattern_triggers_kill(self):
        from validation import RuntimeMonitor

        monitor = RuntimeMonitor()
        job_id = "test-subprocess-job"
        monitor.start_monitoring(job_id)
        monitor.check_violation(job_id, {"type": "gpu", "script": "import subprocess; subprocess.run(['rm', '-rf', '/'])"})
        time.sleep(0.1)
        is_killed = monitor.is_killed(job_id)
        monitor.stop_monitoring(job_id)
        assert is_killed is True

    def test_ctypes_import_triggers_kill(self):
        from validation import RuntimeMonitor

        monitor = RuntimeMonitor()
        job_id = "test-ctypes-job"
        monitor.start_monitoring(job_id)
        monitor.check_violation(job_id, {"type": "gpu", "code": "import ctypes; ctypes.CDLL('lib.so')"})
        time.sleep(0.1)
        is_killed = monitor.is_killed(job_id)
        monitor.stop_monitoring(job_id)
        assert is_killed is True

    def test_gpu_oversub_triggers_kill(self):
        from validation import RuntimeMonitor

        monitor = RuntimeMonitor()
        job_id = "test-gpu-oversub"
        monitor.start_monitoring(job_id, {"gpu_percent": 50})
        monitor.check_violation(job_id, {}, current_metrics={"gpu_percent": 150, "cpu_percent": 10})
        time.sleep(0.1)
        is_killed = monitor.is_killed(job_id)
        monitor.stop_monitoring(job_id)
        assert is_killed is True

    def test_runtime_report_execution_hash(self):
        from validation import RuntimeMonitor

        monitor = RuntimeMonitor()
        job_id = "test-report"
        monitor.start_monitoring(job_id)
        rpt = monitor.stop_monitoring(job_id)
        assert rpt.job_id == job_id
        assert len(rpt.execution_hash) == 64


class TestPostflightValidator:
    """Test post-flight validation mismatch detection."""

    def test_valid_output_passes(self):
        from validation import PostflightValidator

        validator = PostflightValidator()
        result = validator.validate(
            job_id="test-valid",
            expected_output_schema={"required": ["result"]},
            actual_output={"result": "ok", "data": [1, 2, 3]},
        )
        assert result.valid is True

    def test_missing_required_field_fails(self):
        from validation import PostflightValidator

        validator = PostflightValidator()
        result = validator.validate(
            job_id="test-missing",
            expected_output_schema={"required": ["result", "status"]},
            actual_output={"result": "ok"},
        )
        assert result.valid is False
        assert "status" in result.details

    def test_deterministic_replay_mismatch(self):
        from validation import PostflightValidator

        validator = PostflightValidator()
        result = validator.validate(
            job_id="test-replay",
            actual_output={"result": "value_a"},
            baseline_output={"result": "value_b"},
        )
        assert result.valid is False
        assert "replay mismatch" in result.details

    def test_deterministic_replay_match(self):
        from validation import PostflightValidator

        validator = PostflightValidator()
        same_data = {"result": "consistent", "score": 0.95}
        result = validator.validate(
            job_id="test-replay-ok",
            actual_output=same_data,
            baseline_output=same_data,
        )
        assert result.valid is True

    def test_malformed_execution_hash_fails(self):
        from validation import PostflightValidator

        validator = PostflightValidator()
        result = validator.validate(
            job_id="test-hash",
            execution_proof={"job_id": "test-hash", "input_hash": "abc", "execution_hash": "short"},
        )
        assert result.valid is False


class TestAnomalyDetector:
    """Test behavioral drift detection."""

    def test_baseline_recording(self):
        from validation import AnomalyDetector

        detector = AnomalyDetector()
        for i in range(20):
            detector.record_metric("job1", "cpu_percent", 50.0 + (i % 3))
        baseline = detector.get_baseline("job1", "cpu_percent")
        assert baseline is not None
        assert baseline["samples"] == 20

    def test_spike_detected(self):
        from validation import AnomalyDetector

        detector = AnomalyDetector()
        for _ in range(20):
            detector.record_metric("job2", "cpu_percent", 50.0)
        events = detector.detect_drift("job2", {"cpu_percent": 500.0})
        assert len(events) > 0
        assert events[0].drift_score > 0.0

    def test_no_drift_on_normal_values(self):
        from validation import AnomalyDetector

        detector = AnomalyDetector()
        for _ in range(20):
            detector.record_metric("job3", "cpu_percent", 50.0)
        events = detector.detect_drift("job3", {"cpu_percent": 52.0})
        assert len(events) == 0


class TestEnforcementKernel:
    """Test enforcement severity actions."""

    def test_low_severity_logs_warning(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        action = kernel.enforce("job1", EnforcementSeverity.LOW, "minor concern")
        assert action.action_type == "warn"
        assert action.job_id == "job1"

    def test_medium_blocks_retry(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        kernel.enforce("job2", EnforcementSeverity.MEDIUM, "medium issue")
        assert kernel.is_job_blocked("job2") is True

    def test_high_terminates(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        terminated = []

        def fake_terminate(job_id):
            terminated.append(job_id)

        kernel.register_callback("terminate", fake_terminate)
        action = kernel.enforce("job3", EnforcementSeverity.HIGH, "high violation")
        assert action.action_type == "terminate"
        assert "job3" in terminated

    def test_critical_freezes_control_plane(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        kernel.enforce("job4", EnforcementSeverity.CRITICAL, "critical breach")
        frozen, reason = kernel.is_frozen()
        assert frozen is True
        assert "critical" in reason.lower()

    def test_unfreeze_restores(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        kernel.enforce("job5", EnforcementSeverity.CRITICAL, "breach")
        kernel.unfreeze("manual")
        frozen, _ = kernel.is_frozen()
        assert frozen is False

    def test_action_log_tracked(self):
        from validation import EnforcementKernel, EnforcementSeverity

        kernel = EnforcementKernel()
        kernel.enforce("job6", EnforcementSeverity.LOW, "test")
        log = kernel.get_action_log(job_id="job6")
        assert len(log) == 1


class TestValidationGatePipeline:
    """Test the full strict sequential pipeline."""

    def test_valid_job_passes_full_pipeline(self):
        from validation import ValidationGate
        from control_plane import Scheduler

        gate = ValidationGate()
        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {"__sandbox_fp__": "a" * 64, "model": "llama3"},
        })
        job = scheduler._jobs[job_id]

        preflight_report = gate.run_preflight(job, {"queue_depth": {"HIGH": 0}})
        assert preflight_report.gate_result.value == "PASS"

        gate.start_runtime(job_id, {"cpu_percent": 10, "gpu_percent": 30})
        gate.check_runtime(job_id, job.payload, {"cpu_percent": 12, "gpu_percent": 35})
        violations, exec_hash = gate.stop_runtime(job_id)

        postflight = gate.run_postflight(job_id, None, {"result": "ok"}, {"result": "ok"})
        assert postflight.valid is True

    def test_blocked_job_fails_preflight(self):
        from validation import ValidationGate
        from control_plane import Scheduler
        from validation.enforcement_kernel import EnforcementSeverity

        gate = ValidationGate()
        gate.enforcement.enforce("blocked-job", EnforcementSeverity.MEDIUM, "blocked")
        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {"__sandbox_fp__": "a" * 64},
        })
        job = scheduler._jobs[job_id]

        report = gate.run_preflight(job)
        assert report.gate_result.value == "FAIL"
        assert "BLOCKED" in report.rejection_reason

    def test_full_pipeline_with_runtime_violation(self):
        from validation import ValidationGate
        from control_plane import Scheduler

        gate = ValidationGate()
        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {"__sandbox_fp__": "a" * 64, "script": "import subprocess"},
        })
        job = scheduler._jobs[job_id]

        preflight_report = gate.run_preflight(job, {"queue_depth": {"HIGH": 0}})
        assert preflight_report.gate_result.value == "PASS"

        gate.start_runtime(job_id)
        gate.check_runtime(job_id, job.payload)
        time.sleep(0.2)
        violations, exec_hash = gate.stop_runtime(job_id)

        assert len(violations) > 0

    def test_control_plane_freeze_rejects_all(self):
        from validation import ValidationGate
        from control_plane import Scheduler
        from validation.enforcement_kernel import EnforcementSeverity

        gate = ValidationGate()
        gate.enforcement.enforce("ANY", EnforcementSeverity.CRITICAL, "freeze all")
        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "cpu",
            "priority": "NORMAL",
            "payload": {"__sandbox_fp__": "b" * 64},
        })
        job = scheduler._jobs[job_id]

        report = gate.run_preflight(job)
        assert report.gate_result.value == "FAIL"
        assert "FROZEN" in report.rejection_reason


class TestExecutionProof:
    """Test execution proof consistency."""

    def test_proof_structure_complete(self):
        from validation import ValidationGate
        from control_plane import Scheduler

        gate = ValidationGate()
        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {"__sandbox_fp__": "c" * 64, "model": "test"},
        })
        job = scheduler._jobs[job_id]
        job_id_val = job.job_id

        gate.start_runtime(job_id_val, {"cpu_percent": 10})
        _, exec_hash = gate.stop_runtime(job_id_val)

        import hashlib, json
        output_hash = hashlib.sha256(json.dumps({"result": "ok"}, sort_keys=True).encode()).hexdigest()

        proof = gate._build_proof(job, gate.preflight._checked_jobs[job_id_val], exec_hash, output_hash, "")
        assert len(proof.input_hash) == 64
        assert len(proof.execution_hash) == 64
        assert proof.job_id == job_id_val


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
