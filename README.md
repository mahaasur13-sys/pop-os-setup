# ATOMFederationOS — SBS v1

> System Boundary Spec — cross-cutting verification layer for distributed OS stack.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  SBS (System Boundary Spec) — GLOBAL INVARIANTS │
│  GlobalInvariantEngine │ FailureClassifier      │
│  SYSTEM_CONTRACT                                │
└───────────┬─────────────────┬──────────────────┘
            ▼                 ▼                   ▼
   CCL Contracts     F2/F3/F8 Kernel     DESC Log
   (local rules)     (execution)         (audit trail)
            ▲                 ▲                   ▲
            └─────────────────┴───────────────────┘
                       DRL (network reality)
```

## Stack Layers

| Layer | Role |
|---|---|
| **DRL** | Distributed Reality Layer — network partition, clock skew, causality |
| **CCL** | Consensus Contract Layer — semantic contracts, stale reads |
| **F2/F3/F8** | Quorum kernel — commit safety, leader uniqueness |
| **DESC** | Distributed Event Sourcing Component — immutable audit trail |
| **SBS** | System Boundary Spec — **global invariant enforcement** |

## SBS v1 Components

| Module | Responsibility |
|---|---|
| `SystemBoundarySpec` | Hard boundary validation gate (split-brain, quorum, uncommitted reads) |
| `GlobalInvariantEngine` | Cross-layer invariant verification (DRL+CCL+F2+DESC) |
| `FailureClassifier` | Jepsen-aligned failure taxonomy (11 categories) |
| `SYSTEM_CONTRACT` | Immutable hard constraints registry |

## Installation

```bash
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest sbs/tests/ -v
```

## Quick Usage

```python
from sbs import SystemBoundarySpec, GlobalInvariantEngine

spec = SystemBoundarySpec(allow_split_brain=False)
engine = GlobalInvariantEngine(spec)

ok = engine.evaluate(
    drl_state={"leader": "node-1", "term": 3, "partitions": 0},
    ccl_state={"leader": "node-1", "term": 3, "stale_reads": 0},
    f2_state={"leader": "node-1", "term": 3, "quorum_ratio": 0.9, "commit_index": 10},
    desc_state={"leader": "node-1", "term": 3, "commit_index": 10},
)
print(ok)  # True
```

## Version History

| Version | Milestone |
|---|---|
| **0.5.1** | SBS v1 — initial release (GlobalInvariantEngine, SystemBoundarySpec, FailureClassifier, SYSTEM_CONTRACT) |
