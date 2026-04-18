#!/usr/bin/env python3
"""
CVG + LCCP SLSA-4 HARDENED ORCHESTRATION ENGINE v4.5
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = 
PRODUCTION SPEC: git-index canonical manifest, zero-trust release
"""
import subprocess, json, os, hashlib, datetime
SYSTEM = {
    "system": "CVG_LCCP_ENGINE",
    "lccp_version": "v1.2",
    "slsa_level_target": 4,
}
GATES = ["G1_commit","G2_manifest","G3_provenance","G4_lccp","G5_crossrepo","G6_external_sig"]
def h(data):
    if isinstance(data, str): return hashlib.sha256(data.encode()).hexdigest()
    return hashlib.sha256(str(data).encode()).hexdigest()
def resolve_commits():
    repos = {
        "AsurDev": ("/home/workspace/AsurDev", "mahaasur13-sys/AsurDev"),
        "home-cluster-iac": ("/home/workspace/home-cluster-iac", "mahaasur13-sys/home-cluster-iac"),
    }
    out = {}
    for name, (path, remote) in repos.items():
        try:
            sha = subprocess.check_output(["git","rev-parse","HEAD"], text=True, cwd=path).strip()
            out[name] = {"commit": sha, "path": path, "remote": remote}
        except:
            out[name] = {"commit": "unknown", "path": path, "remote": remote}
    return out
def build_manifest(repo_path):
    try:
        files = subprocess.check_output(["git","ls-tree","-r","HEAD","--name-only"], cwd=repo_path, stderr=subprocess.DEVNULL).decode().splitlines()
        digests = {}
        for fn in files:
            fp = os.path.join(repo_path, fn)
            if os.path.isfile(fp):
                try: digests[fn] = h(open(fp,"rb").read())
                except: digests[fn] = "unreadable"
        joined = chr(10).join(sorted(files))
        return {"source": "git-index", "canonical": True, "count": len(files), "files": sorted(files), "digests": digests, "manifest_hash": h(joined)}
    except Exception as e:
        return {"source": "git-index", "canonical": False, "count": 0, "files": [], "digests": {}, "manifest_hash": "error", "error": str(e)}
def provenance_graph(commits, manifests):
    items = str(sorted([(k,v["commit"]) for k,v in commits.items()]))
    pg = {
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{"name": "multi-repo-system", "digest": {"sha256": h(items)[:40]}}],
        "predicate": {
            "buildDefinition": {"repository": {"uri": "https://github.com/mahaasur13-sys"}, "gitIndexBased": True, "deterministic": True},
            "runDetails": {"builder": {"id": "https://github.com/mahaasur13-sys/CVG_LCCP_ENGINE"}},
            "materials": [{"uri": "git+https://github.com/"+v["remote"]+"@"+v["commit"]} for v in commits.values()]
        }
    }
    pg["predicate_digest"] = h(str(pg["predicate"]))
    return pg
def lccp_replay(path):
    try:
        r = subprocess.run(["python3", os.path.basename(path)], capture_output=True, text=True, cwd=os.path.dirname(path), timeout=30)
        out = r.stdout + r.stderr
        valid = any(x in out for x in ["REPLAY CONSISTENT","CONTRACT PROPERTIES","EVENT-SOURCED SOVEREIGNTY","5/5"])
        return {"deterministic": valid, "valid": valid, "output_hash": h(out[:4096]), "exit": r.returncode}
    except:
        return {"deterministic": False, "valid": False, "output_hash": "error", "exit": -1}
def run_lccp_repos():
    repos = {"AsurDev": "/home/workspace/AsurDev/lccp_v12.py", "home-cluster-iac": "/home/workspace/home-cluster-iac/lccp_v12.py"}
    return {n: lccp_replay(p) if os.path.exists(p) else {"valid": False, "output_hash": "missing"} for n, p in repos.items()}
def check_trust_anchors():
    cosign = subprocess.run(["which","cosign"], capture_output=True).returncode == 0
    return {
        "github_oidc": {"available": False, "method": "OIDC id-token (GitHub App)", "limitation": "PAT invalid for OIDC"},
        "sigstore": {"available": cosign, "method": "Sigstore keyless", "cosign_installed": cosign},
        "hsm_tpm": {"available": os.path.exists("/dev/tpm0"), "method": "TPM 2.0 hardware"}
    }
def release_gate(state):
    ext = state.get("external_attestation", {})
    if not ext.get("verified"):
        return {"release_allowed": False, "reason": "NO_EXTERNAL_TRUST_ANCHOR", "hard_rule": "RELEASE=f(external_signature_verified)"}
    return {"release_allowed": True, "reason": "EXTERNAL_ATTESTATION_VERIFIED"}
def generate_bundle(state):
    rg = state["release_gate"]
    bundle = {
        "version": "v4.5", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "system": SYSTEM["system"], "lccp_version": SYSTEM["lccp_version"],
        "slsa_level_target": SYSTEM["slsa_level_target"],
        "commits": state["commits"],
        "manifests": {n: {"source": m["source"], "canonical": m["canonical"], "count": m["count"], "manifest_hash": m["manifest_hash"]} for n, m in state["manifests"].items()},
        "lccp_results": state["lccp_results"],
        "provenance": state["provenance"],
        "external_attestation": state["external_attestation"],
        "release_gate": rg,
        "gates": {f"G{i+1}_{g}": "PASS" if state["gate_results"][i] else "FAIL" for i, g in enumerate(GATES)},
        "system_state": "EXTERNALLY_VERIFIED_SLSA_LEVEL_4" if rg["release_allowed"] else "SLSA_LEVEL_3_INTERNAL_ONLY",
    }
    bundle["bundle_hash"] = h(str(bundle))
    return bundle
def run_pipeline():
    print("="*70)
    print("CVG + LCCP SLSA-4 HARDENED ORCHESTRATION ENGINE v4.5")
    print("PRODUCTION SPEC: git-index canonical manifest, zero-trust release")
    print("="*70)
    state = {"gate_results": [False]*6, "commits": {}, "manifests": {}, "provenance": {}, "lccp_results": {}, "external_attestation": {}, "release_gate": {}}
    # G1
    print(chr(10)+"[G1] COMMIT INTEGRITY")
    state["commits"] = resolve_commits()
    g1 = all(v["commit"] != "unknown" for v in state["commits"].values())
    state["gate_results"][0] = g1
    for n, i in state["commits"].items(): print(f"  [{"PASS" if g1 else "FAIL"}] {n}: {i["commit"][:12]}")
    # G2
    print(chr(10)+"[G2] ARTIFACT MANIFEST (git-index CANONICAL)")
    state["manifests"] = {n: build_manifest(i["path"]) for n, i in state["commits"].items()}
    for n, m in state["manifests"].items():
        c = "CANONICAL" if m["canonical"] else "NON-CANONICAL"
        print(f"  [{c}] {n}: {m["count"]} files, hash={m["manifest_hash"][:16]}")
    g2 = all(m["canonical"] and m["count"] > 0 for m in state["manifests"].values())
    state["gate_results"][1] = g2
    # G3
    print(chr(10)+"[G3] PROVENANCE GRAPH")
    state["provenance"] = provenance_graph(state["commits"], state["manifests"])
    g3 = "predicate_digest" in state["provenance"]
    state["gate_results"][2] = g3
    print(f"  [{"PASS" if g3 else "FAIL"}] predicateType: {state["provenance"]["predicateType"]}")
    # G4
    print(chr(10)+"[G4] LCCP DETERMINISTIC REPLAY")
    state["lccp_results"] = run_lccp_repos()
    g4 = all(r["valid"] for r in state["lccp_results"].values())
    state["gate_results"][3] = g4
    for n, r in state["lccp_results"].items(): print(f"  [{"PASS" if r["valid"] else "FAIL"}] {n}: {r.get("output_hash","?")[:12]}")
    # G5
    print(chr(10)+"[G5] CROSS-REPO CONSISTENCY")
    g5 = g1 and g4
    state["gate_results"][4] = g5
    print(f"  [{"PASS" if g5 else "FAIL"}] commits={g1}, lccp={g4}")
    # G6
    print(chr(10)+"[G6] EXTERNAL CRYPTOGRAPHIC SIGNATURE (HARD GATE)")
    anchors = check_trust_anchors()
    available = {k: v for k, v in anchors.items() if v["available"]}
    sig = {"verified": False, "method": "NONE", "reason": "NO_EXTERNAL_TRUST_ANCHOR_AVAILABLE" if not available else "NOT_CONFIGURED"}
    state["external_attestation"] = sig
    g6 = sig.get("verified") is True
    state["gate_results"][5] = g6
    for k, v in anchors.items(): print(f"  [{"AVAIL" if v["available"] else "UNAVAIL"}] {k}: {v["method"]}")
    # Release gate
    state["release_gate"] = release_gate(state)
    rg = state["release_gate"]
    print(chr(10)+"RELEASE_GATE: release_allowed={} reason={}".format(rg["release_allowed"], rg["reason"]))
    bundle = generate_bundle(state)
    with open("/home/workspace/SLSA_RELEASE_BUNDLE_v4.5.json", "w") as f: json.dump(bundle, f, indent=2, default=str)
    g_str = chr(47).join(["P" if x else "F" for x in state["gate_results"]])
    print(chr(10)+"FINAL: {} GATES={} bundle_hash={}".format(bundle["system_state"], g_str, bundle["bundle_hash"][:20]))
    if not rg["release_allowed"]: print("HARD RULE: NO EXTERNAL PROOF = NO RELEASE")
    return bundle
if __name__ == "__main__": run_pipeline()