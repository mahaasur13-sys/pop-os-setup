"""ATOMCluster reconciliation loop — enforces SBS invariants, drift limits, quorum."""

from __future__ import annotations

import logging
import time
from typing import Optional

from .client import K8sClient
from .state import ClusterState, NodeState

logger = logging.getLogger("atom.operator.reconciler")


class Reconciler:
    """One reconciler per ATOMCluster name — thread-safe."""

    def __init__(self, k8s: K8sClient):
        self.k8s = k8s
        self._last_reconcile: dict[str, float] = {}
        self._heal_cooldown: dict[str, float] = {}
        self._heal_cooldown_seconds: float = 30.0
        self._scale_cooldown_seconds: float = 60.0
        self._last_scale: dict[str, float] = {}

    def reconcile(self, cluster: dict) -> ClusterState:
        state = ClusterState.from_k8s(cluster)
        name = state.name
        ns = state.namespace
        spec = cluster.get("spec", {})

        if state.phase in ("Pending", ""):
            return self._bootstrap(state, spec, ns)

        live = self._poll_metrics(state)

        if live.sbs_violation_rate > state.sbs_threshold:
            if self._can_heal(name):
                logger.warning(
                    "[%s] SBS violation %.4f > %s — triggering heal",
                    name, live.sbs_violation_rate, state.sbs_threshold,
                )
                self._heal_cluster(name, ns, live)
                self._record_heal(name)
                live.phase = "Healing"

        if live.coherence_drift > state.coherence_drift_max:
            if state.phase != "Healing":
                logger.warning(
                    "[%s] Drift %.4f > %s — throttling",
                    name, live.coherence_drift, state.coherence_drift_max,
                )
                self._throttle_cluster(name, ns)
                live.phase = "Degraded"

        if live.is_quorum_breached:
            logger.error("[%s] Quorum BREACHED — %d/%d ready",
                        name, live.ready_replicas, state.replicas)
            live.phase = "Failed"
        else:
            live.quorum_safe = True
            if live.phase == "Failed":
                live.phase = "Running"

        if state.replicas > 0 and self._can_scale(name):
            health_ratio = live.health_ratio
            if health_ratio < 0.99 and live.ready_replicas < state.replicas:
                self._scale_up(name, ns, state, live)
                self._record_scale(name)
            elif health_ratio >= 0.99 and live.ready_replicas == state.replicas:
                live.phase = "Running"

        self._ensure_mesh_service(name, ns)

        status = live.to_k8s_status()
        if live.phase not in ("Pending", "Initializing"):
            status = self._enrich_conditions(live, status)
        self.k8s.patch_status(name, ns, status)

        self._last_reconcile[name] = time.time()
        logger.info(
            "[%s] reconcile done -> phase=%s ready=%d/%d sbs=%.4f drift=%.4f",
            name, live.phase, live.ready_replicas, state.replicas,
            live.sbs_violation_rate, live.coherence_drift,
        )
        return live

    def _bootstrap(
        self, state: ClusterState, spec: dict, ns: str
    ) -> ClusterState:
        state.phase = "Initializing"
        logger.info("[%s] Bootstrapping ATOMCluster", state.name)
        self._ensure_statefulset(state, spec, ns)
        self._ensure_service_account(state.name, ns)
        self._ensure_mesh_service(state.name, ns)
        state.phase = "Running"
        self.k8s.patch_status(state.name, ns, state.to_k8s_status())
        return state

    def _poll_metrics(self, state: ClusterState) -> ClusterState:
        """Pull live metrics from Prometheus or fall back to StatefulSet status."""
        live = ClusterState(
            name=state.name,
            namespace=state.namespace,
            replicas=state.replicas,
            sbs_threshold=state.sbs_threshold,
            coherence_drift_max=state.coherence_drift_max,
            phase=state.phase,
            ready_replicas=state.ready_replicas,
            current_version=state.current_version,
            nodes=state.nodes,
            conditions=state.conditions,
        )

        metrics = self._query_prometheus(state.name)
        if metrics:
            live.sbs_violation_rate = metrics.get("sbs_violation_rate", 0.0)
            live.coherence_drift = metrics.get("coherence_drift", 0.0)
            live.ready_replicas = metrics.get("ready_replicas", live.ready_replicas)
            live.nodes = [
                NodeState(
                    node_id=n.get("node_id", i),
                    status=n.get("status", "Running"),
                    sbs_violation_rate=float(n.get("sbs_violation_rate", 0.0)),
                    coherence_drift=float(n.get("coherence_drift", 0.0)),
                )
                for i, n in enumerate(metrics.get("nodes", []))
            ]
            return live

        sts = self.k8s.read_statefulset(f"atom-node-{state.name}", state.namespace)
        if sts:
            live.ready_replicas = sts.status.ready_replicas or 0

        return live

    def _query_prometheus(self, cluster: str) -> Optional[dict]:
        """Query Prometheus HTTP API. Returns None if unavailable."""
        import json
        import urllib.request

        prom_url = "http://prometheus-service:9090/api/v1/query"
        queries = {
            "sbs_violation_rate": (
                "avg(atom_sbs_violations_total{cluster=\"%s\"}) / "
                "avg(atom_sbs_checks_total{cluster=\"%s\"})"
            ) % (cluster, cluster),
            "coherence_drift": (
                "avg(atom_coherence_drift_score{cluster=\"%s\"})" % cluster
            ),
            "ready_replicas": (
                "count(atom_node_up{cluster=\"%s\"} == 1)" % cluster
            ),
        }

        result = {}
        try:
            for key, query in queries.items():
                url = "%s?query=%s" % (prom_url, urllib.request.quote(query))
                with urllib.request.urlopen(url, timeout=2) as resp:
                    data = json.loads(resp.read())
                val = data.get("data", {}).get("result", [])
                result[key] = float(val[0][1]) if val else 0.0
            return result
        except Exception:
            return None

    def _ensure_statefulset(
        self, state: ClusterState, spec: dict, ns: str
    ) -> None:
        name = f"atom-node-{state.name}"
        existing = self.k8s.read_statefulset(name, ns)

        image = spec.get("image", "ghcr.io/atom-federation/atom-os:latest")
        resources = spec.get("resources", {})
        replicas = spec.get("replicas", state.replicas)

        sts_manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": name,
                "namespace": ns,
                "labels": {
                    "app.kubernetes.io/name": "atom-node",
                    "app.kubernetes.io/instance": state.name,
                    "app.kubernetes.io/version": "7.0",
                    "atom.io/cluster": state.name,
                },
            },
            "spec": {
                "serviceName": f"atom-mesh-{state.name}",
                "replicas": replicas,
                "selector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "atom-node",
                        "atom.io/cluster": state.name,
                    }
                },
                "updateStrategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxUnavailable": 1},
                },
                "podManagementPolicy": "Parallel",
                "template": {
                    "metadata": {
                        "labels": {
                            "app.kubernetes.io/name": "atom-node",
                            "app.kubernetes.io/instance": state.name,
                            "atom.io/cluster": state.name,
                        }
                    },
                    "spec": {
                        "serviceAccountName": f"atom-operator-{state.name}",
                        "containers": [
                            {
                                "name": "atom",
                                "image": image,
                                "ports": [
                                    {"name": "grpc", "containerPort": 50051},
                                    {"name": "metrics", "containerPort": 9464},
                                    {"name": "health", "containerPort": 8080},
                                ],
                                "env": [
                                    {
                                        "name": "ATOM_NODE_ID",
                                        "valueFrom": {
                                            "fieldRef": {
                                                "fieldPath": "metadata.labels['atom.io/node-id']"
                                            }
                                        },
                                    },
                                    {
                                        "name": "ATOM_CLUSTER",
                                        "value": state.name,
                                    },
                                    {
                                        "name": "ATOM_NAMESPACE",
                                        "value": ns,
                                    },
                                ],
                                "resources": resources,
                                "livenessProbe": {
                                    "httpGet": {"path": "/healthz", "port": 8080},
                                    "initialDelaySeconds": 10,
                                    "periodSeconds": 10,
                                },
                                "readinessProbe": {
                                    "httpGet": {"path": "/readyz", "port": 8080},
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 5,
                                },
                            }
                        ],
                    },
                },
            },
        }

        if existing is None:
            logger.info("[%s] Creating StatefulSet %s", state.name, name)
            self.k8s.create_statefulset(sts_manifest)
        else:
            logger.info("[%s] StatefulSet %s already exists", state.name, name)

    def _ensure_service_account(self, name: str, ns: str) -> None:
        sa_name = f"atom-operator-{name}"
        try:
            self.k8s.core.read_namespaced_service_account(sa_name, ns)
        except Exception:
            sa = {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {
                    "name": sa_name,
                    "namespace": ns,
                    "labels": {
                        "app.kubernetes.io/name": "atom-operator",
                        "atom.io/cluster": name,
                    },
                },
            }
            self.k8s.create_service_account(sa)

    def _ensure_mesh_service(self, name: str, ns: str) -> None:
        svc_name = f"atom-mesh-{name}"
        existing = self.k8s.get_service(svc_name, ns)

        svc_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": svc_name,
                "namespace": ns,
                "labels": {
                    "app.kubernetes.io/name": "atom-mesh",
                    "atom.io/cluster": name,
                },
            },
            "spec": {
                "type": "ClusterIP",
                "clusterIP": "None",
                "selector": {
                    "app.kubernetes.io/name": "atom-node",
                    "atom.io/cluster": name,
                },
                "ports": [
                    {"name": "grpc", "port": 50051, "targetPort": 50051},
                    {"name": "metrics", "port": 9464, "targetPort": 9464},
                ],
            },
        }

        if existing is None:
            logger.info("[%s] Creating headless service %s", name, svc_name)
            self.k8s.create_service(svc_manifest)
        else:
            logger.info("[%s] Service %s already exists", name, svc_name)

    def _heal_cluster(
        self, name: str, ns: str, live: ClusterState
    ) -> None:
        """Delete unhealthy pods and force-roll the StatefulSet."""
        sts_name = f"atom-node-{name}"

        worst: Optional[NodeState] = None
        for n in live.nodes:
            if n.sbs_violation_rate > live.sbs_violation_rate * 0.8:
                if worst is None or n.sbs_violation_rate > worst.sbs_violation_rate:
                    worst = n

        if worst:
            pod_name = "%s-%s" % (sts_name, worst.node_id)
            logger.info("[%s] Deleting unhealthy pod %s", name, pod_name)
            try:
                self.k8s.core.delete_namespaced_pod(
                    pod_name, ns, grace_period_seconds=30,
                )
            except Exception as e:
                logger.warning("[%s] Failed to delete pod %s: %s", name, pod_name, e)

        try:
            self.k8s.patch_statefulset(
                sts_name, ns,
                {
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "atom.io/restartedAt": str(time.time()),
                                }
                            }
                        }
                    }
                },
            )
        except Exception as e:
            logger.warning("[%s] Failed to patch StatefulSet: %s", name, e)

    def _throttle_cluster(self, name: str, ns: str) -> None:
        """Reduce admission rate to let coherence recover."""
        logger.info("[%s] Throttling — reducing admission rate", name)
        try:
            self.k8s.patch_cluster(
                name, ns,
                {
                    "spec": {
                        "annotations": {
                            "atom.io/throttle": "true",
                            "atom.io/throttleAt": str(time.time()),
                        }
                    }
                },
            )
        except Exception:
            pass

    def _scale_up(
        self, name: str, ns: str, state: ClusterState, live: ClusterState
    ) -> None:
        target = state.replicas
        logger.info("[%s] Scaling up %d -> %d", name, live.ready_replicas, target)
        sts_name = f"atom-node-{name}"
        self.k8s.patch_statefulset(sts_name, ns, {"spec": {"replicas": target}})

    def _can_heal(self, name: str) -> bool:
        last = self._heal_cooldown.get(name, 0.0)
        return (time.time() - last) > self._heal_cooldown_seconds

    def _can_scale(self, name: str) -> bool:
        last = self._last_scale.get(name, 0.0)
        return (time.time() - last) > self._scale_cooldown_seconds

    def _record_heal(self, name: str) -> None:
        self._heal_cooldown[name] = time.time()

    def _record_scale(self, name: str) -> None:
        self._last_scale[name] = time.time()

    def _enrich_conditions(
        self, state: ClusterState, status: dict
    ) -> dict:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conditions = list(status.get("conditions", []))

        sbs_ok = state.sbs_violation_rate <= state.sbs_threshold
        conditions.append({
            "type": "SBSInvariant",
            "status": "True" if sbs_ok else "False",
            "lastTransitionTime": now,
            "reason": "InvariantCheck",
            "message": "SBS violation %.4f %s %.4f" % (
                state.sbs_violation_rate,
                "<=" if sbs_ok else ">",
                state.sbs_threshold,
            ),
        })

        drift_ok = state.coherence_drift <= state.coherence_drift_max
        conditions.append({
            "type": "CoherenceInvariant",
            "status": "True" if drift_ok else "False",
            "lastTransitionTime": now,
            "reason": "DriftCheck",
            "message": "Drift %.4f %s %.4f" % (
                state.coherence_drift,
                "<=" if drift_ok else ">",
                state.coherence_drift_max,
            ),
        })

        conditions.append({
            "type": "QuorumSafe",
            "status": "True" if state.quorum_safe else "False",
            "lastTransitionTime": now,
            "reason": "QuorumCheck",
            "message": "%d/%d ready" % (state.ready_replicas, state.replicas),
        })

        status["conditions"] = conditions
        return status
