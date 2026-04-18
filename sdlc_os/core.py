"""SDLC OS Core - Entry point runtime."""

from sdlc_os.kernel.engine import Kernel
from sdlc_os.sdlc_types import SystemStateSnapshot
import json
import sys
from pathlib import Path


def run_sdlc_scan(repo_path: str) -> dict:
    """Main entry point for SDLC OS scan."""
    kernel = Kernel()
    snapshot = kernel.execute(repo_path)
    return snapshot.to_dict()


def print_summary(snapshot: dict) -> None:
    """Print human-readable summary of scan results."""
    print("\n" + "="*60)
    print("SDLC OS - System State Snapshot")
    print("="*60)
    print(f"Repository: {snapshot.get('repo_path', 'unknown')}")
    print(f"Timestamp:  {snapshot.get('timestamp', 'unknown')}")
    print()
    print(f"Drift Score: {snapshot.get('drift_score', 0):.3f}")
    print(f"Drift Level: {snapshot.get('drift_level', 'unknown')}")
    print()
    
    nodes = snapshot.get('graph_nodes', [])
    edges = snapshot.get('graph_edges', [])
    print(f"Graph: {len(nodes)} nodes, {len(edges)} edges")
    
    diffs = snapshot.get('diffs', [])
    print(f"Diffs: {len(diffs)} changes analyzed")
    
    anomalies = snapshot.get('anomalies', [])
    print(f"Anomalies: {len(anomalies)} detected")
    
    for a in anomalies:
        print(f"  - [{a.get('level', '?')}] {a.get('signal_type', 'unknown')}: {a.get('description', '')}")
    
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m sdlc_os.core <repo_path>")
        print("Example: python -m sdlc_os.core /home/workspace/AstroFinSentinelV5")
        sys.exit(1)
    
    repo_path = sys.argv[1]
    
    if not Path(repo_path).exists():
        print(f"Error: Path does not exist: {repo_path}")
        sys.exit(1)
    
    result = run_sdlc_scan(repo_path)
    print_summary(result)
    
    if "--json" in sys.argv:
        output_path = Path(repo_path).parent / "sdlc_snapshot.json"
        with open(output_path, "w") as f:
            f.write(json.dumps(result, indent=2))
        print(f"Snapshot saved to: {output_path}")
