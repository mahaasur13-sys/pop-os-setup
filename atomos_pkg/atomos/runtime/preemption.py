"""
ATOM OS v14.2 — Preemption Engine
Priority-based task migration with checkpoint preservation.
"""
from __future__ import annotations
from typing import Optional

class PreemptionEngine:
    """Preempt low-priority tasks for urgent high-priority ones."""

    def __init__(self):
        self._tasks = []
        self._current: Optional[str] = None
        self._checkpoints = {}

    def submit_task(self, task: dict):
        self._tasks.append(task)
        if self._current is None:
            self._current = task['id']
        elif task['priority'] > self._get_priority(self._current):
            self.try_preempt()

    def try_preempt(self) -> bool:
        if not self._tasks:
            return False
        urgent = max(self._tasks, key=lambda t: t.get('priority', 0))
        if self._current and urgent['priority'] > self._get_priority(self._current):
            self._current = urgent['id']
            return True
        elif not self._current:
            self._current = urgent['id']
            return True
        return False

    def _get_priority(self, task_id: str) -> int:
        for t in self._tasks:
            if t['id'] == task_id:
                return t.get('priority', 0)
        return 0

if __name__ == "__main__":
    pe = PreemptionEngine()
    pe.submit_task({'id': 'long', 'priority': 1, 'cpu': 4, 'checkpoint': 'sA', 'deadline': None})
    pe.submit_task({'id': 'urgent', 'priority': 5, 'cpu': 2, 'checkpoint': 'sB', 'deadline': None})
    r = pe.try_preempt()
    print(f"Preempted: {r}, current: {pe._current}")
