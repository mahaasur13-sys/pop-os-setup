"""
ATOMFederationOS v4.0 — OBSERVABILITY SYSTEM
P1 FIX: Distributed tracing + metrics aggregation + event-to-task correlation

Components:
- Distributed trace IDs (W3C TraceContext compatible)
- System-wide telemetry aggregator
- Event correlation graph
- Metrics pipeline (Prometheus-compatible)
"""
from __future__ import annotations
import time, uuid, threading, hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import defaultdict
from enum import Enum


@dataclass
class TraceID:
    """W3C TraceContext-compatible trace ID (128-bit)."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    trace_flags: str = "01"  # 01 = sampled

    @classmethod
    def new(cls, parent: Optional["TraceID"] = None) -> "TraceID":
        tid = uuid.uuid4().hex[:32]  # 128-bit
        sid = uuid.uuid4().hex[:16]  # 64-bit
        psid = parent.span_id if parent else None
        return cls(trace_id=tid, span_id=sid, parent_span_id=psid)

    def child(self) -> "TraceID":
        return TraceID.new(parent=self)

    def as_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "flags": self.trace_flags,
        }


@dataclass
class Span:
    """Distributed span (one unit of work)."""
    trace_id: str
    span_id: str
    operation: str
    start_ts: float
    end_ts: Optional[float] = None
    tags: dict = field(default_factory=dict)
    parent_span_id: Optional[str] = None
    logs: list = field(default_factory=list)
    status: str = "OK"

    def finish(self, status: str = "OK"):
        self.end_ts = time.time()
        self.status = status

    def duration_ms(self) -> float:
        if self.end_ts is None:
            return (time.time() - self.start_ts) * 1000
        return (self.end_ts - self.start_ts) * 1000


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class MetricSample:
    name: str
    value: float
    labels: dict
    timestamp: float


class ObservabilitySystem:
    """
    Full observability pipeline:
    - Distributed tracing (trace graph)
    - Metrics aggregation (Prometheus-compatible labels)
    - Event-to-task correlation
    - Log correlation via trace IDs
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._traces: Dict[str, TraceID] = {}
        self._spans: Dict[str, Span] = {}
        self._metrics: Dict[str, List[MetricSample]] = defaultdict(list)
        self._events: Dict[str, list] = defaultdict(list)  # event_type -> event list
        self._correlations: Dict[str, str] = {}  # event_idx -> task_id
        self._lock = threading.Lock()
        self._span_counter = 0

    # ── Tracing ────────────────────────────────────────────────────────

    def start_trace(self) -> TraceID:
        tid = TraceID.new()
        with self._lock:
            self._traces[tid.trace_id] = tid
        return tid

    def start_span(self, trace: TraceID, operation: str, tags: dict = None, parent_span_id: Optional[str] = None) -> Span:
        # Generate unique span_id per span (trace.span_id is the root trace id)
        span_id = uuid.uuid4().hex[:16]
        parent = parent_span_id if parent_span_id is not None else (trace.parent_span_id if hasattr(trace, 'parent_span_id') else None)
        span = Span(
            trace_id=trace.trace_id,
            span_id=span_id,
            parent_span_id=parent,
            operation=operation,
            start_ts=time.time(),
            tags=tags or {},
        )
        with self._lock:
            self._spans[span.span_id] = span
            self._span_counter += 1
        return span

    def finish_span(self, span: Span, status: str = "OK", logs: list = None):
        span.finish(status)
        if logs:
            span.logs = logs
        with self._lock:
            self._spans[span.span_id] = span

    def correlate_event_to_task(self, event_idx: int, task_id: str):
        with self._lock:
            self._correlations[str(event_idx)] = task_id

    def get_trace_spans(self, trace_id: str) -> List[Span]:
        with self._lock:
            return [s for s in self._spans.values() if s.trace_id == trace_id]

    def event_correlation(self, event_idx: int) -> Optional[str]:
        return self._correlations.get(str(event_idx))

    # ── Metrics ───────────────────────────────────────────────────────

    def record_metric(self, name: str, value: float, labels: dict = None, metric_type: MetricType = MetricType.GAUGE):
        sample = MetricSample(
            name=name,
            value=value,
            labels=labels or {},
            timestamp=time.time(),
        )
        with self._lock:
            self._metrics[name].append(sample)
            # Keep last 1000 samples per metric
            if len(self._metrics[name]) > 1000:
                self._metrics[name] = self._metrics[name][-1000:]

    def counter(self, name: str, labels: dict = None):
        self.record_metric(name, 1.0, labels, MetricType.COUNTER)

    def gauge(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, labels, MetricType.GAUGE)

    def histogram(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, labels, MetricType.HISTOGRAM)

    # ── Events ────────────────────────────────────────────────────────

    def record_event(self, event_type: str, payload: dict, trace: Optional[TraceID] = None):
        entry = {
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
            "trace_id": trace.trace_id if trace else None,
            "span_id": trace.span_id if trace else None,
        }
        with self._lock:
            self._events[event_type].append(entry)

    def get_events(self, event_type: str, limit: int = 50) -> list:
        with self._lock:
            evts = self._events.get(event_type, [])
            return evts[-limit:]

    # ── Correlation Graph ──────────────────────────────────────────────

    def build_trace_graph(self, trace_id: str) -> dict:
        """Build execution graph from spans for a given trace."""
        spans = self.get_trace_spans(trace_id)
        nodes = []
        edges = []
        for s in spans:
            nodes.append({"id": s.span_id, "op": s.operation, "dur_ms": s.duration_ms()})
            if s.parent_span_id:
                edges.append({"from": s.parent_span_id, "to": s.span_id})
        return {"trace_id": trace_id, "nodes": nodes, "edges": edges}

    # ── Prometheus Export ───────────────────────────────────────────────

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format."""
        lines = []
        with self._lock:
            for name, samples in self._metrics.items():
                if not samples:
                    continue
                latest = samples[-1]
                labels_str = ",".join(f'{k}="{v}"' for k, v in latest.labels.items())
                suffix = f"{{{labels_str}}}" if labels_str else ""
                lines.append(f"{name}{suffix} {latest.value} {int(latest.timestamp * 1000)}")
        return "\n".join(lines)

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {
                "node_id": self.node_id,
                "active_traces": len(self._traces),
                "total_spans": self._span_counter,
                "metrics": {name: len(samples) for name, samples in self._metrics.items()},
                "event_types": list(self._events.keys()),
                "correlations": len(self._correlations),
            }


def demo():
    obs = ObservabilitySystem("node-A")

    print("=== Distributed Tracing ===")
    trace = obs.start_trace()
    print(f"TraceID: {trace.trace_id[:16]}...")

    span1 = obs.start_span(trace, "task_submission", {"priority": "high"})
    time.sleep(0.01)
    span2 = obs.start_span(trace.child(), "task_execution", {"cpu": "1"})
    time.sleep(0.02)
    obs.finish_span(span1)
    obs.finish_span(span2)

    print(f"Spans in trace: {len(obs.get_trace_spans(trace.trace_id))}")
    print(f"Trace graph: {obs.build_trace_graph(trace.trace_id)}")

    print("\n=== Metrics ===")
    obs.counter("tasks_submitted", {"node": "A"})
    obs.gauge("cpu_usage_percent", 72.5, {"node": "A"})
    obs.histogram("task_duration_ms", 45.2, {"priority": "high"})
    print(obs.export_prometheus())

    print("\n=== Event Correlation ===")
    obs.correlate_event_to_task(0, "task-t1")
    obs.correlate_event_to_task(1, "task-t2")
    print(f"Event 0 → Task: {obs.event_correlation(0)}")
    print(f"Event 1 → Task: {obs.event_correlation(1)}")

    print("\n=== Stats ===")
    import json
    print(json.dumps(obs.stats(), indent=2, default=str))


if __name__ == "__main__":
    demo()
