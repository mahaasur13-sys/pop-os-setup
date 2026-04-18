"""
ATOM OS v14.2 - Scheduler
Priority-based with fairness index (Jain).
"""
from __future__ import annotations
import heapq, random
from dataclasses import dataclass
from typing import List

@dataclass(order=False)
class QueuedTask:
    priority: int
    cpu: float
    ram: float
    gpu: float
    id: str
    deadline: float = 0.0
    submitted_at: float = 0.0
    def __lt__(self, other):
        return self.priority < other.priority

class Scheduler:
    def __init__(self):
        self._queue: List[QueuedTask] = []
        self._running = []
        self._total_cpu = 0.0
        self._total_ram = 0.0
        self._total_gpu = 0.0

    def submit(self, task: dict) -> bool:
        if self._total_cpu + task.get('cpu', 0) > 8.0:
            return False
        if self._total_ram + task.get('ram', 0) > 32.0:
            return False
        qt = QueuedTask(
            priority=task.get('priority', 3),
            cpu=task.get('cpu', 1.0),
            ram=task.get('ram', 10.0),
            gpu=task.get('gpu', 0.0),
            id=task.get('id', 'task'),
            deadline=task.get('deadline', 0.0),
            submitted_at=0.0,
        )
        heapq.heappush(self._queue, qt)
        self._total_cpu += qt.cpu
        self._total_ram += qt.ram
        self._total_gpu += qt.gpu
        return True

    def fairness_index(self) -> float:
        if not self._queue:
            return 1.0
        n = len(self._queue)
        if n < 2:
            return 1.0
        shares = [min(1.0, t.cpu / 2.0) for t in self._queue]
        s = sum(shares)
        if s == 0:
            return 1.0
        return (s * s) / (n * sum(x*x for x in shares))

if __name__ == "__main__":
    s = Scheduler()
    for i in range(20):
        s.submit({'id': f't{i}', 'priority': random.randint(1, 5), 'cpu': 1, 'ram': 10, 'gpu': 0, 'deadline': None})
    fi = s.fairness_index()
    print(f"Jain fairness: {fi:.3f}")
