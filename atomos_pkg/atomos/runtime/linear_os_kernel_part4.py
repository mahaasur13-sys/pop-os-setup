"""
ATOMFederationOS v4.1 — PART 4: Backpressure + CausalTrace + IntegratedKernel + Tests
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
import threading, hashlib, time


class ThrottleLevel(Enum):
    NONE = "none"; LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"


@dataclass
class BackpressureConfig:
    queue_depth_threshold: int = 100
    cpu_threshold_pct: float = 80.0
    memory_threshold_gb: float = 28.0


class AdmissionThrottler:
    def __init__(self, config: BackpressureConfig):
        self.config = config
        self._lock = threading.Lock()
        self._current_level = ThrottleLevel.NONE
        self._rejected_count = 0; self._accepted_count = 0
        self._last_throttle_change = 0.0

    def evaluate_task(self, task: dict) -> tuple[bool, ThrottleLevel, str]:
        with self._lock:
            level = self._current_level
            min_p = {ThrottleLevel.NONE: 0, ThrottleLevel.LOW: 3,
                     ThrottleLevel.MEDIUM: 5, ThrottleLevel.HIGH: 7,
                     ThrottleLevel.CRITICAL: 10}[level]
            if task.get("priority", 0) < min_p:
                self._rejected_count += 1
                return False, level, f"priority {task.get('priority')} < {min_p}"
            self._accepted_count += 1
            return True, level, "admitted"

    def update_system_load(self, queue_depth: int, cpu_pct: float, memory_gb: float) -> ThrottleLevel:
        with self._lock:
            prev = self._current_level
            if queue_depth > self.config.queue_depth_threshold * 2:
                self._current_level = ThrottleLevel.CRITICAL
            elif queue_depth > self.config.queue_depth_threshold:
                self._current_level = ThrottleLevel.HIGH
            elif cpu_pct > self.config.cpu_threshold_pct * 1.2:
                self._current_level = ThrottleLevel.MEDIUM
            elif cpu_pct > self.config.cpu_threshold_pct:
                self._current_level = ThrottleLevel.LOW
            else:
                self._current_level = ThrottleLevel.NONE
            if prev != self._current_level: self._last_throttle_change = time.time()
            return self._current_level

    def get_current_level(self) -> ThrottleLevel: return self._current_level

    def admission_rate(self) -> float:
        total = self._accepted_count + self._rejected_count
        return self._accepted_count / total if total > 0 else 1.0

    def stats(self) -> dict:
        return {"level": self._current_level.value,
                "accepted": self._accepted_count, "rejected": self._rejected_count,
                "admission_rate": self.admission_rate()}


# ── F8: CausalTraceSystem ────────────────────────────────────────────────
@dataclass
class CausalSpan:
    span_id: str; trace_id: str; parent_span_id: Optional[str]
    operation: str; started_at: float; finished_at: Optional[float] = None
    consensus_term: Optional[int] = None; commit_index: Optional[int] = None
    causality_id: Optional[str] = None; tags: dict = field(default_factory=dict)
    def duration_ms(self) -> Optional[float]:
        return (self.finished_at - self.started_at) * 1000 if self.finished_at else None


class CausalTraceSystem:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._traces: Dict[str, List[CausalSpan]] = {}
        self._spans: Dict[str, CausalSpan] = {}
        self._event_to_task: Dict[int, str] = {}
        self._lock = threading.Lock(); self._counter = 0

    def start_trace(self) -> str:
        tid = f"trace-{self.node_id}-{self._counter}"; self._counter += 1; return tid

    def start_span(self, trace_id: str, operation: str, parent_span_id: Optional[str] = None,
                  causality_id: Optional[str] = None,
                  consensus_term: Optional[int] = None,
                  commit_index: Optional[int] = None) -> str:
        sid = f"span-{self._counter}"; self._counter += 1
        span = CausalSpan(span_id=sid, trace_id=trace_id, parent_span_id=parent_span_id,
            operation=operation, started_at=time.time(), causality_id=causality_id,
            consensus_term=consensus_term, commit_index=commit_index)
        with self._lock:
            if trace_id not in self._traces: self._traces[trace_id] = []
            self._traces[trace_id].append(span); self._spans[sid] = span
        return sid

    def finish_span(self, span_id: str):
        with self._lock:
            if span_id in self._spans: self._spans[span_id].finished_at = time.time()

    def correlate_event_to_task(self, event_index: int, task_id: str):
        self._event_to_task[event_index] = task_id

    def event_correlation(self, event_index: int) -> Optional[str]:
        return self._event_to_task.get(event_index)

    def build_trace_graph(self, trace_id: str) -> dict:
        with self._lock:
            spans = self._traces.get(trace_id, [])
            nodes = []; edges = []
            for s in spans:
                nodes.append({"id": s.span_id, "op": s.operation,
                             "dur_ms": s.duration_ms(),
                             "term": s.consensus_term, "cindex": s.commit_index})
                if s.parent_span_id: edges.append({"from": s.parent_span_id, "to": s.span_id})
            return {"nodes": nodes, "edges": edges}

    def export_prometheus(self) -> dict:
        with self._lock:
            spans = list(self._spans.values())
            return {"traces_total": len(self._traces), "spans_total": len(spans),
                    "spans_finished": len([s for s in spans if s.finished_at]),
                    "correlations": len(self._event_to_task)}
