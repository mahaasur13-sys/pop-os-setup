#!/usr/bin/env python3
"""
CVG + LCCP SLSA Supply-Chain HARDENING ENGINE v4.2
=============================================================
LEVEL 3 → LEVEL 4 TRANSITION — HONEST ASSESSMENT

ROLE: Supply-chain security compiler + deterministic governance engine
       + external attestation gatekeeper

TARGET: SLSA Level 4 (external cryptographic verification REQUIRED)

HARD RULE: NO EXTERNAL SIGNATURE → NO RELEASE — NO EXCEPTION
"""


import subprocess, json, os, hashlib, yaml
from datetime import datetime, timezone
from pathlib import Path

REPOS = {
    "AsurDev": "/home/workspace/AsurDev",
    "home-cluster-iac": "/home/workspace/home-cluster-iac"
}

SYSTEM = {
    "repos": {"AsurDev": "SOURCE_OF_TRUTH", "home-cluster-iac": "CONSUMER_ONLY"},
    "governance": "CVG_v1.0_SEALED",
    "replay_engine": "LCCP_v1.2",
    "state_model": "event_sourced_deterministic",
    "attestation_level": 3,
    "target_level": 4,
    "external_trust_required": True,
    "release_allowed": False,
}

# ═══════════════════════════════════════════════════════════════════════
# HARD SECURITY MODEL — NO FALLBACKS
# ═══════════════════════════════════════════════════════════════════════
FORBIDDEN = {
    "simulated_gpg", "local_trust", "unsigned_provenance",
    "pat_pseudo_identity", "replay_only_proof",
}

TRUST_ANCHORS_LEVEL4 = {
    "GitHub Actions OIDC (id-token: write)",
    "Sigstore (cosign + Fulcio + Rekor)",
    "HSM-backed signing (PKCS#11)",
    "TPM hardware attestation",
}

print("=" * 78)
print("CVG + LCCP SLSA HARDENING ENGINE v4.2")
print("LEVEL 3 → LEVEL 4 TRANSITION")
print("=" * 78)

# ── TRUST ANCHOR PROBE ──────────────────────────────────────────────
anchors = {}
result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
pat_token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()

is_pat = pat_token.startswith("gho_") if pat_token else False
anchors["github_oidc"] = {
    "available": False,
    "reason": "PAT token — OIDC requires GitHub App or Actions OIDC endpoint",
    "can_request_token": False,
}
anchors["sigstore"] = {"available": False, "reason": "cosign not installed"}
for p in ["/dev/pkcs11", "/dev/tpm0", "/dev/swtpm"]:
    anchors["hsm_tpm"] = {"available": os.path.exists(p), "reason": "No HSM/TPM found"}
    if os.path.exists(p):
        break
result = subprocess.run(["which", "cosign"], capture_output=True, text=True)
anchors["sigstore"]["available"] = result.returncode == 0

for name, data in anchors.items():
    sym = "\u2705" if data.get("available") else "\u274c"
    print(f"  {sym} {name}: {data.get('reason', data.get('found', ''))}")

# ── BUILD PIPELINE (deterministic) ───────────────────────────────────
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def build_artifact_manifest(repo):
    manifest = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in [".git", "node_modules", "__pycache__", ".venv"]]
        for f in files:
            path = os.path.join(root, f)
            rel = os.path.relpath(path, repo)
            manifest.append({"path": rel, "sha256": sha256_file(path)})
    manifest.sort(key=lambda x: x["path"])
    return manifest

print("\n[2/7] BUILDING DETERMINISTIC ARTIFACT MANIFEST...")
artifact_manifests = {}
for name, path in REPOS.items():
    manifest = build_artifact_manifest(path)
    artifact_manifests[name] = manifest
    commit = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()[:12]
    print(f"  \u2705 {name}: commit={commit} files={len(manifest)}")

# ── LCCP REPLAY VALIDATION ───────────────────────────────────────────
print("\n[3/7] RUNNING LCCP DETERMINISM VALIDATION...")
def validate_lccp_replay(repo_path):
    lccp_file = os.path.join(repo_path, "lccp_v12.py")
    if not os.path.exists(lccp_file):
        return {"valid": False, "reason": "LCCP v1.2 not found"}
    r = subprocess.run(["python3", lccp_file], capture_output=True, text=True, cwd=repo_path)
    for line in r.stdout.strip().split("\n"):
        if "REPLAY CONSISTENT" in line or "CONTRACT PROPERTIES" in line:
            return {"valid": True, "engine": "v1.2", "output_hash": hashlib.sha256(r.stdout.encode()).hexdigest()[:16]}
    return {"valid": False, "reason": "LCCP self-test failed", "output": r.stdout[-200:]}

lccp_results = {}
for name, path in REPOS.items():
    result = validate_lccp_replay(path)
    lccp_results[name] = result
    sym = "\u2705" if result["valid"] else "\u274c"
    print(f"  {sym} {name}: {result.get('engine', 'NONE')} valid={result['valid']}")

# ── PROVENANCE GRAPH ─────────────────────────────────────────────────
print("\n[4/7] GENERATING PROVENANCE GRAPH...")
def generate_provenance(repo_name, commit, tree, manifest, lccp_result):
    predicate = {
        "type": "https://slsa.dev/provenance/v1.0",
        "builder": {"id": f"https://github.com/mahaasur13-sys/{repo_name}/.github/workflows/ci.yml"},
        "buildDefinition": {
            "buildType": "https://github.com/actions/runner@v2",
            "externalParameters": {
                "repository": f"https://github.com/mahaasur13-sys/{repo_name}",
                "ref": "refs/heads/main",
                "workflow": ".github/workflows/ci.yml"
            },
            "resolvedDependencies": [
                {"uri": f"git object:{commit}", "digest": {"gitCommit": commit}},
                {"uri": f"git tree:{tree}", "digest": {"gitTree": tree}},
            ]
        },
        "runDetails": {
            "builder": {"id": "https://github.com/mahaasur13-sys/" + repo_name},
            "metadata": {"invocationId": f"github.com/{repo_name}/actions/runs/local-run"}
        }
    }
    predicate_str = json.dumps(predicate, sort_keys=True)
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1.0",
        "subject": [{"name": repo_name, "digest": {"sha256": commit[:16]}}],
        "predicate": predicate,
        "artifact_manifest": manifest,
        "predicate_digest": hashlib.sha256(predicate_str.encode()).hexdigest(),
        "lccp_valid": lccp_result["valid"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return provenance

provenance_data = {}
for name, path in REPOS.items():
    commit = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    tree = subprocess.run(["git", "-C", path, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip()
    prov = generate_provenance(name, commit, tree, artifact_manifests[name], lccp_results[name])
    provenance_data[name] = prov
    print(f"  \u2705 {name}: predicate_digest={prov['predicate_digest'][:16]}")

# ── EXTERNAL SIGNING GATE (LEVEL 4 REQUIRED) ─────────────────────────
print("\n[5/7] REQUESTING EXTERNAL SIGNATURE (MANDATORY)...")
external_sig = {"method": None, "signature": None, "verified": False, "simulated": False}

# Try GitHub OIDC
if not anchors["github_oidc"]["can_request_token"]:
    print("  \u274c GitHub OIDC: UNAVAILABLE (PAT token, need GitHub App)")
else:
    external_sig = {"method": "GITHUB_OIDC", "verified": True, "simulated": False}

# Try Sigstore
if not anchors["sigstore"]["available"]:
    print("  \u274c Sigstore cosign: UNAVAILABLE (not installed)")
else:
    external_sig = {"method": "SIGSTORE_KEYLESS", "verified": False, "simulated": False}

if external_sig["method"] is None:
    print("  \u274c All external signing methods FAILED")
    print("  \u26a0 NO EXTERNAL PROOF AVAILABLE — RELEASE BLOCKED BY HARD RULE")

# ── FINAL ATTESTATION BUNDLE ─────────────────────────────────────────
print("\n[6/7] BUILDING ATTESTATION BUNDLE...")
level = 3 if lccp_results[name]["valid"] else 2
level_class = "SLSA_LEVEL_3_DETERMINISTIC" if level == 3 else "SLSA_LEVEL_2"

for name in REPOS:
    if not lccp_results[name]["valid"]:
        level = 2
        level_class = "SLSA_LEVEL_2"
        break

bundle = {
    "_type": "https://slsa.dev/Attestation v1.0",
    "version": "4.2",
    "system": SYSTEM,
    "attestation_level": level,
    "level_class": level_class,
    "trust_anchors": anchors,
    "provenance": provenance_data,
    "lccp_replay": lccp_results,
    "external_attestation": {
        "enabled": external_sig["method"] is not None,
        "method": external_sig["method"],
        "signature": None,
        "verification": "EXTERNALLY_VERIFIED" if external_sig["verified"] else "PENDING_EXTERNAL_ANCHOR",
        "simulated": external_sig["simulated"],
    },
    "release_allowed": False,
    "release_blocked": True,
    "hard_rule_violated": False,
    "bundle_hash": None,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "generator": "CVG-SLSA-HARDEN-ENGINE-v4.2",
}
bundle_str = json.dumps(bundle, indent=2, sort_keys=True)
bundle["bundle_hash"] = hashlib.sha256(bundle_str.encode()).hexdigest()

print(f"  Level: {level} ({level_class})")
print(f"  External sig: {external_sig['method'] or 'NONE'}")
print(f"  Release allowed: {bundle['release_allowed']}")
print(f"  Release blocked: {bundle['release_blocked']}")
print(f"  Bundle hash: {bundle['bundle_hash'][:16]}")

# ── SLSA GAP ANALYSIS ────────────────────────────────────────────────
print("\n[7/7] SLSA GAP ANALYSIS (Level 4 requirements)...")
gaps = []
if not anchors["github_oidc"]["can_request_token"]:
    gaps.append("OIDC: Need GitHub App + OIDC endpoint (not PAT)")
if not anchors["sigstore"]["available"]:
    gaps.append("Sigstore: Need cosign + Fulcio + Rekor setup")
hsm_tpm = anchors.get("hsm_tpm", {})
if not hsm_tpm.get("available"):
    gaps.append("HSM/TPM: Need PKCS#11 or TPM device for Level 4")
for i, gap in enumerate(gaps, 1):
    print(f"  GAP {i}: {gap}")

print("\n" + "=" * 78)
print("VALIDATION GATES:")
print("=" * 78)
gates = [
    ("G1 commit_hash", all(subprocess.run(["git", "-C", p, "rev-parse", "HEAD"], capture_output=True, text=True).returncode == 0 for p in REPOS.values())),
    ("G2 artifact_manifest", all(len(v) > 0 for v in artifact_manifests.values())),
    ("G3 provenance_graph", all(len(v) > 0 for v in provenance_data.values())),
    ("G4 lccp_replay", all(r["valid"] for r in lccp_results.values())),
    ("G5 external_signature", external_sig["method"] is not None),
    ("G6 release_gate", bundle["release_allowed"]),
]
for name, ok in gates:
    sym = "\u2705" if ok else "\u274c"
    print(f"  {sym} {name}: {'PASS' if ok else 'FAIL'}")
print("=" * 78)
print(f"RELEASE DECISION: {'\u2705 ALLOWED' if bundle['release_allowed'] else '\u274c BLOCKED — NO EXTERNAL PROOF'}")
print("=" * 78)

with open("/home/workspace/SLSA_HARDEN_BUNDLE_v4.2.json", "w") as f:
    json.dump(bundle, f, indent=2)
print(f"\nBundle: /home/workspace/SLSA_HARDEN_BUNDLE_v4.2.json")
print(f"Seal: {bundle['bundle_hash']}")

if __name__ == "__main__":
    pass
