# Control Plane — Orchestration Layer

## Purpose

The control-plane is the **single entry point** for all execution flows in the unified platform. It provides:

- **Job scheduling** (AI GPU jobs, batch tasks)
- **Policy enforcement** (ACOS governance rules)
- **Execution routing** (Slurm ↔ Ray ↔ Kubernetes)
- **Audit logging** (immutable event chain)

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │           CONTROL PLANE               │
                    │                                        │
  API Request ──► │  Scheduler → Policy Engine → Router   │
                    │         ↓                              │
                    │    Audit Logger                       │
                    └───────┬───────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ↓             ↓             ↓
         domain/       domain/        infra/
         ai_scheduler  trading       (Terraform/K8s)
         job-router    (read-only)
```

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Scheduler | `scheduler.py` | Queue management, priority, backpressure |
| Policy Engine | `policy_engine.py` | ACOS rule enforcement, admission control |
| Execution Router | `execution_router.py` | Route to Slurm / Ray / K8s based on policy |
| Audit Logger | `audit_logger.py` | Immutable event chain, compliance |
| ACOS Gateway | `acos_gateway.py` | Isolated interface to ACOS subsystem |

## Isolation Rules

```
ACOS (acos/) ←── strictly isolated ───→ INFRA (infra/)
     ↓                                          ↓
  NO subprocess calls                    NO ACOS imports
  NO system access                      NO eval/exec
  NO infra imports                      NO kubectl/terraform
```

## Usage

```bash
# Submit job via control-plane
from control_plane import Scheduler

scheduler = Scheduler()
job_id = scheduler.submit({"type": "gpu", "priority": "high", "payload": {...}})
```

## Design Principles

1. **Deterministic** — Same input → Same output
2. **Isolated** — ACOS cannot touch infra, infra cannot touch ACOS
3. **Auditable** — Every action logged to immutable chain
4. **Policy-bound** — All execution gated by policy engine
