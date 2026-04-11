"""
ATOMFederationOS — Chaos Validation Layer (Jepsen-style).

This module provides adversarial fault injection to verify that
ATOMFederationOS remains correct under realistic failure conditions.

Modules
-------
harness   : ChaosHarness — seeded fault injector + metrics collector
scenarios : ChaosScenarios — pre-built named fault scenarios
validator : ChaosValidator — post-chaos SBS invariant checker

Quick start
-----------
    from sbs.boundary_spec import SystemBoundarySpec
    from sbs.global_invariant_engine import GlobalInvariantEngine
    from sbs.runtime import SBSRuntimeEnforcer, SBS_MODE

    from chaos.harness import ChaosHarness, LayerFaultAdapter
    from chaos.validator import ChaosValidator

    spec = SystemBoundarySpec()
    engine = GlobalInvariantEngine(spec)
    enforcer = SBSRuntimeEnforcer(spec, engine, mode=SBS_MODE.ENFORCED)
    adapter = LayerFaultAdapter(drl=my_drl, f2=my_f2, ...)
    validator = ChaosValidator(enforcer, spec, engine)

    harness = ChaosHarness(adapter, enforcer, runtime, seed=42)
    metrics = harness.run(steps=100)

    state = runtime.collect_state()
    result = validator.validate(state)

    print(validator.get_summary())
"""

from chaos.harness import (
    ChaosHarness,
    LayerFaultAdapter,
    ChaosMetrics,
    FaultResult,
    FAULT_TYPE,
)
from chaos.scenarios import ChaosScenarios
from chaos.validator import ChaosValidator, ValidatorReport, ValidationResult

__all__ = [
    "ChaosHarness",
    "LayerFaultAdapter",
    "ChaosMetrics",
    "FaultResult",
    "FAULT_TYPE",
    "ChaosScenarios",
    "ChaosValidator",
    "ValidatorReport",
    "ValidationResult",
]
