# ATOM Federation OS — Agent Memory

## Current Version: v8.0

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

### Pending
- Phase 2: `orchestration/plan_graph.py` — long-horizon planning DAG
- Phase 3: Federation sync
- Phase 4: Invariant evolution

## Key Invariants
- `S(t) = f(S(t-1), decision(t-1), outcome(t-1))` — StateWindowStore
- `coherence(t) = coherence_base(v7) + Δ(stability_ledger, state_window, decision_memory)`

## Test Status (2026-04-12)
- 173 passed / 6 failed (pre-existing `test_operator_reconciler.py` failures)
- Phase 1 persistence: 24/24
- Phase INTEGRATION: 11/11

## Persistence API (real, not assumed)
- `StateWindowStore()` — `record_tick()`, `window()`, `depth`, `latest_tick()`
- `DecisionMemory()` — `append()`, `find_similar(payload, k)`, `record_outcome()`
- `StabilityLedger()` — `record(source, stability, violated)`, `get_ledger()`, `global_trend()`, `is_coherent(source)`
