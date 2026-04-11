import threading
import time
import random
import grpc
from concurrent import futures
from typing import Callable

import sys
import os
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# ── gRPC Protobuf definitions ──────────────────────────────────────────────
import proto.atom_os_pb2 as pb2
import proto.atom_os_pb2_grpc as pb2_grpc


class NodeRPCServicer(pb2_grpc.NodeRPCServicer):
    """gRPC servicer — handles inbound RPCs."""

    def __init__(self, node_id: str, peers: list[str]):
        self.node_id = node_id
        self.peers = peers
        self._app = None          # set via set_app()
        self._shutdown = threading.Event()

    def set_app(self, app):
        self._app = app

    # ── Unary RPC ──────────────────────────────────────────────────────────
    def Ping(self, request, context):
        return pb2.Pong(
            node_id=self.node_id,
            term=self._app.current_term() if self._app else 0,
            ok=True,
        )

    def Forward(self, request, context):
        """Forward a command to the local node's SBS engine."""
        result = self._app.execute(request.command) if self._app else "no-app"
        return pb2.ForwardResponse(success=True, result=result)

    # ── Streaming RPC ─────────────────────────────────────────────────────
    def StreamEvents(self, request, context):
        """Server-side stream: push events to subscriber."""
        for i in range(50):  # up to 50 events then re-query
            if context.is_active():
                yield pb2.Event(node_id=self.node_id, seq=i, type="heartbeat")
                time.sleep(2)
            else:
                break


class RPCServer:
    """Manages gRPC server lifecycle and peer connections."""

    def __init__(self, node_id: str, peers: list[str], port: int = None):
        self.node_id = node_id
        self.peers = peers
        self.port = port or (50000 + hash(node_id) % 1000)
        self._server = None
        self._thread = None
        self._servicer = NodeRPCServicer(node_id, peers)

    def start(self):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        pb2_grpc.add_NodeRPCServicer_to_server(self._servicer, self._server)
        self._server.add_insecure_port(f"[::]:{self.port}")
        self._server.start()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()
        print(f"[RPC] {self.node_id} listening on :{self.port}")

    def set_app(self, app):
        self._servicer.set_app(app)

    def _serve_loop(self):
        try:
            self._server.wait_for_termination()
        except Exception as e:
            print(f"[RPC] {self.node_id} server error: {e}")

    def stop(self):
        if self._server:
            self._server.stop(grace=5)
        print(f"[RPC] {self.node_id} server stopped")

    # ── Outbound calls to peers ────────────────────────────────────────────
    def call_peer(self, peer_id: str, command: str) -> str:
        """Call a peer's Forward RPC (thread-safe, pooled stub)."""
        peer_port = 50000 + hash(peer_id) % 1000
        channel = grpc.insecure_channel(f"atom-{peer_id}:{peer_port}")
        stub = pb2_grpc.NodeRPCStub(channel)
        try:
            resp = stub.Forward(pb2.ForwardRequest(command=command), timeout=3.0)
            return resp.result
        except grpc.RpcError as e:
            return f"rpc-error:{e.code().name}"
        finally:
            channel.close()

    def broadcast(self, command: str) -> dict[str, str]:
        """Broadcast command to all peers, return peer→result map."""
        results = {}
        threads = []
        lock = threading.Lock()

        def call(peer):
            r = self.call_peer(peer, command)
            with lock:
                results[peer] = r

        for peer in self.peers:
            t = threading.Thread(target=call, args=(peer,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=5.0)

        return results
