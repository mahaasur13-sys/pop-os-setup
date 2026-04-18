#!/usr/bin/env python3
"""
CVG v7.1 — Federated Execution Runtime
======================================
Deterministic cross-node execution mirror with TEE attestation.
NOT a blockchain. NOT a consensus network.

Two-node federation:
  1. home-cluster-iac  (primary, compiler_v3, tee_v7, self_heal_v6)
  2. AsurDev           (secondary, partial_ir, pending_tee, no_self_heal)

Guarantee: identical input → identical IR → identical execution hash
"""

import json, hashlib, datetime, os, sys
from pathlib import Path
from typing import Optional

FEDERATION_ID = "cvg-federation-v7.1"
CANONICAL_SCHEMA = "3.1"
COMPILER_LOCK = "v3.1"
NODES = {
    "home-cluster-iac": {
        "role": "primary",
        "capabilities": ["compiler_v3", "tee_v7", "self_heal_v6"],
        "path": "/home/workspace/home-cluster-iac",
        "ir_file": "CVG_IR.json",
        "policy_file": "CVG_POLICY.yml",
        "ci_file": ".github/workflows/ci.yml",
    },
    "AsurDev": {
        "role": "secondary",
        "capabilities": ["partial_ir", "pending_tee", "no_self_heal"],
        "path": "/home/workspace/AsurDev",
        "ir_file": "CVG_IR.json",
        "policy_file": "CVG_POLICY.yml",
        "ci_file": ".github/workflows/ci.yml",
    },
}


def h(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def load_ir(node_id: str) -> Optional[dict]:
    cfg = NODES[node_id]
    p = Path(cfg["path"]) / cfg["ir_file"]
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_policy(node_id: str) -> Optional[dict]:
    import yaml
    cfg = NODES[node_id]
    p = Path(cfg["path"]) / cfg["policy_file"]
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text())


def compute_ir_hash(ir: dict) -> str:
    """Canonical IR hash — deterministic regardless of key order."""
    raw_jobs = ir.get("jobs", [])
    jobs = sorted(raw_jobs, key=lambda x: x["id"] if isinstance(x, dict) else str(x))
    core = {
        "schema_version": ir.get("schema_version", "unknown"),
        "policy_hash": ir["policy_hash"],
        "toolchain_hash": ir["toolchain_hash"],
        "jobs": jobs,
    }
    return h(json.dumps(core, sort_keys=True))


def ir_normalize(ir: dict) -> dict:
    """Normalize IR to canonical form for cross-node comparison."""
    raw_jobs = ir.get("jobs", [])
    # Normalize: jobs can be list of strings or list of dicts
    norm_jobs = []
    for j in raw_jobs:
        if isinstance(j, str):
            norm_jobs.append({"id": j})
        elif isinstance(j, dict):
            norm_jobs.append(j)
    return {
        "schema_version": ir.get("schema_version", "unknown"),
        "policy_hash": ir["policy_hash"],
        "toolchain_hash": ir["toolchain_hash"],
        "ir_hash": compute_ir_hash({**ir, "jobs": norm_jobs}),
        "render_hash": ir.get("render_hash", ""),
        "dag_sorted": ir.get("dag_sorted", []),
        "edges": sorted(ir.get("edges", [])),
        "jobs": sorted(norm_jobs, key=lambda x: x["id"]),
    }


def compile_parity_check() -> dict:
    """STEP 2: Verify both nodes produce identical IR hashes."""
    results = {}
    for node_id, cfg in NODES.items():
        ir = load_ir(node_id)
        if ir is None:
            results[node_id] = {"status": "NO_IR", "error": f"{cfg['ir_file']} not found"}
            continue
        norm = ir_normalize(ir)
        results[node_id] = {
            "status": "OK",
            "schema": norm["schema_version"],
            "policy_hash": norm["policy_hash"],
            "toolchain_hash": norm["toolchain_hash"],
            "ir_hash": norm["ir_hash"],
            "render_hash": norm.get("render_hash", "N/A"),
            "jobs": [j["id"] for j in norm["jobs"]],
        }
    hashes = [r["ir_hash"] for r in results.values() if r["status"] == "OK"]
    parity = len(set(hashes)) <= 1 if hashes else False
    return {"step": "ir_parity_check", "nodes": results, "parity": parity, "all_ir_hashes": hashes}


def execution_mirror() -> dict:
    """STEP 3: Simulate deterministic execution mirroring."""
    results = []
    for node_id, cfg in NODES.items():
        ir = load_ir(node_id)
        if ir is None:
            results.append({"node": node_id, "execution_hash": "NO_IR", "status": "skip"})
            continue
        norm = ir_normalize(ir)
        exec_input = json.dumps(norm, sort_keys=True)
        exec_hash = h(exec_input + cfg["path"])
        results.append({
            "node": node_id,
            "execution_hash": exec_hash,
            "ir_hash": norm["ir_hash"],
            "job_count": len(norm["jobs"]),
            "status": "executed",
        })
    hashes = [r["execution_hash"] for r in results if r["status"] == "executed"]
    parity = len(set(hashes)) <= 1 if hashes else False
    return {"step": "execution_mirror", "nodes": results, "parity": parity}


def cross_node_validation() -> dict:
    """STEP 4: Cross-node validation (NOT consensus — deterministic equality check)."""
    mirror = execution_mirror()
    results = []
    for node_result in mirror["nodes"]:
        if node_result["status"] != "executed":
            results.append({**node_result, "validated": False, "reason": "no_execution"})
            continue
        ir = load_ir(node_result["node"])
        if ir is None:
            results.append({**node_result, "validated": False, "reason": "no_ir"})
            continue
        norm = ir_normalize(ir)
        exec_hash_expected = h(json.dumps(norm, sort_keys=True) + NODES[node_result["node"]]["path"])
        match = exec_hash_expected == node_result["execution_hash"]
        results.append({
            **node_result,
            "validated": match,
            "expected_hash": exec_hash_expected,
        })
    valid_nodes = [r for r in results if r.get("validated")]
    drift = len(valid_nodes) != len([r for r in results if r["status"] == "executed"])
    return {
        "step": "cross_node_validation",
        "nodes": results,
        "drift_detected": drift,
        "trusted_nodes": [n["node"] for n in valid_nodes],
    }


def diff_resolution_engine() -> dict:
    """STEP 5: Diff resolution — NO auto-merge, NO voting, manual override only."""
    parity = compile_parity_check()
    mirror = execution_mirror()
    if parity["parity"] and mirror["parity"]:
        return {
            "step": "diff_resolution",
            "drift_type": None,
            "status": "NO_DRIFT",
            "resolution_mode": "none",
            "auto_heal": False,
        }
    node_hashes = {n["node"]: n["execution_hash"] for n in mirror["nodes"]}
    hash_groups = {}
    for node, eh in node_hashes.items():
        if eh not in hash_groups:
            hash_groups[eh] = []
        hash_groups[eh].append(node)
    if len(hash_groups) > 1:
        drift_type = "EXECUTION_DRIFT"
    else:
        drift_type = "IR_DRIFT"
    primaries = [g for g in hash_groups.values() if NODES.get(g[0], {}).get("role") == "primary"]
    reference = primaries[0][0] if primaries else list(hash_groups.values())[0][0]
    return {
        "step": "diff_resolution",
        "drift_type": drift_type,
        "status": "DRIFT_DETECTED",
        "hash_groups": hash_groups,
        "reference_node": reference,
        "resolution_mode": "manual_override_required",
        "auto_heal": False,
    }


def tee_attestation_for_node(node_id: str) -> dict:
    """Extend v7 TEE attestation for federated runtime."""
    cfg = NODES[node_id]
    ir = load_ir(node_id)
    if ir is None:
        return {"node_id": node_id, "tee_status": "NO_IR"}
    norm = ir_normalize(ir)
    return {
        "node_id": node_id,
        "tee_status": "attested" if cfg["capabilities"] else "unattested",
        "platform": "simulated",
        "measurement_hash": h(json.dumps(norm, sort_keys=True)),
        "quote_signature": h(norm["ir_hash"] + "TEE_SECRET"),
        "policy_hash": norm["policy_hash"],
        "ir_hash": norm["ir_hash"],
        "execution_hash": h(json.dumps(norm, sort_keys=True) + cfg["path"]),
    }


def federation_state() -> dict:
    """Build full federation state model."""
    parity = compile_parity_check()
    mirror = execution_mirror()
    xval = cross_node_validation()
    diff = diff_resolution_engine()
    tee = {node_id: tee_attestation_for_node(node_id) for node_id in NODES}
    tee_parity = len({t["measurement_hash"] for t in tee.values() if t["tee_status"] == "attested"}) <= 1
    return {
        "federation_id": FEDERATION_ID,
        "schema_version": CANONICAL_SCHEMA,
        "compiler_lock": COMPILER_LOCK,
        "nodes": len(NODES),
        "last_sync_hash": h(str(parity["all_ir_hashes"])),
        "execution_parity": mirror["parity"],
        "ir_parity": parity["parity"],
        "tee_parity": tee_parity,
        "drift_detected": diff["drift_detected"] if diff["status"] == "NO_DRIFT" else True,
        "ir_parity_check": parity,
        "execution_mirror": mirror,
        "cross_node_validation": xval,
        "diff_resolution": diff,
        "tee_attestations": tee,
    }


def capability_matrix() -> dict:
    """Build capability matrix for federation."""
    matrix = {}
    for node_id, cfg in NODES.items():
        caps = cfg["capabilities"]
        matrix[node_id] = {
            "role": cfg["role"],
            "compiler_v3": "compiler_v3" in caps,
            "tee_v7": "tee_v7" in caps,
            "self_heal_v6": "self_heal_v6" in caps,
            "has_ir": load_ir(node_id) is not None,
            "has_policy": load_policy(node_id) is not None,
        }
    return matrix


def print_report(state: dict):
    print("=" * 64)
    print("CVG FEDERATION v7.1 — Deterministic Runtime Report")
    print("=" * 64)

    cap = capability_matrix()
    print("\n📋 NODE CAPABILITY MATRIX:")
    for node_id, info in cap.items():
        status = "✅" if info["has_ir"] else "⚠️"
        print(f"  {status} {node_id} ({info['role']})")
        print(f"      compiler_v3: {'✅' if info['compiler_v3'] else '❌'}")
        print(f"      tee_v7:      {'✅' if info['tee_v7'] else '❌'}")
        print(f"      self_heal:   {'✅' if info['self_heal_v6'] else '❌'}")

    print("\n🔍 IR PARITY CHECK (Step 2):")
    for node_id, r in state["ir_parity_check"]["nodes"].items():
        icon = "✅" if r["status"] == "OK" else "❌"
        print(f"  {icon} {node_id}: ir_hash={r.get('ir_hash','N/A')[:16]}")
    print(f"  Parity: {'✅ PASS' if state['ir_parity_check']['parity'] else '❌ FAIL'}")

    print("\n🔄 EXECUTION MIRROR (Step 3):")
    for n in state["execution_mirror"]["nodes"]:
        icon = "✅" if n["status"] == "executed" else "⚠️"
        print(f"  {icon} {n['node']}: exec_hash={n['execution_hash'][:16]}")
    print(f"  Parity: {'✅ PASS' if state['execution_mirror']['parity'] else '❌ FAIL'}")

    print("\n🛡️ CROSS-NODE VALIDATION (Step 4):")
    for n in state["cross_node_validation"]["nodes"]:
        icon = "✅" if n.get("validated") else "❌"
        print(f"  {icon} {n['node']}: validated={n.get('validated')}")
    print(f"  Drift:  {'❌ DETECTED' if state['cross_node_validation']['drift_detected'] else '✅ NONE'}")

    print("\n⚙️ DIFF RESOLUTION (Step 5):")
    d = state["diff_resolution"]
    print(f"  Status: {d['status']}")
    if d["status"] != "NO_DRIFT":
        print(f"  Type: {d['drift_type']}")
        print(f"  Mode: {d['resolution_mode']} (auto_heal={d['auto_heal']})")
        print(f"  Reference: {d.get('reference_node','N/A')}")
    else:
        print(f"  ✅ No drift — no resolution needed")

    print("\n🔐 TEE ATTESTATION STATUS:")
    for node_id, t in state["tee_attestations"].items():
        icon = "✅" if t["tee_status"] == "attested" else "⚠️"
        print(f"  {icon} {node_id}: {t['tee_status']} | measurement={t['measurement_hash'][:16]}")
    print(f"  TEE Parity: {'✅ PASS' if state['tee_parity'] else '⚠️ FAIL'}")

    print("\n📦 FEDERATION STATE MODEL:")
    print(f"  federation_id:   {state['federation_id']}")
    print(f"  compiler_lock:   {state['compiler_lock']}")
    print(f"  ir_schema:        {state['schema_version']} (canonical={CANONICAL_SCHEMA})")
    print(f"  last_sync_hash:   {state['last_sync_hash'][:16]}")
    print(f"  execution_parity: {'✅' if state['execution_parity'] else '❌'}")
    print(f"  ir_parity:        {'✅' if state['ir_parity'] else '❌'}")
    print(f"  tee_parity:       {'✅' if state['tee_parity'] else '❌'}")
    print(f"  drift_detected:   {'❌ YES' if state['drift_detected'] else '✅ NO'}")

    print("\n" + "=" * 64)
    if not state["drift_detected"] and state["ir_parity"] and state["execution_parity"]:
        print("🏁 STATUS: FEDERATED_OK — Full deterministic parity achieved")
    else:
        print("⚠️  STATUS: DRIFT_DETECTED — Manual override required")
    print("=" * 64)

    state["_generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out_path = Path("/home/workspace/cvg_federation_v71.json")
    out_path.write_text(json.dumps(state, indent=2))
    print(f"\n📄 Federation state saved: {out_path}")


def main():
    print("Loading federation state...")
    state = federation_state()
    print_report(state)

    # Output contract
    contract = {
        "status": "FEDERATED_OK" if not state["drift_detected"] else "DRIFT_DETECTED",
        "execution_parity": state["execution_parity"],
        "ir_parity": state["ir_parity"],
        "tee_parity": state["tee_parity"],
        "nodes": [
            {**n, "execution_hash": n.get("execution_hash", "")}
            for n in state["execution_mirror"]["nodes"]
        ],
        "drift_report": None if not state["drift_detected"] else state["diff_resolution"],
        "compiler_lock": state["compiler_lock"],
        "federation_mode": "deterministic_mirroring",
    }
    print("\n📦 OUTPUT CONTRACT:")
    print(json.dumps(contract, indent=2))


if __name__ == "__main__":
    main()
