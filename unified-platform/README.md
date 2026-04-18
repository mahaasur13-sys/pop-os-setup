# 🏛️ Unified Platform — Enterprise IaC Repository

## Vision

**From "one cluster at home" → Distributed Cloud System**

| Layer | Component | Purpose |
|-------|-----------|---------|
| L0 | AmneziaWG Mesh | Encrypted private network |
| L1 | MikroTik VLAN | Network segmentation + routing |
| L2 | Ceph Storage | Distributed replicated storage |
| L3 | Slurm HA | GPU/CPU batch job scheduling |
| L4 | Ray Cluster | AI runtime + distributed tasks |
| L5 | Kubernetes | Container orchestration + services |
| L6 | AI Scheduler | Policy-driven job routing |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    unified-platform                      │
├─────────────────────────────────────────────────────────┤
│  /acos           ACOS subsystem (ISOLATED boundary)     │
│  /core           Business logic + domain models         │
│  /domain         Application domains (trading, astro)   │
│  /infra          Terraform + Kubernetes + Ansible     │
│  /services       API servers, workers, dashboards       │
│  /pipelines      CI/CD definitions (GitHub Actions)     │
│  /tests          Integration + isolation tests           │
│  /scripts        Automation tools + day-scripts          │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone + enter
git clone https://github.com/mahaasur13-sis/unified-platform.git
cd unified-platform

# Bootstrap (Day 0)
make bootstrap

# Deploy infrastructure
make infra-apply ENV=staging

# Run tests
make test

# Push changes (requires GitHub auth)
make push
```

## CI/CD Gates

| Check | Purpose |
|-------|---------|
| `terraform apply` only in `infra/` | Infrastructure isolation |
| `kubectl apply` only in `pipelines/` | Deployment control |
| ACOS isolation test | No subprocess outside boundary |
| Pre-push validation | Safety checks before commit |

## ACOS Isolation Policy

ACOS subsystem (`/acos`) MUST:

- ❌ NEVER import `infra` modules directly
- ❌ NEVER execute `subprocess` calls outside allowed layer
- ❌ NEVER access Kubernetes API directly
- ✅ MUST be tested via `tests/acos_isolation.py`
- ✅ MUST route through `domain/ai_scheduler/job-router.py` for GPU operations

## Repository Merge History

This repo is a merger of:

- **AsurDev** — Governance, ACOS, observability, scheduling v1-v3
- **home-cluster-iac** — Terraform IaC, Kubernetes manifests, Ceph/Slurm/Ray configs

Merge performed: 2026-04-09

---

*Production-ready. Zero functional duplication. Strict ACOS isolation.*
