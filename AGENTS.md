# ATOM Federation OS — Agent Memory

## Current Version: v8.1-HARDENING-1

## Architecture Map

### v7.x layers (baseline)
- `proof/temporal_verifier.py` — TemporalVerificationReport producer
- `meta_control/temporal_gain_scheduler.py` — instant gain modulation
- `meta_control/proof_feedback_controller.py` — instant weight delta
- `meta_control/stability_weighted_arbitrator.py` — ControlArbitrator with stability weights
- `coherence/` — instantaneous coherence

### v8.0 Persistence Layer (Phase 1 ✅)
- `meta_control/persistence/state_window_store.py` — Sliding tick history (bounded)
- `meta_control/persistence/decision_memory.py` — DecisionRecord + Outcome pairs (bounded, searchable)
- `meta_control/persistence/stability_ledger.py` — Per-source epoch-based stability tracking

### v8.0 Integration Layer (Phase INTEGRATION ✅)
- `meta_control/integration/persistence_bridge.py`
  - `GainModulator` — TemporalGainScheduler + ledger stability + window depth
  - `WeightModulator` — ProofFeedbackController + DecisionMemory outcome history
  - `CoherenceEnricher` — coherence(t) = base(v7) + Δ(persistence)
  - `PersistenceBridge` — top-level `integrate(v7_report, base_gains, base_coherence)` → `IntegrationReport`

### v8.1 Observability Layer (✅)
- `orchestration/planning_observability/drift_profiler.py` — oscillation, goal drift, weight instability, DAG drift
- `orchestration/planning_observability/evaluation_metrics.py` — health score, coherence, DAG metrics
- `orchestration/planning_observability/plan_trace_logger.py` — event trace

### HARDENING PHASE 1 — Circuit Breaker (✅ NEW)
- `orchestration/planning_observability/circuit_breaker.py`
  - CLOSED → OPEN (severity > threshold)
  - OPEN → HALF (health >= recovery_threshold)
  - HALF → CLOSED (health >= close_threshold sustained for half_max_ticks)
  - HALF → OPEN (new episode during recovery)
  - oscillation / governor BLOCK → immediate OPEN
  - Output: `CircuitBreakerSignal {can_mutate, state, block_reason}`
  - Closes the loop: v8.1 drift → actuator control gate

### v8.2a Safety Foundations (✅)
- `orchestration/v8_2a_safety_foundations/invariant_checker.py` — ε-norm, spectral radius, PSD invariants
- `orchestration/v8_2a_safety_foundations/stability_governor.py` — pre-mutation gate (health/drift/density)
- `orchestration/v8_2a_safety_foundations/mutation_ledger.py` — append-only audit log
- `orchestration/v8_2a_safety_foundations/rollback_engine.py` — checkpoint + revert

### Pending
- Phase 2: `orchestration/plan_graph.py` — long-horizon planning DAG
- HARDENING PHASE 2: chaos integration + stress envelope + failure replay
- Phase 3: Federation sync
- Phase 4: Invariant evolution

## Key Invariants
- `S(t) = f(S(t-1), decision(t-1), outcome(t-1))` — StateWindowStore
- `coherence(t) = coherence_base(v7) + Δ(stability_ledger, state_window, decision_memory)`
- `CircuitBreaker.can_mutate = True` iff `state == CLOSED` and no governor block

## Test Status (2026-04-12)
- **134 passed / 6 failed (pre-existing `test_operator_reconciler.py` failures)**
- Phase 1 persistence: 24/24
- Phase INTEGRATION: 11/11
- v8.1 observability: 30/30
- HARDENING-1 circuit breaker: 16/16 ⭐ NEW
- v8.2a safety foundations: 35/35
- coherence (v6.8): 27/27
- chaos harness: 31/31

## Persistence API (real, not assumed)
- `StateWindowStore()` — `record_tick()`, `window()`, `depth`, `latest_tick()`
- `DecisionMemory()` — `append()`, `find_similar(payload, k)`, `record_outcome()`
- `StabilityLedger()` — `record(source, stability, violated)`, `get_ledger()`, `global_trend()`, `is_coherent(source)`

## HARDENING-1 Architecture (closed loop)
```
DriftProfiler.scan()
    → [episodes] → CircuitBreaker.evaluate()
                        → GovernorSignal → StabilityGovernor.evaluate()
                        → CircuitBreakerSignal {can_mutate, state}
                            → actuator / MutationExecutor (respects can_mutate)
```
