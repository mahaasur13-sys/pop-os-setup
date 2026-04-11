import os
import sys
import time
import signal

# Add /app to path so 'from atomos import ...' resolves
sys.path.insert(0, "/app")

from shared.runtime_bootstrap import BootstrapNode

NODE_ID = os.getenv("NODE_ID", "unknown")
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]

node = BootstrapNode(node_id=NODE_ID, peers=PEERS)

def shutdown(signum, frame):
    print(f"\n[SHUTDOWN] {NODE_ID} stopping gracefully...")
    node.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

node.start()

print(f"[READY] {NODE_ID} — type 'help' for commands")

while True:
    time.sleep(1)
