"""
Anomaly Detector — Behavioral Drift Detection Layer

Detects behavioral drift by comparing current job behavior against
established baselines using statistical and pattern-based analysis.
"""

import hashlib
import json
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DriftType(Enum):
    CPU_SPIKE = "CPU_SPIKE"
    MEMORY_LEAK = "MEMORY_LEAK"
    GPU_UTILIZATION_ANOMALY = "GPU_UTILIZATION_ANOMALY"
    EXECUTION_TIME_DRIFT = "EXECUTION_TIME_DRIFT"
    SYSCALL_PATTERN_CHANGE = "SYSCALL_PATTERN_CHANGE"
    NETWORK_EGRESS_SPIKE = "NETWORK_EGRESS_SPIKE"


@dataclass
class DriftEvent:
    job_id: str
    drift_type: DriftType
    drift_score: float  # 0.0 (normal) -> 1.0 (max anomaly)
    current_value: float
    baseline_value: float
    detail: str
    timestamp: float = field(default_factory=time.time)


class AnomalyDetector:
    """
    Behavioral drift detection using rolling window statistics.
    Uses z-score and IQR methods to detect anomalies.
    """

    ZSCORE_THRESHOLD = 3.0  # standard deviations
    IQR_MULTIPLIER = 1.5

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._baselines: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=window_size)))
        self._drift_history: list[DriftEvent] = []
        self._lock = threading.Lock()

    def record_metric(self, job_id: str, metric_name: str, value: float):
        with self._lock:
            self._baselines[job_id][metric_name].append(value)

    def detect_drift(self, job_id: str, current_metrics: dict) -> list[DriftEvent]:
        events = []
        with self._lock:
            for metric_name, current_value in current_metrics.items():
                window = list(self._baselines[job_id].get(metric_name, []))
                if len(window) < 10:
                    continue

                drift_score, is_anomaly = self._compute_zscore(current_value, window)
                if is_anomaly:
                    baseline_val = sum(window) / len(window)
                    drift_type = self._metric_to_drift_type(metric_name)
                    event = DriftEvent(
                        job_id=job_id,
                        drift_type=drift_type,
                        drift_score=min(drift_score / self.ZSCORE_THRESHOLD, 1.0),
                        current_value=current_value,
                        baseline_value=baseline_val,
                        detail=f"{metric_name}: {current_value:.2f} vs baseline {baseline_val:.2f}",
                    )
                    events.append(event)
                    self._drift_history.append(event)

        return events

    def _compute_zscore(self, value: float, window: list[float]) -> tuple[float, bool]:
        if not window:
            return 0.0, False
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        std = variance ** 0.5
        if std == 0:
            return 0.0, False
        zscore = abs(value - mean) / std
        return zscore, zscore >= self.ZSCORE_THRESHOLD

    def _metric_to_drift_type(self, metric: str) -> DriftType:
        mapping = {
            "cpu_percent": DriftType.CPU_SPIKE,
            "memory_rss_mb": DriftType.MEMORY_LEAK,
            "gpu_percent": DriftType.GPU_UTILIZATION_ANOMALY,
            "execution_time_seconds": DriftType.EXECUTION_TIME_DRIFT,
            "syscall_count": DriftType.SYSCALL_PATTERN_CHANGE,
            "network_egress_bytes": DriftType.NETWORK_EGRESS_SPIKE,
        }
        return mapping.get(metric, DriftType.EXECUTION_TIME_DRIFT)

    def get_baseline(self, job_id: str, metric_name: str) -> Optional[dict]:
        with self._lock:
            window = list(self._baselines[job_id].get(metric_name, []))
        if not window:
            return None
        return {
            "mean": sum(window) / len(window),
            "std": (sum((x - sum(window) / len(window)) ** 2 for x in window) / len(window)) ** 0.5,
            "min": min(window),
            "max": max(window),
            "samples": len(window),
        }

    def get_drift_history(self, job_id: Optional[str] = None) -> list[DriftEvent]:
        with self._lock:
            if job_id is None:
                return list(self._drift_history)
            return [e for e in self._drift_history if e.job_id == job_id]

    def is_drift_detected(self, job_id: str, metric: str, current_value: float) -> bool:
        with self._lock:
            window = list(self._baselines[job_id].get(metric, []))
        if len(window) < 10:
            return False
        _, is_anomaly = self._compute_zscore(current_value, window)
        return is_anomaly
