# 🏗️ HOME-CLUSTER-IAC UNIFICATION PLAN v1.0

## STATUS: READY TO EXECUTE

---

## INPUT ANALYSIS

### AsurDev (canonical baseline)
- ✅ day1-day7 scripts (production-documented)
- ✅ L1-L6 test_suite.sh
- ✅ CI workflow (ruff/black/pytest)
- ✅ pyproject.toml + Makefile (ML targets)
- ⚠️ NO Terraform modules
- ⚠️ NO Ansible roles

### home-cluster-iac (extended IaC)
- ✅ Terraform modules (network/compute/k8s/slurm/ray/storage/vpn_mesh)
- ✅ Ansible playbooks + roles + inventory
- ✅ Monitoring (Prometheus/Grafana/exporters)
- ✅ K8s manifests (kustomization overlays)
- ✅ Self-healing (systemd watchdog + k8s watchdog)
- ✅ slurm_ha_failover.sh
- ✅ validate.sh + generate_vars.sh + vars.sh
- ✅ day6_monitoring.sh
- ✅ Makefile (day0-day7 targets)
- ⚠️ NO L1-L6 test suite
- ⚠️ NO proper CI

---

## DECISION MATRIX

| Component | Source | Reason |
|-----------|--------|--------|
| day1-network.sh | AsurDev | better documented |
| day2-vpn.sh | AsurDev | better documented |
| day3-compute.sh | AsurDev | canonical |
| day4-slurm.sh | AsurDev | canonical |
| day5-ray.sh | AsurDev | canonical |
| day6-ceph.sh | AsurDev | canonical |
| day7-integration.sh | AsurDev | canonical |
| test_suite.sh | AsurDev | L1-L6 coverage |
| Terraform modules | home-cluster-iac | unique |
| Ansible playbooks | home-cluster-iac | unique |
| K8s manifests | MERGE both | complement each other |
| Monitoring | MERGE both | home-cluster-iac more complete |
| self_healing | MERGE both | home-cluster-iac more complete + k8s |
| slurm_ha_failover | home-cluster-iac | unique |
| validate.sh | home-cluster-iac | unique |
| generate_vars.sh | home-cluster-iac | unique |
| vars.sh | home-cluster-iac | unique |
| day6_monitoring.sh | home-cluster-iac | unique |
| Makefile | MERGE both | use home-cluster-iac structure + ML targets from AsurDev |
| CI workflows | MERGE both | AsurDev CI (ruff/black/pytest) + home-cluster-iac security |

---

## TARGET STRUCTURE

```
home-cluster-iac/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml          ← AsurDev canonical CI
│   │   └── security.yml   ← home-cluster-iac security scan
│   └── dependabot.yml
│
├── scripts/                     ← CANONICAL (from AsurDev)
│   ├── day1-network.sh
│   ├── day2-vpn.sh
│   ├── day3-compute.sh
│   ├── day4-slurm.sh
│   ├── day5-ray.sh
│   ├── day6-ceph.sh
│   ├── day7-integration.sh
│   ├── test_suite.sh          ← L1-L6 test suite (from AsurDev)
│   │
│   ├── infra-tools/            ← from home-cluster-iac
│   │   ├── slurm_ha_failover.sh
│   │   ├── validate.sh
│   │   ├── generate_vars.sh
│   │   ├── vars.sh
│   │   └── day6_monitoring.sh
│   │
│   └── dev-tools/             ← auth/dev utilities
│       └── gh-auth-fix.sh
│
├── terraform/                  ← from home-cluster-iac
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars.example
│   └── modules/
│       ├── network/
│       ├── compute/
│       ├── kubernetes/
│       ├── monitoring/
│       ├── ray/
│       ├── slurm/
│       ├── storage/
│       └── vpn_mesh/
│
├── ansible/                    ← from home-cluster-iac
│   ├── inventory.ini
│   ├── inventory.ini.example
│   ├── playbook.yml
│   ├── site.yml
│   ├── roles/
│   └── group_vars/
│
├── k8s/                        ← MERGED
│   ├── manifests/               ← original (gpu-job, ray-jobs-pvc, ray-serve-service)
│   │   ├── gpu-job.yaml
│   │   ├── ray-jobs-pvc.yaml
│   │   └── ray-serve-service.yaml
│   └── federation/             ← from home-cluster-iac
│       ├── cluster-registration.yaml
│       ├── federated-deployment.yaml
│       ├── placement-policy.yaml
│       ├── helm-install.sh
│       └── cluster-registration.sh
│
├── monitoring/                 ← MERGED (home-cluster-iac base + AsurDev exporters)
│   ├── prometheus.yml
│   ├── grafana-datasources.yml
│   ├── alerts/
│   ├── dashboards/
│   ├── exporters/
│   └── prometheus/             ← from home-cluster-iac
│       └── alerts.yml
│
├── self_healing/               ← MERGED (home-cluster-iac more complete)
│   ├── health_check.sh
│   ├── watchdog.sh
│   ├── diagnostics/
│   ├── cluster-watchdog.service   ← from home-cluster-iac
│   ├── cluster-watchdog.timer       "
│   ├── k8s_watchdog.yaml           "
│   └── systemd_watchdog.sh          "
│
├── docs/
│   ├── architecture.md         ← NEW: unified architecture doc
│   └── cluster-runbook.md     ← NEW: operations handbook
│
├── Makefile                    ← MERGED: day0-day7 (home-cluster-iac) + ML (AsurDev)
├── pyproject.toml              ← from AsurDev (acos package)
└── README.md                   ← UPDATED: unified documentation
```

---

## MERGE STEPS

### STEP 1: Copy canonical day scripts (AsurDev → home-cluster-iac)
```bash
cp AsurDev/scripts/day{1,2,3,4,5,6,7}-*.sh home-cluster-iac/scripts/
cp AsurDev/scripts/test_suite.sh home-cluster-iac/scripts/
```

### STEP 2: Copy Terraform + Ansible (already in home-cluster-iac)
→ No action needed (already there)

### STEP 3: Copy K8s manifests (AsurDev → home-cluster-iac/k8s/manifests/)
```bash
cp AsurDev/k8s/manifests/*.yaml home-cluster-iac/k8s/manifests/
```

### STEP 4: Merge monitoring dirs (home-cluster-iac base + AsurDev alerts/exporters)
```bash
cp -r AsurDev/monitoring/alerts/* home-cluster-iac/monitoring/alerts/
cp -r AsurDev/monitoring/exporters/* home-cluster-iac/monitoring/exporters/
```

### STEP 5: Merge self_healing (home-cluster-iac base + AsurDev diagnostics)
```bash
cp -r AsurDev/self_healing/diagnostics/* home-cluster-iac/self_healing/diagnostics/
```

### STEP 6: Add AsurDev ML Makefile targets to home-cluster-iac Makefile
→ Append: ml-train, ml-api*, loadtest, correction

### STEP 7: Add AsurDev CI workflow
```bash
cp AsurDev/.github/workflows/ci.yml home-cluster-iac/.github/workflows/
```

### STEP 8: Generate architecture.md + cluster-runbook.md

---

## POST-MERGE VALIDATION

```bash
cd home-cluster-iac
bash scripts/test_suite.sh          # L1-L6 suite must pass
bash scripts/validate.sh             # TF + Ansible validation
make day1                            # dry-run check
```

---

## RESULT AFTER CONSOLIDATION

| Metric | Before | After |
|--------|--------|-------|
| day1-day7 scripts | DUPLICATED (2x naming) | SINGLE canonical source |
| Terraform modules | scattered | unified /modules/ |
| Ansible playbooks | overlapping | SINGLE site.yml |
| K8s manifests | partial | full federation + base |
| Monitoring | fragmented | unified prometheus + grafana |
| self_healing | basic | full k8s + systemd |
| CI | partial | full ruff+black+pytest+security |
| test coverage | partial | L1-L6 full suite |
| ML pipeline | separate repo | integrated in Makefile |

---

## ESTIMATED effort

- Manual merge: ~2 hours (copy/verify)
- Auto script: ~20 min (rsync + git add)
- Validation: ~10 min

