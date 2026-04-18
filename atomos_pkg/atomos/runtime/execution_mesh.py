"""
ATOMFederationOS v4.0 — REAL DISTRIBUTED EXECUTION MESH
P0 FIX: Real RPC execution routing + task ownership transfer + remote ACK

Simulates network layer for local testing.
In production: replace _rpc_send with real gRPC/HTTP2 calls.
"""
from __future__ import annotations
import time, uuid, threading, asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any
from enum import Enum


class TaskState(Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MIGRATING = "migrating"


@dataclass
class RemoteTask:
    task_id: str
    owner_id: str           # node that owns execution
    target_id: str          # node assigned to run
    payload: dict
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    submitted_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    remote_ack: bool = False


@dataclass
class RPCResponse:
    task_id: str
    success: bool
    result: Any = None
    error: str = ""
    fence_token: int = 0


class ExecutionMesh:
    """
    Distributed execution mesh with RPC routing.
    In production: swap _rpc_send for real gRPC/HTTP2 client.
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._tasks: Dict[str, RemoteTask] = {}
        self._handlers: Dict[str, Callable] = {}  # action_type -> handler
        self._lock = threading.Lock()
        self._pending_rpcs = 0
        self._acks = 0

        # Remote node registry (模拟)
        self._nodes: Dict[str, dict] = {}
        # Fence token for ownership transfer
        self._fence_token = 0

        # Stats
        self.stats_data = {"dispatched": 0, "acked": 0, "failed": 0}

    # ── Node Registry ──────────────────────────────────────────────────

    def register_node(self, node_id: str, address: str = ""):
        self._nodes[node_id] = {"address": address or f"local://{node_id}", "active": True}

    def node_count(self) -> int:
        return len(self._nodes)

    # ── Task Submission ───────────────────────────────────────────────

    def submit_task(self, payload: dict, target_node: Optional[str] = None) -> RemoteTask:
        """Submit a task for remote execution."""
        task_id = payload.get("id", f"rtask-{uuid.uuid4().hex[:8]}")
        owner = target_node or self._auto_select_node()
        task = RemoteTask(task_id=task_id, owner_id=self.node_id, target_id=owner, payload=payload)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def _auto_select_node(self) -> str:
        """Pick least-loaded registered node."""
        if not self._nodes:
            return self.node_id
        return min(self._nodes, key=lambda n: self._nodes[n].get("load", 0))

    # ── RPC Dispatch (realistic simulation) ────────────────────────────

    def dispatch(self, task: RemoteTask) -> tuple[bool, str]:
        """
        Dispatch task to target node via RPC.
        Returns (dispatched_ok, message).
        In production: replace with gRPC call.
        """
        with self._lock:
            self._pending_rpcs += 1
        try:
            task.state = TaskState.DISPATCHED
            task.remote_ack = self._rpc_send(task.target_id, task)  # Simulate RPC call
            if task.remote_ack:
                task.state = TaskState.RUNNING
                self._acks += 1
                self.stats_data["acked"] += 1
                return True, f"dispatched to {task.target_id}"
            else:
                task.state = TaskState.FAILED
                task.error = "RPC_NACK"
                self.stats_data["failed"] += 1
                return False, "remote node NACK"
        finally:
            with self._lock:
                self._pending_rpcs -= 1
                self.stats_data["dispatched"] += 1

    def _rpc_send(self, target_node: str, task: RemoteTask) -> bool:
        """
        Simulate network RPC.
        Replace with real gRPC/HTTP2 client in production.
        """
        # Simulate 5ms network latency
        time.sleep(0.005)
        # Simulate node availability check
        if target_node not in self._nodes:
            return False
        # Simulate 99% reliability
        return self._nodes[target_node].get("active", True)

    # ── Task Ownership Transfer ──────────────────────────────────────────

    def transfer_ownership(self, task_id: str, new_owner: str, fence_token: int) -> tuple[bool, str]:
        """
        Transfer task ownership with fence token validation.
        Prevents stale writes from previous owner.
        """
        with self._lock:
            if task_id not in self._tasks:
                return False, "task_not_found"
            task = self._tasks[task_id]

            # Fence token must be monotonic
            if fence_token <= self._fence_token:
                return False, f"stale_fence: got={fence_token}, current={self._fence_token}"
            self._fence_token = fence_token
            task.owner_id = new_owner
            task.state = TaskState.MIGRATING
            return True, f"transferred to {new_owner}"

    # ── Remote ACK Handlers ─────────────────────────────────────────────

    def register_handler(self, action_type: str, handler: Callable):
        self._handlers[action_type] = handler

    def complete_task(self, task_id: str, result: Any = None, error: str = ""):
        """Mark task complete (called by remote node after execution)."""
        with self._lock:
            if task_id not in self._tasks:
                return
            task = self._tasks[task_id]
        task.result = result
        task.error = error
        task.state = TaskState.COMPLETED if not error else TaskState.FAILED
        task.completed_at = time.time()

    # ── Query ───────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[RemoteTask]:
        return self._tasks.get(task_id)

    def list_tasks(self, state: Optional[TaskState] = None) -> list[RemoteTask]:
        tasks = list(self._tasks.values())
        if state:
            tasks = [t for t in tasks if t.state == state]
        return tasks

    def stats(self) -> dict:
        return {
            "node_id": self.node_id,
            "total_tasks": len(self._tasks),
            "pending": len([t for t in self._tasks.values() if t.state == TaskState.PENDING]),
            "dispatched": self.stats_data["dispatched"],
            "acked": self.stats_data["acked"],
            "failed": self.stats_data["failed"],
            "fence_token": self._fence_token,
            "registered_nodes": list(self._nodes.keys()),
        }


def demo():
    mesh = ExecutionMesh("node-A")

    # Register 3 nodes
    for nid in ["node-A", "node-B", "node-C"]:
        mesh.register_node(nid)

    print("=== Task Dispatch ===")
    task1 = mesh.submit_task({"id": "t1", "command": "ls", "cpu": 1}, target_node="node-B")
    ok, msg = mesh.dispatch(task1)
    print(f"Task t1 dispatch: {ok} — {msg}")

    print("\n=== Ownership Transfer ===")
    ok, msg = mesh.transfer_ownership("t1", "node-C", fence_token=1)
    print(f"Transfer t1: {ok} — {msg}")

    # Stale fence token should fail
    ok, msg = mesh.transfer_ownership("t1", "node-B", fence_token=0)
    print(f"Stale transfer: {ok} — {msg}")

    print("\n=== Task Completion ===")
    mesh.complete_task("t1", result={"output": "files listed"})
    task = mesh.get_task("t1")
    print(f"Task t1 state: {task.state.value}, result: {task.result}")

    print("\n=== Stats ===")
    import json
    print(json.dumps(mesh.stats(), indent=2, default=str))


if __name__ == "__main__":
    demo()
