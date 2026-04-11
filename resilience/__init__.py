"""
Resilience Layer v6.4 — Closed-Loop Resilience Engine

Architecture:
    reactor.py      — Event-driven reaction engine (SBS violations → runtime actions)
    healer.py       — Self-healing control plane (evict / rejoin / re-elect)
    adaptive_router.py — DRL++ (loss-aware, latency-aware routing)
    metrics_engine.py  — Stability metrics (score / RTO / convergence)
    closed_loop.py     — Integrates all into single controller
    policy_engine.py   — Maps events → action policies

Namespace: resilience.*
"""
from resilience.reactor import ResilienceReactor, ReactionTrigger, ReactionAction
from resilience.healer import SelfHealingControlPlane, HealingAction
from resilience.adaptive_router import AdaptiveRouter, RouteMetrics
from resilience.metrics_engine import StabilityMetricsEngine, StabilitySnapshot
from resilience.closed_loop import ClosedLoopResilienceController
from resilience.policy_engine import PolicyEngine, PolicyRule, PolicyAction

__all__ = [
    # reactor
    "ResilienceReactor",
    "ReactionTrigger",
    "ReactionAction",
    # healer
    "SelfHealingControlPlane",
    "HealingAction",
    # adaptive_router
    "AdaptiveRouter",
    "RouteMetrics",
    # metrics_engine
    "StabilityMetricsEngine",
    "StabilitySnapshot",
    # closed_loop
    "ClosedLoopResilienceController",
    # policy_engine
    "PolicyEngine",
    "PolicyRule",
    "PolicyAction",
]
