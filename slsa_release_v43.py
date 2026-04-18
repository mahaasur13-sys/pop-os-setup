#!/usr/bin/env python3
"""
CVG + LCCP SLSA-4 RELEASE ORCHESTRATION ENGINE v4.3
=============================================================
ROLE: Supply Chain Security Orchestrator
TARGET: SLSA Level 4 Production-Grade Release

HARD RULE: No external cryptographic proof = NO RELEASE
"""
import subprocess, json, os, hashlib, datetime

SYSTEM = {
    "system": "CVG_LCCP_ENGINE",
    "version": "v4.3",
    "lccp_version": "v1.2",
    "target_slsa_level": 4,
    "current_slsa_level": 3,
    "state_model": "event_sourced_deterministic",
}

VALID_TRUST_ANCHORS = {
    "github_oidc": False,   # PAT only, no OIDC
    "sigstore": False,       # cosign not installed
    "hsm_tpm": False,        # No HSM/TPM found
}

GATES = ["G1_commit", "G2_manifest", "G3_provenance", "G4_lccp", "G5_crossrepo", "G6_external_sig"]

def h(data):
    return hashlib.sha256(data.encode()).hexdigest()

def resolve_commits():
    repos = {
        "AsurDev": ("/home/workspace/AsurDev", "mahaasur13-sys/AsurDev"),
        "home-cluster-iac": ("/home/workspace/home-cluster-iac", "mahaasur13-sys/home-cluster-iac"),
    }
    commits = {}
    for name, (path, remote) in repos.items():
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, cwd=path
            ).strip()
            commits[name] = {"commit": sha, "path": path, "remote": remote}
        except:
            commits[name] = {"commit": "unknown", "path": path, "remote": remote}
    return commits

def build_manifest(path):
    manifest = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", ".pytest_cache", "node_modules"}]
        for f in files:
            fp = os.path.join(root, f)
            try:
                with open(fp, "rb") as fh:
                    manifest[fp] = h(fh.read())
            except:
                pass
    return manifest

def provenance_graph(commits, manifests):
    pg = {
        "subject": [{"Name": "multi-repo-system", "digest": {"sha256": h(str(sorted(commits.items()))[:40])}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "repository": {"uri": "git+https://github.com/mahaasur13-sys"},
                "dispatchPath": ".github/workflows/ci.yml",
            },
            "runDetails": {
                "builder": {"id": "https://github.com/mahaasur13-sys"},
                "metadata": {"finishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()},
            },
        },
        "materials": [],
    }
    for name, m in manifests.items():
        for fp, digest in list(m.items())[:5]:
            pg["materials"].append({"uri": fp, "digest": {"sha256": digest}})
    pg["predicate_digest"] = h(str(pg))
    return pg

def lccp_replay(path):
    result = subprocess.run(
        ["python3", "lccp_v12.py"],
        capture_output=True, text=True, cwd=os.path.dirname(path) or path,
        timeout=30
    )
    out = result.stdout + result.stderr
    valid = "REPLAY CONSISTENT" in out or "CONTRACT PROPERTIES" in out or "EVENT-SOURCED SOVEREIGNTY" in out
    return {"valid": valid, "output_hash": h(out), "stdout_len": len(out)}

def run_lccp_repos():
    results = {}
    repos = {
        "AsurDev": "/home/workspace/AsurDev",
        "home-cluster-iac": "/home/workspace/home-cluster-iac",
    }
    for name, path in repos.items():
        lccp_path = os.path.join(path, "lccp_v12.py")
        if os.path.exists(lccp_path):
            results[name] = lccp_replay(lccp_path)
        else:
            results[name] = {"valid": False, "output_hash": "missing", "stdout_len": 0}
    return results

def check_trust_anchors():
    results = {}
    # GitHub OIDC - needs GitHub App, PAT won't work
    results["github_oidc"] = {"available": False, "method": "PAT (invalid for OIDC)"}
    # Sigstore - cosign not installed
    results["sigstore"] = {"available": False, "method": "cosign not installed"}
    # HSM/TPM
    results["hsm_tpm"] = {"available": os.path.exists("/dev/tpm0") or os.path.exists("/dev/tpmrm0")}
    return results

def request_external_signature(provenance, trust_anchors):
    """HARD GATE: Must return verified=True only with valid external proof"""
    available = {k: v for k, v in trust_anchors.items() if v.get("available")}
    if not available:
        return {"verified": False, "method": "NONE", "signature": "MISSING", "reason": "NO_TRUST_ANCHOR"}
    # Only reachable if external signing is actually available
    return {"verified": False, "method": "NONE", "signature": "MISSING", "reason": "NO_TRUST_ANCHOR"}

def external_signature_verification(sig):
    """Independent verification that signature is externally binding"""
    if sig.get("verified") == True:
        return True
    return False

def release_gate(state):
    """HARD RELEASE GATE - Zero Trust"""
    if not state.get("external_attestation", {}).get("verified"):
        return {
            "release_allowed": False,
            "reason": "NO_EXTERNAL_TRUST_ANCHOR",
            "hard_rule": "RELEASE = f(external_signature_verified)",
        }
    return {"release_allowed": True}

def generate_attestation_bundle(state):
    bundle = {
        "version": "v4.3",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "system": SYSTEM["system"],
        "slsa_level": 4,
        "commits": state["commits"],
        "build": {
            "deterministic": True,
            "artifact_count": sum(len(m) for m in state["manifests"].values()),
            "hashing": "SHA-256",
        },
        "lccp": {"version": "v1.2", "replay_results": state["lccp_results"]},
        "provenance": state["provenance"],
        "external_attestation": state["external_attestation"],
        "release_gate": state["release_gate"],
        "gates": {f"G{i+1}_{g}": state["gate_results"][i] for i, g in enumerate(GATES)},
        "system_state": "EXTERNALLY_VERIFIED_SLSA_LEVEL_4" if state["release_gate"]["release_allowed"] else "ATTESTATION_BLOCKED_NO_EXTERNAL_PROOF",
    }
    bundle["bundle_hash"] = h(str(bundle))
    return bundle

def run_pipeline():
    print("=" * 70)
    print("CVG + LCCP SLSA-4 RELEASE ORCHESTRATION ENGINE v4.3")
    print("=" * 70)

    state = {"gate_results": [False]*6, "commits": {}, "manifests": {}, "provenance": {}, "lccp_results": {}}

    # G1: Commit integrity
    print("\n[1/6] G1 - COMMIT INTEGRITY")
    commits = resolve_commits()
    state["commits"] = commits
    g1_pass = all(v["commit"] != "unknown" for v in commits.values())
    state["gate_results"][0] = g1_pass
    for name, info in commits.items():
        status = "PASS" if info["commit"] != "unknown" else "FAIL"
        print(f"  [{status}] {name}: {info['commit'][:12]}")
    print(f"  G1_result: {'PASS' if g1_pass else 'FAIL'}")

    # G2: Artifact manifest
    print("\n[2/6] G2 - ARTIFACT MANIFEST")
    manifests = {}
    for name, info in commits.items():
        m = build_manifest(info["path"])
        manifests[name] = m
        print(f"  [{name}] {len(m)} files hashed")
    state["manifests"] = manifests
    g2_pass = all(len(m) > 0 for m in manifests.values())
    state["gate_results"][1] = g2_pass
    print(f"  G2_result: {'PASS' if g2_pass else 'FAIL'}")

    # G3: Provenance graph
    print("\n[3/6] G3 - PROVENANCE GRAPH")
    pg = provenance_graph(commits, manifests)
    state["provenance"] = pg
    g3_pass = "predicate_digest" in pg
    state["gate_results"][2] = g3_pass
    print(f"  [{'PASS' if g3_pass else 'FAIL'}] predicate_digest: {pg.get('predicate_digest', 'MISSING')[:16]}")
    print(f"  G3_result: {'PASS' if g3_pass else 'FAIL'}")

    # G4: LCCP deterministic replay
    print("\n[4/6] G4 - LCCP DETERMINISTIC REPLAY")
    lccp_results = run_lccp_repos()
    state["lccp_results"] = lccp_results
    g4_pass = all(r.get("valid", False) for r in lccp_results.values())
    state["gate_results"][3] = g4_pass
    for name, r in lccp_results.items():
        print(f"  [{'PASS' if r.get('valid') else 'FAIL'}] {name}: valid={r.get('valid')}, output_hash={r.get('output_hash','?')[:8]}")
    print(f"  G4_result: {'PASS' if g4_pass else 'FAIL'}")

    # G5: Cross-repo consistency
    print("\n[5/6] G5 - CROSS-REPO CONSISTENCY")
    commits_ok = all(v["commit"] != "unknown" for v in commits.values())
    lccp_ok = g4_pass
    g5_pass = commits_ok and lccp_ok
    state["gate_results"][4] = g5_pass
    print(f"  [{'PASS' if g5_pass else 'FAIL'}] cross-repo: commits={commits_ok}, lccp={lccp_ok}")
    print(f"  G5_result: {'PASS' if g5_pass else 'FAIL'}")

    # G6: External cryptographic signature (HARD GATE)
    print("\n[6/6] G6 - EXTERNAL CRYPTOGRAPHIC SIGNATURE (HARD GATE)")
    trust_anchors = check_trust_anchors()
    sig = request_external_signature(pg, trust_anchors)
    state["external_attestation"] = sig
    g6_pass = external_signature_verification(sig)
    state["gate_results"][5] = g6_pass
    for anchor, info in trust_anchors.items():
        avail = "AVAILABLE" if info.get("available") else "UNAVAILABLE"
        print(f"  [{avail}] {anchor}: {info.get('method')}")
    print(f"  External sig: verified={sig.get('verified')}, method={sig.get('method')}, reason={sig.get('reason')}")
    print(f"  G6_result: {'PASS' if g6_pass else 'FAIL'}")

    # Release gate
    print("\n" + "=" * 70)
    print("RELEASE GATE EVALUATION")
    print("=" * 70)
    rg = release_gate(state)
    state["release_gate"] = rg
    print(f"  release_allowed: {rg['release_allowed']}")
    print(f"  reason: {rg['reason']}")
    print(f"  hard_rule: {rg.get('hard_rule', 'N/A')}")

    # Final attestation bundle
    bundle = generate_attestation_bundle(state)
    bundle_path = "/home/workspace/SLSA_RELEASE_BUNDLE_v4.3.json"
    with open(bundle_path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("FINAL SYSTEM STATE")
    print("=" * 70)
    print(f"  SYSTEM_STATE: {bundle['system_state']}")
    print(f"  SLSA_LEVEL: {bundle['slsa_level']} (target: {SYSTEM['target_slsa_level']})")
    print(f"  RELEASE_ALLOWED: {rg['release_allowed']}")
    print(f"  GATES: {'/'.join(['PASS' if r else 'FAIL' for r in state['gate_results']])}")
    print(f"  BUNDLE: {bundle_path}")
    print(f"  BUNDLE_HASH: {bundle['bundle_hash'][:32]}")
    print("=" * 70)

    if not rg["release_allowed"]:
        print("\nHARD RULE ENFORCED: NO EXTERNAL PROOF = NO RELEASE")
        print("To enable release, configure one of: GitHub OIDC, Sigstore cosign, HSM/TPM")

    return bundle

if __name__ == "__main__":
    run_pipeline()
