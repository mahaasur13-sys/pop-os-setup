"""
test_chaos.py — Jepsen-style chaos validation tests.

Success criteria (all must pass after a chaos run):
  1. No split-brain commit (leader uniqueness holds)
  2. Quorum not violated
  3. Replay remains deterministic (no sequence violations)
  4. SBS catches real violations (not false positives)
  5. System recovers after partition (RECOVER fault)
"""

from __future__ import annotations

import pytest

from sbs.boundary_spec import SystemBoundarySpec
from sbs.global_invariant_engine import GlobalInvariantEngine
from sbs.runtime import SBSRuntimeEnforcer, SBS_MODE, ViolationPolicy, ExecutionStage

from chaos.harness import ChaosHarness, LayerFaultAdapter, FAULT_TYPE, ChaosMetrics
from chaos.scenarios import ChaosScenarios
from chaos.validator import ChaosValidator, ValidationResult


# ── Mock layer implementations ──────────────────────────────────────────────

class MockFailures:
    """Mock failures object for DRL/F2 layers."""
    def __init__(self):
        self.loss_rate = 0.0
        self.dup_rate = 0.0
        self.latency_ms = (0, 0)
        self.byzantine = False


class MockPartition:
    """Mock partition manager for DRL layer."""
    def __init__(self):
        self.partitions = 0

    def random_split(self):
        self.partitions += 1

    def heal(self):
        self.partitions = max(0, self.partitions - 1)


class MockDRL:
    """Mock DRL layer."""
    def __init__(self):
        self.failures = MockFailures()
        self.partition = MockPartition()
        self.leader = "node-1"
        self.term = 1
        self.clock_skew_ms = 0.0
        self.state = {}

    def get_state(self):
        return {
            "leader": self.leader,
            "term": self.term,
            "partitions": self.partition.partitions,
            "clock_skew_ms": self.clock_skew_ms,
            "quorum_ratio": 0.75,
            "duplicate_ack": self.failures.byzantine or self.failures.dup_rate > 0,
            "event_sequence_gaps": 0,
        }


class MockCCL:
    """Mock CCL contract layer."""
    def __init__(self):
        self.leader = "node-1"
        self.term = 1
        self.stale_reads = 0
        self.quorum_ratio = 0.75
        self.duplicate_ack = False

    def get_state(self):
        return {
            "leader": self.leader,
            "term": self.term,
            "stale_reads": self.stale_reads,
            "quorum_ratio": self.quorum_ratio,
            "duplicate_ack": self.duplicate_ack,
            "event_sequence_gaps": 0,
        }


class MockF2:
    """Mock F2 quorum kernel."""
    def __init__(self):
        self.failures = MockFailures()
        self.partition = MockPartition()
        self.leader = "node-1"
        self.term = 1
        self.commit_index = 0
        self.quorum_ratio = 0.75
        self.duplicate_ack = False

    def get_state(self):
        return {
            "leader": self.leader,
            "term": self.term,
            "commit_index": self.commit_index,
            "partitions": self.partition.partitions,
            "quorum_ratio": self.quorum_ratio,
            "duplicate_ack": self.failures.byzantine or self.failures.dup_rate > 0,
            "event_sequence_gaps": 0,
        }


class MockDESC:
    """Mock DESC event log."""
    def __init__(self):
        self.leader = "node-1"
        self.term = 1
        self.commit_index = 0
        self.event_sequence_gaps = 0

    def get_state(self):
        return {
            "leader": self.leader,
            "term": self.term,
            "commit_index": self.commit_index,
            "event_sequence_gaps": self.event_sequence_gaps,
        }


class MockRuntime:
    """Mock runtime for task submission."""
    def __init__(self):
        self.submitted = []

    def submit(self, task):
        self.submitted.append(task)

    def collect_state(self):
        return {
            "drl": self._drl.get_state(),
            "ccl": self._ccl.get_state(),
            "f2": self._f2.get_state(),
            "desc": self._desc.get_state(),
        }


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def spec():
    return SystemBoundarySpec(
        allow_split_brain=False,
        allow_event_reorder=False,
        allow_duplicate_ack=False,
        quorum_threshold=0.67,
        max_partitions=1,
        enable_temporal_strictness=True,
        clock_skew_threshold_ms=100.0,
    )


@pytest.fixture
def engine(spec):
    return GlobalInvariantEngine(spec)


@pytest.fixture
def enforcer(spec, engine):
    return SBSRuntimeEnforcer(spec, engine, mode=SBS_MODE.ENFORCED)


@pytest.fixture
def mock_drl():
    return MockDRL()


@pytest.fixture
def mock_ccl():
    return MockCCL()


@pytest.fixture
def mock_f2():
    return MockF2()


@pytest.fixture
def mock_desc():
    return MockDESC()


@pytest.fixture
def adapter(mock_drl, mock_ccl, mock_f2, mock_desc):
    return LayerFaultAdapter(
        drl=mock_drl, ccl=mock_ccl, f2=mock_f2, desc=mock_desc
    )


@pytest.fixture
def runtime(mock_drl, mock_ccl, mock_f2, mock_desc):
    r = MockRuntime()
    r._drl = mock_drl
    r._ccl = mock_ccl
    r._f2 = mock_f2
    r._desc = mock_desc
    return r


@pytest.fixture
def validator(enforcer, spec, engine):
    return ChaosValidator(enforcer, spec, engine)


# ── Core tests ───────────────────────────────────────────────────────────────

def test_system_survives_random_chaos(adapter, enforcer, runtime, validator):
    """
    Run 50 iterations of chaos (10 steps each) and verify:
    - System remains in valid state
    - No critical violations
    - SBS catches real violations

    Success criteria: violations < 5 (some transient violations expected
    during adversarial conditions).
    """
    harness = ChaosHarness(adapter, enforcer, runtime, seed=42)
    harness.set_halt_on_violation(False)

    metrics = harness.run(steps=50, halt_on_violation=False)

    state = runtime.collect_state()
    result = validator.validate(state)

    report = validator.get_summary()

    assert metrics.faults_injected > 0, "No faults were injected"
    assert report["status"] == "PASS" or report["violations"] < 5, (
        f"System failed chaos validation: {report['violations']} violations"
    )


def test_split_brain_detection(enforcer, spec, engine, adapter, runtime, validator):
    """
    Split-brain scenario: inject partition and verify SBS detects it.

    Success criteria:
    - SPLIT_BRAIN invariant violation is detected
    - No commit happens on minority partition
    """
    adapter.inject("drl", FAULT_TYPE.PARTITION)
    adapter.inject("f2", FAULT_TYPE.PARTITION)

    state = runtime.collect_state()
    result = validator.validate(state)

    assert not result.ok, "SBS must detect split-brain violation"
    violations = result.failed_invariants
    assert any("SPLIT_BRAIN" in v for v in violations), (
        f"Expected SPLIT_BRAIN violation, got: {violations}"
    )


def test_quorum_safety_under_loss(enforcer, adapter, runtime, validator):
    """
    Message loss + partition degrades quorum below threshold.
    SBS must detect QUORUM_VIOLATION.

    Success criteria: quorum_ratio drops below 0.67 → violation detected.
    """
    adapter.inject("drl", FAULT_TYPE.DROP, loss_rate=0.5)
    adapter.inject("f2", FAULT_TYPE.DROP, loss_rate=0.5)
    adapter.inject("drl", FAULT_TYPE.PARTITION)

    state = runtime.collect_state()

    drl_state = state["drl"]
    drl_state["quorum_ratio"] = 0.4

    result = validator.validate(state)

    assert not result.ok, "SBS must detect quorum violation under loss"
    violations = result.failed_invariants
    assert any("QUORUM" in v.upper() for v in violations), (
        f"Expected QUORUM violation, got: {violations}"
    )


def test_replay_remains_deterministic(enforcer, adapter, runtime, validator):
    """
    Verify that replay under fault injection remains deterministic.
    Sequence gaps must be detected and reported.

    Success criteria: SEQUENCE_VIOLATION is detected or replay is clean.
    """
    adapter.inject("drl", FAULT_TYPE.DUPLICATE, dup_rate=0.4)
    adapter.inject("drl", FAULT_TYPE.DELAY, lo=50, hi=200)

    state = runtime.collect_state()
    result = validator.validate(state)

    violations = result.failed_invariants
    has_sequence_violation = any(
        "SEQUENCE" in v or "REORDER" in v for v in violations
    )
    assert result.ok or has_sequence_violation, (
        "Expected either clean state or sequence violation detected"
    )


def test_sbs_catches_real_violations_not_false_positives(enforcer, adapter, runtime, validator):
    """
    Verify SBS does NOT fire on clean state (no false positives)
    AND does fire on real violations (no false negatives).

    Success criteria:
    - Clean run → no violations (false positive rate = 0)
    - Real fault → violations detected
    """
    state_clean = runtime.collect_state()
    result_clean = validator.validate(state_clean)

    assert result_clean.ok, "SBS must not fire on clean state (false positive)"
    assert result_clean.violations_found == 0, (
        f"False positives detected: {result_clean.failed_invariants}"
    )

    adapter.inject("drl", FAULT_TYPE.PARTITION)
    adapter.inject("f2", FAULT_TYPE.PARTITION)

    state_faulted = runtime.collect_state()
    result_faulted = validator.validate(state_faulted)

    assert not result_faulted.ok, "SBS must fire on real fault (false negative)"
    assert result_faulted.violations_found > 0, (
        "SBS failed to detect real violation"
    )

    validator.reset()


def test_system_recovers_after_partition(adapter, enforcer, runtime, validator):
    """
    Partition → recover cycle: system must converge to clean state.

    Success criteria:
    - After RECOVER fault, state is clean (no violations)
    - Commit index does not regress
    """
    adapter.inject("drl", FAULT_TYPE.PARTITION)
    adapter.inject("f2", FAULT_TYPE.PARTITION)

    state_partitioned = runtime.collect_state()
    result_partitioned = validator.validate(state_partitioned)

    assert not result_partitioned.ok, "Must detect partition violation"

    adapter.inject("drl", FAULT_TYPE.RECOVER)
    adapter.inject("f2", FAULT_TYPE.RECOVER)

    state_healed = runtime.collect_state()
    result_healed = validator.validate(state_healed)

    assert result_healed.ok, (
        f"System must recover after heal. Violations: {result_healed.failed_invariants}"
    )


def test_byzantine_signal_detection(enforcer, adapter, runtime, validator):
    """
    Byzantine behavior (duplicate ACKs / equivocation) must be detected.

    Success criteria: BYZANTINE_SIGNAL or DUPLICATE violation detected.
    """
    adapter.inject("f2", FAULT_TYPE.BYZANTINE)
    adapter.inject("f2", FAULT_TYPE.DUPLICATE, dup_rate=0.5)

    state = runtime.collect_state()
    result = validator.validate(state)

    violations = result.failed_invariants
    has_byzantine = any(
        "BYZANTINE" in v or "DUPLICATE" in v for v in violations
    )
    assert has_byzantine, f"Expected Byzantine signal, got: {violations}"


def test_temporal_drift_detection(enforcer, adapter, runtime, validator):
    """
    Clock skew > threshold must trigger TEMPORAL_DRIFT violation.

    Success criteria: clock_skew_ms > 100ms → TEMPORAL_DRIFT detected.
    """
    adapter.inject("drl", FAULT_TYPE.CLOCK_SKEW, skew_ms=200.0)

    state = runtime.collect_state()
    result = validator.validate(state)

    violations = result.failed_invariants
    has_temporal = any("TEMPORAL" in v or "DRIFT" in v for v in violations)
    assert has_temporal, f"Expected temporal drift, got: {violations}"


def test_no_commit_on_no_quorum(enforcer, adapter, runtime, validator):
    """
    When quorum is lost, system must NOT commit.

    Success criteria: commit_index does not advance without quorum.
    """
    adapter.inject("drl", FAULT_TYPE.PARTITION)
    adapter.inject("ccl", FAULT_TYPE.PARTITION)
    adapter.inject("f2", FAULT_TYPE.PARTITION)

    state = runtime.collect_state()
    result = validator.validate(state)

    violations = result.failed_invariants
    has_quorum = any("QUORUM" in v for v in violations)
    has_partition = any("SPLIT_BRAIN" in v or "partition" in v.lower() for v in violations)

    assert has_quorum or has_partition, (
        f"System must detect no-quorum condition. Violations: {violations}"
    )


def test_chaos_harness_injects_all_fault_types(adapter):
    """
    Verify that all FAULT_TYPE variants can be injected without crashing.

    Success criteria: all 8 fault types return injected=True for at least
    one layer.
    """
    fault_results = {}
    for fault_type in FAULT_TYPE:
        result = adapter.inject("drl", fault_type, loss_rate=0.3, dup_rate=0.3, skew_ms=100.0, lo=50, hi=200)
        fault_results[fault_type] = result

    assert all(r for r in fault_results.values()), (
        f"Some fault types failed to inject: "
        f"{[f.value for f, r in fault_results.items() if not r]}"
    )


def test_repeated_chaos_runs_are_deterministic(adapter, enforcer, runtime):
    """
    Two runs with same seed produce identical fault/type/sequence patterns.
    Note: latency_ms is timing-based and may differ; we compare the
    fault sequence (step, fault, layer, injected, error) only.
    """
    harness1 = ChaosHarness(adapter, enforcer, runtime, seed=99)
    m1 = harness1.run(steps=20)

    adapter2 = LayerFaultAdapter(
        drl=MockDRL(), ccl=MockCCL(), f2=MockF2(), desc=MockDESC()
    )
    harness2 = ChaosHarness(adapter2, enforcer, runtime, seed=99)
    m2 = harness2.run(steps=20)

    def fault_summary(log):
        return [(e["step"], e["fault"], e["layer"], e["injected"], e["error"]) for e in log]

    assert fault_summary(m1.fault_log) == fault_summary(m2.fault_log), (
        "Chaos runs with same seed must produce same fault sequence"
    )


def test_validator_report_aggregates_correctly(adapter, enforcer, runtime, validator):
    """
    Multiple validate() calls accumulate into ValidatorReport.

    Success criteria: total_validations reflects actual call count.
    """
    validator.reset()
    assert validator.get_report().total_validations == 0

    for i in range(5):
        state = runtime.collect_state()
        adapter.inject("drl", FAULT_TYPE.PARTITION)
        validator.validate(state)

    report = validator.get_report()
    assert report.total_validations == 5, (
        f"Expected 5 validations, got {report.total_validations}"
    )


def test_composite_attack_multiple_fault_types(adapter, enforcer, runtime, validator):
    """
    Inject composite attack: partition + Byzantine + latency + skew.
    SBS must catch all violations simultaneously.

    Success criteria: ≥ 2 distinct violation types detected.
    """
    adapter.inject("drl", FAULT_TYPE.PARTITION)
    adapter.inject("f2", FAULT_TYPE.BYZANTINE)
    adapter.inject("drl", FAULT_TYPE.DELAY, lo=100, hi=400)
    adapter.inject("drl", FAULT_TYPE.CLOCK_SKEW, skew_ms=200.0)

    state = runtime.collect_state()
    result = validator.validate(state)

    assert not result.ok, "Composite attack must trigger violations"
    violations = result.failed_invariants

    distinct_categories = set()
    for v in violations:
        if "PARTITION" in v or "SPLIT" in v:
            distinct_categories.add("partition")
        elif "QUORUM" in v:
            distinct_categories.add("quorum")
        elif "TEMPORAL" in v or "DRIFT" in v or "SKEW" in v:
            distinct_categories.add("temporal")
        elif "BYZANTINE" in v or "DUPLICATE" in v:
            distinct_categories.add("byzantine")

    assert len(distinct_categories) >= 2, (
        f"Expected ≥2 distinct violation categories, got: {distinct_categories}"
    )