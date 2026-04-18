"""
ATOM OS v14.2 — RPC Mesh
Peer registry, latency measurement, message routing.
"""
from __future__ import annotations
import time, random
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class Peer:
    node_id: str
    address: str
    latency_ms: float = 0.0
    status: str = "ACTIVE"

class RPCMesh:
    """Peer-to-peer RPC mesh with latency tracking."""

    def __init__(self, local_node_id: str):
        self.local_node_id = local_node_id
        self._peers: Dict[str, Peer] = {}
        self._outbox = []

    def register_peer(self, node_id: str, address: str):
        self._peers[node_id] = Peer(node_id=node_id, address=address)

    def measure_latency(self, node_id: str) -> float:
        if node_id in self._peers:
            self._peers[node_id].latency_ms = random.uniform(0.5, 5.0)
        return self._peers.get(node_id, Peer(node_id=node_id, address='')).latency_ms or 1.0

    def send_rpc(self, target: str, payload: dict) -> Optional[dict]:
        msg = {'from': self.local_node_id, 'to': target, 'payload': payload, 'status': 'pending', 'ts': time.time()}
        self._outbox.append(msg)
        return msg

if __name__ == "__main__":
    mesh = RPCMesh("node-1")
    mesh.register_peer("node-2", "node-2:7000")
    print(f"Peers: {len(mesh._peers)}, latency: {mesh.measure_latency('node-2'):.1f}ms")
