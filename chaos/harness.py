"""
Chaos Harness — Jepsen-style adversarial fault injection engine.

Injects faults into ATOMFederationOS layers (DRL/CCL/F2/DESC)
and validates that SBS invariants hold under pressure.

Usage
-----
    from chaos.harness import ChaosHarness, FAULT_TYPE

    harness = ChaosHarness(drl_layer, runtime, enforcer, seed=42)
    harness.run(steps=100, halt_on_violation=False)

    report = harness.get_report()
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum


class FAULT_TYPE(Enum):
    """Jepsen-aligned fault injection types."""
    DROP = "drop"           # Message loss (packet loss simulation)
    DELAY = "delay"         # Latency injection
    DUPLICATE = "duplicate"  # Message duplication
    PARTITION = "partition"  # Network partition (split-brain)
    RECOVER = "recover"      # Partition healing
    CORRUPT = "corrupt"      # Data corruption
    CLOCK_SKEW = "clock_skew"  # Temporal attack
    BYZANTINE = "byzantine"   # Equivocation / fork


@dataclass
class FaultResult:
    """Result of a single fault injection."""
    step: int
    fault_type: FAULT_TYPE
    target_layer: str
    injected: bool
    latency_ms: float
    error: str | None = None

    def __repr__(self) -> str:
        status = "OK" if self.injected else f"FAIL({self.error})"
        return (
            f"[step={self.step}] {self.fault_type.value} → {self.target_layer} "
            f"({status}, {self.latency_ms:.1f}ms)"
        )


@dataclass
class ChaosMetrics:
    """Runtime metrics collected during a chaos run."""
    total_steps: int = 0
    faults_injected: int = 0
    faults_failed: int = 0
    violations_detected: int = 0
    violations_recovered: int = 0
    runtime_errors: int = 0
    final_state_ok: bool = True
    elapsed_ms: float = 0.0
    fault_log: list[dict] = field(default_factory=list)

    def add_fault(self, result: FaultResult) -> None:
        self.faults_injected += 1
        if not result.injected:
            self.faults_failed += 1
        self.fault_log.append({
            "step": result.step,
            "fault": result.fault_type.value,
            "layer": result.target_layer,
            "latency_ms": result.latency_ms,
            "injected": result.injected,
            "error": result.error,
        })

    def add_violation(self) -> None:
        self.violations_detected += 1

    def add_recovery(self) -> None:
        self.violations_recovered += 1

    def add_runtime_error(self) -> None:
        self.runtime_errors += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_steps": self.total_steps,
            "faults_injected": self.faults_injected,
            "faults_failed": self.faults_failed,
            "violations_detected": self.violations_detected,
            "violations_recovered": self.violations_recovered,
            "runtime_errors": self.runtime_errors,
            "final_state_ok": self.final_state_ok,
            "elapsed_ms": self.elapsed_ms,
        }


class LayerFaultAdapter:
    """
    Abstracts fault injection across different layer implementations.
    Each layer may have a different API, so this adapter normalizes access.
    """

    def __init__(self, drl=None, ccl=None, f2=None, desc=None) -> None:
        self._drl = drl
        self._ccl = ccl
        self._f2 = f2
        self._desc = desc

    def _get_layer(self, name: str):
        return {"drl": self._drl, "ccl": self._ccl, "f2": self._f2, "desc": self._desc}.get(name)

    def inject(self, layer: str, fault_type: FAULT_TYPE, **params) -> bool:
        """Inject a fault into a specific layer. Returns True on success."""
        target = self._get_layer(layer)
        if target is None:
            return False

        try:
            if fault_type == FAULT_TYPE.DROP:
                loss_rate = params.get("loss_rate", 0.3)
                if hasattr(target, "failures"):
                    target.failures.loss_rate = loss_rate
                    return True
                return False

            elif fault_type == FAULT_TYPE.DELAY:
                lo = params.get("lo", 50)
                hi = params.get("hi", 200)
                if hasattr(target, "failures"):
                    target.failures.latency_ms = (lo, hi)
                    return True
                if hasattr(target, "latency_ms"):
                    target.latency_ms = (lo, hi)
                    return True
                return False

            elif fault_type == FAULT_TYPE.DUPLICATE:
                dup_rate = params.get("dup_rate", 0.5)
                if hasattr(target, "failures"):
                    target.failures.dup_rate = dup_rate
                    return True
                return False

            elif fault_type == FAULT_TYPE.PARTITION:
                if hasattr(target, "partition"):
                    target.partition.random_split()
                    return True
                if hasattr(target, "partitions"):
                    target.partitions += 1
                    return True
                return False

            elif fault_type == FAULT_TYPE.RECOVER:
                if hasattr(target, "partition"):
                    target.partition.heal()
                    return True
                if hasattr(target, "partitions"):
                    target.partitions = max(0, target.partitions - 1)
                    return True
                return False

            elif fault_type == FAULT_TYPE.CORRUPT:
                if hasattr(target, "state"):
                    target.state["_corrupted"] = True
                    return True
                return False

            elif fault_type == FAULT_TYPE.CLOCK_SKEW:
                skew_ms = params.get("skew_ms", 150)
                if hasattr(target, "clock_skew_ms"):
                    target.clock_skew_ms = skew_ms
                    return True
                return False

            elif fault_type == FAULT_TYPE.BYZANTINE:
                if hasattr(target, "failures"):
                    target.failures.byzantine = True
                    return True
                return False

            return False
        except Exception:
            return False

    def get_state(self, layer: str) -> dict[str, Any]:
        """Get current state snapshot from a layer."""
        target = self._get_layer(layer)
        if target is None:
            return {}
        if hasattr(target, "get_state"):
            return target.get_state()
        if hasattr(target, "__dict__"):
            return {
                k: v for k, v in target.__dict__.items()
                if not k.startswith("_")
            }
        return {}

    def reset_layer(self, layer: str) -> bool:
        """Reset a layer to a clean state."""
        target = self._get_layer(layer)
        if target is None:
            return False
        try:
            if hasattr(target, "reset"):
                target.reset()
                return True
            if hasattr(target, "failures"):
                tf = target.failures
                tf.loss_rate = 0.0
                tf.dup_rate = 0.0
                tf.latency_ms = (0, 0)
                tf.byzantine = False
            if hasattr(target, "partitions"):
                target.partitions = 0
            return True
        except Exception:
            return False


class ChaosHarness:
    """
    Jepsen-style chaos harness for ATOMFederationOS.

    Runs adversarial fault injection sequences and collects metrics
    on SBS invariant violations. Designed to be deterministic (seeded)
    so chaos runs are reproducible.

    Parameters
    ----------
    adapter : LayerFaultAdapter
        Abstraction over layer implementations
    enforcer : SBSRuntimeEnforcer
        SBS enforcement layer for invariant checking
    runtime : Any
        Runtime that can submit tasks and collect state
    seed : int
        Random seed for reproducible runs
    """

    def __init__(
        self,
        adapter: LayerFaultAdapter,
        enforcer,  # SBSRuntimeEnforcer
        runtime: Any,
        seed: int = 42,
    ) -> None:
        self.adapter = adapter
        self.enforcer = enforcer
        self.runtime = runtime
        self._rng = random.Random(seed)
        self._step = 0
        self._metrics = ChaosMetrics()
        self._halt_on_violation = False
        self._violation_callbacks: list[Callable] = []

    def set_halt_on_violation(self, value: bool) -> None:
        self._halt_on_violation = value

    def add_violation_callback(self, cb: Callable) -> None:
        self._violation_callbacks.append(cb)

    def run(self, steps: int = 100, halt_on_violation: bool = False) -> ChaosMetrics:
        """
        Run a chaos simulation for `steps` iterations.

        Each step:
        1. Inject a random fault into a random layer
        2. Attempt a runtime step (task submission)
        3. Collect system state
        4. Run SBS invariant check
        5. Record metrics
        """
        self._halt_on_violation = halt_on_violation
        self._metrics = ChaosMetrics()
        self._metrics.total_steps = steps

        start = time.monotonic()

        for i in range(steps):
            self._step = i
            self._run_step(i)

            if halt_on_violation and self._metrics.violations_detected > 0:
                break

        self._metrics.elapsed_ms = (time.monotonic() - start) * 1000
        return self._metrics

    def _run_step(self, step: int) -> None:
        """Execute a single chaos step."""
        layer_choice = self._rng.choice(["drl", "ccl", "f2", "desc"])
        fault_choice = self._rng.choice(list(FAULT_TYPE))

        result = self._inject_fault(step, layer_choice, fault_choice)
        self._metrics.add_fault(result)

        if not result.injected:
            return

        try:
            if hasattr(self.runtime, "submit"):
                task_id = f"chaos-task-{step}"
                self.runtime.submit({"task": task_id, "step": step})
        except Exception:
            self._metrics.add_runtime_error()

        state = self._collect_state()

        try:
            self.enforcer.enforce(f"chaos_step_{step}", state)
        except Exception:
            pass

        violations = self.enforcer.get_violations_summary()
        if violations:
            self._metrics.add_violation()
            for cb in self._violation_callbacks:
                try:
                    cb(step, state, violations)
                except Exception:
                    pass

    def _inject_fault(
        self, step: int, layer: str, fault_type: FAULT_TYPE
    ) -> FaultResult:
        """Inject a single fault. Returns FaultResult."""
        start = time.monotonic()
        params = {}

        if fault_type == FAULT_TYPE.DROP:
            params["loss_rate"] = self._rng.uniform(0.1, 0.5)
        elif fault_type == FAULT_TYPE.DELAY:
            params["lo"] = self._rng.randint(50, 200)
            params["hi"] = self._rng.randint(200, 500)
        elif fault_type == FAULT_TYPE.DUPLICATE:
            params["dup_rate"] = self._rng.uniform(0.1, 0.6)
        elif fault_type == FAULT_TYPE.CLOCK_SKEW:
            params["skew_ms"] = self._rng.uniform(50, 200)
        elif fault_type == FAULT_TYPE.PARTITION:
            pass
        elif fault_type == FAULT_TYPE.RECOVER:
            pass

        latency = (time.monotonic() - start) * 1000

        try:
            ok = self.adapter.inject(layer, fault_type, **params)
            return FaultResult(
                step=step,
                fault_type=fault_type,
                target_layer=layer,
                injected=ok,
                latency_ms=latency,
                error=None if ok else "layer has no such fault target",
            )
        except Exception as e:
            return FaultResult(
                step=step,
                fault_type=fault_type,
                target_layer=layer,
                injected=False,
                latency_ms=latency,
                error=str(e),
            )

    def _collect_state(self) -> dict[str, Any]:
        """Collect current state from all layers."""
        return {
            "drl": self.adapter.get_state("drl"),
            "ccl": self.adapter.get_state("ccl"),
            "f2": self.adapter.get_state("f2"),
            "desc": self.adapter.get_state("desc"),
        }

    def get_metrics(self) -> ChaosMetrics:
        return self._metrics

    def get_report(self) -> dict[str, Any]:
        """Generate a human-readable chaos run report."""
        m = self._metrics
        return {
            "run_summary": m.to_dict(),
            "fault_success_rate": (
                (m.faults_injected - m.faults_failed) / m.faults_injected * 100
                if m.faults_injected > 0 else 0.0
            ),
            "violation_rate": (
                m.violations_detected / m.total_steps * 100 if m.total_steps > 0 else 0.0
            ),
            "recovery_rate": (
                m.violations_recovered / m.violations_detected * 100
                if m.violations_detected > 0 else 0.0
            ),
            "status": "PASS" if m.violations_detected == 0 else "FAIL",
        }