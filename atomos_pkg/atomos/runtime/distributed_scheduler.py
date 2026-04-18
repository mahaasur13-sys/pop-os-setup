"""
ATOMFederationOS v4.0 — DISTRIBUTED SCHEDULER
P2 FIX: Global resource view + node-aware placement + migration cost estimation
"""
from __future__ import annotations
import heapq, random, time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict


@dataclass
class QueuedTask:
    priority: int
    cpu: float
    ram: float
    gpu: float
    id: str
    preferred_node: Optional[str] = None
    deadline: float = 0.0
    submitted_at: float = 0.0
    migrations: int = 0

    def __lt__(self, other):
        return self.priority < other.priority


@dataclass
class NodeResources:
    node_id: str
    cpu_total: float
    ram_total: float
    gpu_total: float = 0.0
    cpu_used: float = 0.0
    ram_used: float = 0.0
    gpu_used: float = 0.0
    tasks: List[str] = field(default_factory=list)
    load: float = 0.0

    def cpu_free(self) -> float:
        return max(0.0, self.cpu_total - self.cpu_used)

    def ram_free(self) -> float:
        return max(0.0, self.ram_total - self.ram_used)

    def gpu_free(self) -> float:
        return max(0.0, self.gpu_total - self.gpu_used)

    def load_pct(self) -> float:
        denom = self.cpu_total or 1.0
        return (self.cpu_used / denom) * 100.0


class DistributedScheduler:
    def __init__(self, default_node_resources: Optional[Dict[str, dict]] = None):
        self._queue: List[QueuedTask] = []
        self._running: List[str] = []
        self._nodes: Dict[str, NodeResources] = {}
        self._task_location: Dict[str, str] = {}
        self._migration_costs: Dict[str, float] = {}
        self._total_cpu = 0.0
        self._total_ram = 0.0
        self._total_gpu = 0.0
        default_node_resources = default_node_resources or {
            "node-A": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
            "node-B": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
            "node-C": {"cpu": 4.0, "ram": 16.0, "gpu": 0.0},
        }
        for nid, res in default_node_resources.items():
            self.register_node(nid, res["cpu"], res["ram"], res["gpu"])

    def register_node(self, node_id: str, cpu: float, ram: float, gpu: float = 0.0):
        self._nodes[node_id] = NodeResources(node_id=node_id, cpu_total=cpu, ram_total=ram, gpu_total=gpu)

    def update_node_resources(self, node_id: str, cpu_used: float, ram_used: float, gpu_used: float = 0.0):
        if node_id in self._nodes:
            nr = self._nodes[node_id]
            nr.cpu_used = cpu_used
            nr.ram_used = ram_used
            nr.gpu_used = gpu_used
            nr.load = nr.load_pct()

    def submit(self, task: dict) -> bool:
        cpu = task.get("cpu", 1.0)
        ram = task.get("ram", 10.0)
        gpu = task.get("gpu", 0.0)
        total_cpu_free = sum(n.cpu_free() for n in self._nodes.values())
        total_ram_free = sum(n.ram_free() for n in self._nodes.values())
        if total_cpu_free < cpu or total_ram_free < ram:
            return False
        qt = QueuedTask(
            priority=task.get("priority", 3),
            cpu=cpu, ram=ram, gpu=gpu,
            id=task.get("id", f"task-{time.time_ns()}"),
            preferred_node=task.get("preferred_node"),
            deadline=task.get("deadline", 0.0),
            submitted_at=time.time(),
        )
        heapq.heappush(self._queue, qt)
        self._total_cpu += cpu
        self._total_ram += ram
        self._total_gpu += gpu
        return True

    def _best_node(self, task: QueuedTask) -> Optional[str]:
        if task.preferred_node and task.preferred_node in self._nodes:
            preferred = self._nodes[task.preferred_node]
            if preferred.cpu_free() >= task.cpu and preferred.ram_free() >= task.ram:
                return task.preferred_node
        scored = []
        for nid, nr in self._nodes.items():
            if nr.cpu_free() < task.cpu or nr.ram_free() < task.ram:
                continue
            if task.gpu > 0 and nr.gpu_free() < task.gpu:
                continue
            scored.append((nr.load, nid))
        if not scored:
            return None
        scored.sort()
        return scored[0][1]

    def _migration_cost(self, task: QueuedTask, from_node: str, to_node: str) -> float:
        base = task.cpu * 0.5 + task.ram * 0.1
        if from_node != to_node:
            base *= 1.5
        return base

    def dispatch_next(self) -> Optional[tuple[str, str]]:
        while self._queue:
            task = heapq.heappop(self._queue)
            node_id = self._best_node(task)
            if node_id is None:
                continue
            if task.id in self._task_location:
                prev_node = self._task_location[task.id]
                cost = self._migration_cost(task, prev_node, node_id)
                self._migration_costs[task.id] = cost
                task.migrations += 1
            nr = self._nodes[node_id]
            nr.cpu_used += task.cpu
            nr.ram_used += task.ram
            nr.gpu_used += task.gpu
            nr.tasks.append(task.id)
            nr.load = nr.load_pct()
            self._task_location[task.id] = node_id
            self._running.append(task.id)
            self._total_cpu -= task.cpu
            self._total_ram -= task.ram
            self._total_gpu -= task.gpu
            return task.id, node_id
        return None

    def dispatch_all(self) -> List[tuple[str, str]]:
        results = []
        while True:
            r = self.dispatch_next()
            if r is None:
                break
            results.append(r)
        return results

    def complete_task(self, task_id: str):
        node_id = self._task_location.get(task_id)
        if node_id and node_id in self._nodes:
            nr = self._nodes[node_id]
            if task_id in nr.tasks:
                nr.tasks.remove(task_id)
        if task_id in self._running:
            self._running.remove(task_id)
        self._task_location.pop(task_id, None)

    def cluster_jain_fairness(self) -> float:
        if not self._nodes:
            return 1.0
        shares = []
        total_tasks = len(self._running) + len(self._queue)
        for nr in self._nodes.values():
            fair_share = len(nr.tasks) / max(total_tasks, 1)
            shares.append(min(1.0, fair_share * len(self._nodes)))
        n = len(shares)
        if n < 2:
            return 1.0
        s = sum(shares)
        if s == 0:
            return 1.0
        return (s * s) / (n * sum(x*x for x in shares if x > 0))

    def node_loads(self) -> Dict[str, dict]:
        return {
            nid: {"load_pct": nr.load_pct(), "cpu_free": nr.cpu_free(),
                  "ram_free": nr.ram_free(), "tasks": len(nr.tasks)}
            for nid, nr in self._nodes.items()
        }

    def fairness_index(self) -> float:
        return self.cluster_jain_fairness()

    def stats(self) -> dict:
        total_tasks = len(self._running) + len(self._queue)
        return {
            "queue_depth": len(self._queue),
            "running": len(self._running),
            "total_tasks": total_tasks,
            "jain_fairness": round(self.cluster_jain_fairness(), 3),
            "total_migrations": sum(t.migrations for t in self._queue),
            "node_loads": self.node_loads(),
        }


if __name__ == "__main__":
    ds = DistributedScheduler()
    for i in range(20):
        ds.submit({"id": f"t{i}", "priority": (i % 5) + 1, "cpu": 1, "ram": 10, "gpu": 0})
    dispatched = ds.dispatch_all()
    fairness = ds.cluster_jain_fairness()
    loads = ds.node_loads()
    print(f"Dispatched: {len(dispatched)}/20")
    print(f"Jain fairness: {fairness:.3f}")
    print(f"Nodes: {len(loads)}")
    print("OK")
