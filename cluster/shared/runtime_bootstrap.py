import sys
import os

# Resolve shared = cluster/shared, atomos = repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # cluster/
sys.path.insert(0, REPO_ROOT)

from shared.drl_bridge import DRLBridge
from shared.rpc_server import RPCServer


class BootstrapNode:
    def __init__(self, node_id: str, peers: list[str]):
        self.node_id = node_id
        self.peers = peers
        self.drl = None
        self.rpc = None
        self.sbs = None
        self._running = False

    def start(self):
        print(f"[BOOT] {self.node_id} starting with peers: {self.peers}")

        self._init_drl()
        self._init_rpc()
        self._init_sbs()

        self._running = True
        print(f"[BOOT] {self.node_id} ready")

    def _init_drl(self):
        self.drl = DRLBridge(self.node_id)
        print(f"[BOOT] {self.node_id} DRL bridge initialized (loss={self.drl.loss_rate}, delay={self.drl.delay}s)")

    def _init_rpc(self):
        self.rpc = RPCServer(self.node_id, self.peers)
        self.rpc.start()
        print(f"[BOOT] {self.node_id} RPC server started")

    def _init_sbs(self):
        try:
            from atomos.sbs.global_invariant_engine import GlobalInvariantEngine
            self.sbs = GlobalInvariantEngine(mode="distributed")
            print(f"[BOOT] {self.node_id} SBS GlobalInvariantEngine initialized (mode=distributed)")
        except ImportError as e:
            print(f"[WARN] {self.node_id} SBS not available: {e}")
            self.sbs = None

    def stop(self):
        self._running = False
        if self.rpc:
            self.rpc.stop()
        print(f"[SHUTDOWN] {self.node_id} stopped")
