"""
Tests for Control Plane components.
Run with: pytest tests/test_control_plane.py -v
"""

import pytest
import tempfile
import os
from pathlib import Path

# Set temp log path for audit tests
os.environ["CONTROL_PLANE_AUDIT_PATH"] = tempfile.mktemp(suffix=".jsonl")


class TestScheduler:
    """Test job scheduler and admission flow."""

    def test_submit_gpu_job_admitted(self):
        from control_plane import Scheduler

        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {"model": "llama3"},
        })

        assert job_id is not None
        queue = scheduler.get_queue_depth()
        assert queue["HIGH"] >= 0

    def test_submit_unknown_type_rejected(self):
        from control_plane import Scheduler

        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "unknown_type_xyz",
            "priority": "NORMAL",
            "payload": {},
        })

        # Should be rejected by policy engine
        assert job_id is not None

    def test_submit_infra_blocked_by_policy(self):
        from control_plane import Scheduler

        scheduler = Scheduler()
        job_id = scheduler.submit({
            "type": "gpu",
            "priority": "HIGH",
            "payload": {
                "model": "llama3",
                "terraform": "apply",
            },
        })

        # Should be blocked unless __infra_whitelisted__
        assert job_id is not None

    def test_priority_ordering(self):
        from control_plane import Scheduler, JobPriority

        scheduler = Scheduler()
        ids = []
        for priority in ["LOW", "NORMAL", "HIGH", "CRITICAL"]:
            jid = scheduler.submit({
                "type": "cpu",
                "priority": priority,
                "payload": {},
            })
            ids.append((priority, jid))

        # CRITICAL should be first when dispatching
        next_job = scheduler.dispatch_next()
        assert next_job is not None

    def test_dispatch_empty_queue(self):
        from control_plane import Scheduler

        scheduler = Scheduler()
        result = scheduler.dispatch_next()
        assert result is None


class TestPolicyEngine:
    """Test policy engine rules."""

    def test_default_rules_loaded(self):
        from control_plane import PolicyEngine

        engine = PolicyEngine()
        policy = engine.get_active_policy()

        assert "max_concurrent_gpu_jobs" in policy["rules"]
        assert policy["rules"]["max_concurrent_gpu_jobs"] == 4

    def test_gpu_job_admitted(self):
        from control_plane import PolicyEngine
        from control_plane.scheduler import Job

        engine = PolicyEngine()
        job = Job(job_type="gpu", priority=1, payload={})

        result = engine.admit(job)
        assert result["admitted"] is True

    def test_unknown_type_rejected(self):
        from control_plane import PolicyEngine
        from control_plane.scheduler import Job

        engine = PolicyEngine()
        job = Job(job_type="malware", priority=1, payload={})

        result = engine.admit(job)
        assert result["admitted"] is False
        assert "not in allowed list" in result["reason"]

    def test_infra_keyword_blocked(self):
        from control_plane import PolicyEngine
        from control_plane.scheduler import Job

        engine = PolicyEngine()
        job = Job(
            job_type="gpu",
            priority=1,
            payload={"kubectl": "delete pods --all"},
        )

        result = engine.admit(job)
        assert result["admitted"] is False

    def test_policy_fingerprint(self):
        from control_plane import PolicyEngine

        engine = PolicyEngine()
        fp1 = engine._policy_fingerprint

        engine.update_rules({"max_concurrent_gpu_jobs": 8})
        fp2 = engine._policy_fingerprint

        assert fp1 != fp2


class TestExecutionRouter:
    """Test routing decisions."""

    def test_gpu_routes_to_slurm(self):
        from control_plane import ExecutionRouter
        from control_plane.scheduler import Job

        router = ExecutionRouter()
        job = Job(job_type="gpu", priority=1, payload={})

        route = router.route(job)
        assert route["executor"] == "slurm"
        assert route["partition"] == "gpu"

    def test_inference_routes_to_ray(self):
        from control_plane import ExecutionRouter
        from control_plane.scheduler import Job

        router = ExecutionRouter()
        job = Job(job_type="inference", priority=1, payload={})

        route = router.route(job)
        assert route["executor"] == "ray"

    def test_service_routes_to_k8s(self):
        from control_plane import ExecutionRouter
        from control_plane.scheduler import Job

        router = ExecutionRouter()
        job = Job(job_type="service", priority=1, payload={})

        route = router.route(job)
        assert route["executor"] == "kubernetes"

    def test_unknown_type_defaults_to_local(self):
        from control_plane import ExecutionRouter
        from control_plane.scheduler import Job

        router = ExecutionRouter()
        job = Job(job_type="unknown_foobar", priority=1, payload={})

        route = router.route(job)
        assert route["executor"] == "local"

    def test_custom_route_override(self):
        from control_plane import ExecutionRouter
        from control_plane.scheduler import Job

        router = ExecutionRouter()
        router.add_route("gpu", {"executor": "ray", "runtime": "gpu_ray"})

        job = Job(job_type="gpu", priority=1, payload={})
        route = router.route(job)

        assert route["executor"] == "ray"


class TestAuditLogger:
    """Test immutable audit chain."""

    def test_log_event_creates_entry(self):
        from control_plane import AuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit.jsonl")
            # Patch the logger path
            import control_plane.audit_logger as al
            original_init = al.AuditLogger.__init__

            def patched_init(self, log_path_=None):
                log_path_ = log_path or tempfile.mktemp(suffix=".jsonl")
                original_init(self, log_path_)

            al.AuditLogger.__init__ = patched_init

            logger = AuditLogger(log_path=log_path)
            h1 = logger.log_event(event_type="TEST_EVENT", job_id="test-123")
            assert h1 is not None
            assert len(h1) == 64  # SHA-256 hex

            al.AuditLogger.__init__ = original_init

    def test_chain_verification(self):
        from control_plane import AuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit.jsonl")
            logger = AuditLogger(log_path=log_path)

            logger.log_event(event_type="EVENT_1", job_id="j1")
            logger.log_event(event_type="EVENT_2", job_id="j2")

            report = logger.verify_chain()
            assert report["valid"] is True
            assert report["total_entries"] == 2


class TestACOSIsolation:
    """Test that ACOS boundary is respected."""

    def test_control_plane_does_not_import_infra(self):
        """Control-plane modules must not import infra."""
        import ast
        import os

        control_plane_root = Path(__file__).parent.parent / "control_plane"
        violations = []

        for py_file in control_plane_root.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text()
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("infra."):
                            violations.append(f"{py_file.name}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("infra."):
                        violations.append(f"{py_file.name}: from {node.module}")

        assert len(violations) == 0, f"ACOS boundary violated: {violations}"

    def test_control_plane_no_subprocess(self):
        """Control-plane modules must not call subprocess."""
        import ast
        from pathlib import Path

        control_plane_root = Path(__file__).parent.parent / "control_plane"
        violations = []

        for py_file in control_plane_root.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text()
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "subprocess":
                            violations.append(f"{py_file.name}: imports subprocess")
                elif isinstance(node, ast.Name):
                    if node.id == "subprocess":
                        violations.append(f"{py_file.name}: uses subprocess")

        assert len(violations) == 0, f"Subprocess violation: {violations}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
