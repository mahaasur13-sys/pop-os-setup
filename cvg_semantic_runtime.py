#!/usr/bin/env python3
"""
CVG v7.2 — Federated Semantic Execution Runtime
================================================

Semantic Drift Classification Engine for Distributed CI/CD Systems

KEY PRINCIPLE: Different execution scopes are NOT errors.
CI vs test vs infra pipelines MUST resolve to IGNORE, not BLOCK.

Version: 7.2.0
Schema: cvg.semantic.v1
"""

import json, hashlib, datetime, sys, os
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

# ─────────────────────────────────────────────────────────────
# SCHEMA DEFINITIONS
# ─────────────────────────────────────────────────────────────

DRIFT_CLASS = {"NONE", "STRUCTURAL", "EXECUTION", "ENVIRONMENTAL", "INVALID", "EQUIVALENT"}
SEVERITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ACTION = {"IGNORE", "REVIEW", "BLOCK", "RECONCILE"}
SCOPE_TYPES = {"ci", "infra", "test", "build", "runtime", "mixed"}

# ─────────────────────────────────────────────────────────────
# IR COMPILER v3.2 — Normalizes execution graphs
# ─────────────────────────────────────────────────────────────

def compute_ir_hash(ir: dict) -> str:
    """Deterministic IR hash — order-independent for graph stability."""
    normal = {
        k: ir[k] for k in sorted(ir.keys())
        if ir[k] is not None and ir[k] != "" and ir[k] != []
    }
    return hashlib.sha256(json.dumps(normal, sort_keys=True).encode()).hexdigest()[:16]


def ir_normalize(raw: dict, repo: str) -> dict:
    """Convert raw IR to canonical v3.2 semantic IR."""
    jobs = raw.get("jobs", [])
    if isinstance(jobs, dict):
        job_list = [{"id": k, **v} for k, v in jobs.items()]
    elif isinstance(jobs, list):
        job_list = [{"id": j["id"] if isinstance(j, dict) else j} for j in jobs]
    else:
        job_list = []

    toolchain = raw.get("toolchain", {})
    if isinstance(toolchain, dict):
        tc_normal = {k: v.get("version", v) if isinstance(v, dict) else str(v)
                     for k, v in toolchain.items()}
    else:
        tc_normal = {}

    repo_lower = repo.lower()
    if "test" in repo_lower or "spec" in repo_lower:
        scope = "test"
    elif "infra" in repo_lower or "iac" in repo_lower or "cluster" in repo_lower:
        scope = "infra"
    elif "build" in repo_lower or "compile" in repo_lower:
        scope = "build"
    else:
        scope = _infer_scope(job_list)

    env = _build_env_profile(raw, scope)

    return {
        "ir_version": "3.2",
        "repo": repo,
        "scope": scope,
        "determinism_class": raw.get("determinism_class", "strict"),
        "job_count": len(job_list),
        "job_ids": sorted(set(j["id"] if isinstance(j, dict) else j for j in job_list)),
        "toolchain_profile": tc_normal,
        "toolchain_hash": hashlib.sha256(
            json.dumps(tc_normal, sort_keys=True).encode()
        ).hexdigest()[:16],
        "env_profile": env,
        "env_hash": hashlib.sha256(
            json.dumps(env, sort_keys=True).encode()
        ).hexdigest()[:16],
        "graph_hash": hashlib.sha256(
            json.dumps(sorted(j["id"] if isinstance(j, dict) else j for j in job_list), sort_keys=True).encode()
        ).hexdigest()[:16],
        "ir_hash": None,
        "raw_ref": raw.get("policy_hash", raw.get("ir_hash", "")),
    }


def _infer_scope(job_list: list) -> str:
    names = " ".join(j["id"] if isinstance(j, dict) else str(j) for j in job_list).lower()
    if any(k in names for k in ["terraform", "ansible", "k8s", "kube", "deploy", "mesh", "vpn"]):
        return "infra"
    if any(k in names for k in ["pytest", "test", "spec", "lint", "format", "ruff", "yamllint"]):
        return "test"
    return "ci"


def _build_env_profile(raw: dict, scope: str) -> dict:
    env = {
        "scope": scope,
        "python": "==3.12",
        "ubuntu": "ubuntu-latest",
    }
    if scope == "infra":
        env.update({"terraform": "==1.5.7", "ansible_core": "==2.16.18"})
    elif scope == "test":
        env.update({"pytest": "from-pyproject"})
    return env


def ir_finalize(ir: dict) -> dict:
    ir["ir_hash"] = compute_ir_hash(ir)
    return ir


# ─────────────────────────────────────────────────────────────
# SEMANTIC DRIFT CLASSIFIER v7.2 — Core Engine
# ─────────────────────────────────────────────────────────────

@dataclass
class DriftReport:
    status: str
    drift_class: str
    severity: str
    scope_match: bool
    execution_equivalence: bool
    root_cause: str
    action: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "drift_report": {
                "class": self.drift_class,
                "severity": self.severity,
                "scope_match": self.scope_match,
                "execution_equivalence": self.execution_equivalence,
                "root_cause": self.root_cause,
                "action": self.action,
                **self.details
            }
        }


class SemanticDriftClassifier:
    """
    v7.2 Core: Classifies execution graph differences semantically.

    RULES (applied in order):
      R1 — Scope mismatch    → STRUCTURAL (IGNORE, LOW)
      R2 — DAG mismatch      → STRUCTURAL (REVIEW, LOW/MEDIUM)
      R3 — Toolchain differ  → EXECUTION (REVIEW, MEDIUM)
      R4 — Env mismatch      → ENVIRONMENTAL (IGNORE, LOW)
      R5 — Exact match       → NONE (IGNORE, LOW)
      R6 — IR invalid        → INVALID (BLOCK, HIGH)
      R7 — Same scope + same DAG but different tool → EQUIVALENT (IGNORE, LOW)
    """

    def classify(self, ir_a: dict, ir_b: dict) -> DriftReport:
        # R6: Invalid IR check
        if not self._is_valid_ir(ir_a) or not self._is_valid_ir(ir_b):
            return self._invalid()

        scope_a, scope_b = ir_a["scope"], ir_b["scope"]
        job_ids_a = set(ir_a["job_ids"])
        job_ids_b = set(ir_b["job_ids"])
        tc_a, tc_b = ir_a["toolchain_hash"], ir_b["toolchain_hash"]
        env_a, env_b = ir_a["env_hash"], ir_b["env_hash"]

        details = {
            "repo_a": ir_a["repo"],
            "repo_b": ir_b["repo"],
            "scope_a": scope_a,
            "scope_b": scope_b,
            "job_count_a": ir_a["job_count"],
            "job_count_b": ir_b["job_count"],
            "ir_hash_a": ir_a["ir_hash"],
            "ir_hash_b": ir_b["ir_hash"],
            "graph_hash_a": ir_a["graph_hash"],
            "graph_hash_b": ir_b["graph_hash"],
            "toolchain_hash_a": tc_a,
            "toolchain_hash_b": tc_b,
            "env_hash_a": env_a,
            "env_hash_b": env_b,
        }

        # R1: Scope mismatch
        if scope_a != scope_b:
            return DriftReport(
                status="DRIFT",
                drift_class="STRUCTURAL",
                severity="LOW",
                scope_match=False,
                execution_equivalence=False,
                root_cause=f"Scope mismatch: '{scope_a}' vs '{scope_b}' (different execution domains)",
                action="IGNORE",
                details={
                    **details,
                    "reason": "Heterogeneous execution domains — different scope is EXPECTED",
                    "note": "CI vs infra vs test pipelines are SUPPOSED to differ"
                }
            )

        # R2: DAG mismatch (same scope, different job sets)
        if job_ids_a != job_ids_b:
            only_a = sorted(job_ids_a - job_ids_b)
            only_b = sorted(job_ids_b - job_ids_a)
            severity = "LOW" if scope_a in ("infra", "test") else "MEDIUM"
            return DriftReport(
                status="DRIFT",
                drift_class="STRUCTURAL",
                severity=severity,
                scope_match=True,
                execution_equivalence=False,
                root_cause=f"DAG structure differs: {len(only_a)} jobs only in A, {len(only_b)} jobs only in B",
                action="IGNORE" if scope_a in ("infra", "test") else "REVIEW",
                details={
                    **details,
                    "only_in_a": only_a,
                    "only_in_b": only_b,
                    "reason": "Same scope but different job composition — structural difference, not failure"
                }
            )

        # R3: Toolchain mismatch
        if tc_a != tc_b:
            return DriftReport(
                status="DRIFT",
                drift_class="EXECUTION",
                severity="MEDIUM",
                scope_match=True,
                execution_equivalence=False,
                root_cause="Toolchain versions differ between repos",
                action="REVIEW",
                details={
                    **details,
                    "reason": "Same DAG but different tool versions — may affect reproducibility"
                }
            )

        # R4: Environment mismatch
        if env_a != env_b:
            return DriftReport(
                status="DRIFT",
                drift_class="ENVIRONMENTAL",
                severity="LOW",
                scope_match=True,
                execution_equivalence=True,
                root_cause="Environment profile differs",
                action="IGNORE",
                details={
                    **details,
                    "reason": "Same execution logic but different environment config"
                }
            )

        # R5: Exact match
        if ir_a["ir_hash"] == ir_b["ir_hash"]:
            return DriftReport(
                status="NO_DRIFT",
                drift_class="NONE",
                severity="LOW",
                scope_match=True,
                execution_equivalence=True,
                root_cause="Identical execution graphs",
                action="IGNORE",
                details={
                    **details,
                    "ir_match": True
                }
            )

        # R7: Same scope, same DAG, different hash (internal diff)
        return DriftReport(
            status="DRIFT",
            drift_class="EQUIVALENT",
            severity="LOW",
            scope_match=True,
            execution_equivalence=True,
            root_cause="Same DAG and scope but non-functional hash difference",
            action="IGNORE",
            details={
                **details,
                "reason": "Functional equivalence despite hash difference"
            }
        )

    def _is_valid_ir(self, ir: dict) -> bool:
        required = {"ir_version", "repo", "scope", "job_ids", "toolchain_hash", "env_hash", "ir_hash"}
        return required.issubset(ir.keys()) and ir.get("ir_version") == "3.2"


# ─────────────────────────────────────────────────────────────
# TEE ATTESTATION BRIDGE — v7.0 compatibility
# ─────────────────────────────────────────────────────────────

def load_tee_attestation(ledger_path: str) -> dict:
    if os.path.exists(ledger_path):
        return json.loads(Path(ledger_path).read_text())
    return {}


# ─────────────────────────────────────────────────────────────
# FEDERATION ENGINE
# ─────────────────────────────────────────────────────────────

def load_repo_ir(repo_path: str) -> dict | None:
    ir_file = Path(repo_path) / "CVG_IR.json"
    if ir_file.exists():
        raw = json.loads(ir_file.read_text())
        repo = ir_file.parent.name
        normalized = ir_normalize(raw, repo)
        ir_finalize(normalized)
        return normalized
    return None


def compare_repos(repos: list[tuple[str, str]]) -> list[dict]:
    classifier = SemanticDriftClassifier()
    irs = []
    for name, path in repos:
        ir = load_repo_ir(path)
        if ir:
            irs.append((name, ir))

    reports = []
    for i in range(len(irs)):
        for j in range(i + 1, len(irs)):
            name_a, ir_a = irs[i]
            name_b, ir_b = irs[j]
            report = classifier.classify(ir_a, ir_b)
            reports.append({
                "repo_a": name_a,
                "repo_b": name_b,
                **report.to_dict()
            })
    return reports


# ─────────────────────────────────────────────────────────────
# MAIN — Semantic Execution Report
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("CVG v7.2 — Federated Semantic Execution Runtime")
    print("=" * 64)

    repos = [
        ("home-cluster-iac", "/home/workspace/home-cluster-iac"),
        ("AsurDev",          "/home/workspace/AsurDev"),
    ]

    irs = {}
    for name, path in repos:
        ir = load_repo_ir(path)
        if ir:
            irs[name] = ir

    print("\n[NORMALIZED IR SUMMARY — v3.2]")
    print("-" * 64)
    for name, ir in irs.items():
        print(f"  [{name}]")
        print(f"    scope:            {ir['scope']}")
        print(f"    ir_version:       {ir['ir_version']}")
        print(f"    job_count:        {ir['job_count']}")
        print(f"    jobs:             {', '.join(ir['job_ids'][:8])}{'...' if len(ir['job_ids']) > 8 else ''}")
        print(f"    toolchain_hash:   {ir['toolchain_hash']}")
        print(f"    graph_hash:       {ir['graph_hash']}")
        print(f"    env_hash:         {ir['env_hash']}")
        print(f"    ir_hash:          {ir['ir_hash']}")
        print()

    classifier = SemanticDriftClassifier()
    reports = compare_repos(repos)

    print("\n[SEMANTIC DRIFT CLASSIFICATION — v7.2]")
    print("-" * 64)
    for r in reports:
        rr = r["drift_report"]
        status_icon = "✓" if r["status"] == "NO_DRIFT" else "⚠"
        print(f"\n  {status_icon} {r['repo_a']} vs {r['repo_b']}")
        print(f"    class:            {rr['class']}")
        print(f"    severity:         {rr['severity']}")
        print(f"    action:           {rr['action']}")
        print(f"    scope_match:      {rr['scope_match']}")
        print(f"    exec_equiv:       {rr['execution_equivalence']}")
        print(f"    root_cause:       {rr['root_cause']}")
        if "reason" in rr:
            print(f"    NOTE:             {rr['reason']}")
        if "only_in_a" in rr:
            print(f"    only in {r['repo_a']}: {rr['only_in_a']}")
            print(f"    only in {r['repo_b']}: {rr['only_in_b']}")

    print("\n[TEE ATTESTATION BRIDGE]")
    print("-" * 64)
    tee = load_tee_attestation("/home/workspace/cvg_tee_attestation.json")
    if tee:
        print(f"  attestation_id: {tee.get('attestation_id', 'N/A')}")
        print(f"  tee_platform:    {tee.get('platform', 'software')}")
        print(f"  system_status:  {tee.get('status', 'UNKNOWN')}")
    else:
        print("  [no attestation — running in software mode]")

    print("\n" + "=" * 64)
    print("FINAL VERDICT")
    print("=" * 64)
    all_ignore = all(r["drift_report"]["action"] == "IGNORE" for r in reports)
    any_block = any(r["drift_report"]["action"] == "BLOCK" for r in reports)
    any_drift = any(r["status"] == "DRIFT" for r in reports)

    if any_block:
        print("  BLOCK — Critical issues detected")
    elif all_ignore:
        print("  IGNORE — All differences are expected and safe")
    elif any_drift:
        print("  REVIEW — Non-critical differences detected")
    else:
        print("  NO_DRIFT — Execution graphs are equivalent")

    # Save v7.2 semantic report
    out = {"schema": "cvg.semantic.v1", "version": "7.2.0", "reports": reports}
    Path("/home/workspace/cvg_semantic_v72.json").write_text(json.dumps(out, indent=2))
    print(f"\n  Semantic report: /home/workspace/cvg_semantic_v72.json")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
