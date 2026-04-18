"""
ATOM OS v14.2 — 8-Step Execution Loop
Deterministic planning + risk scoring + rollback + SBS Enforcement

.. deprecated:: 9.0
    All execution MUST go through ExecutionGateway.execute().
    This module is kept for SBS/AUDIT backward compatibility only.
    Direct calls bypass the G1-G10 safety algebra chain.
"""
from __future__ import annotations
import hashlib, time, random, warnings
from dataclasses import dataclass, field
from typing import Optional

# ── ExecutionGateway (mandatory from v9.0) ───────────────────────────────────
try:
    import sys as _sys
    _sys.path.insert(0, "/home/workspace/atom-federation-os")
    from orchestration.ExecutionGateway import ExecutionGateway as _GW
    _GATEWAY_AVAILABLE = True
except Exception:
    _GATEWAY_AVAILABLE = False

# SBS Runtime Integration v5.2
_SBS_AVAILABLE = False
_SBSEnforcer = None
_SBS_MODE = None
_InvariantViolation = None
_ExecutionStage = None
_COLLECT_STATE = None

try:
    import sys
    sys.path.insert(0, "/home/workspace/atom-federation-os")
    from sbs import (
        SBSRuntimeEnforcer,
        SBS_MODE,
        InvariantViolation,
        ViolationPolicy,
        ExecutionStage,
        SystemBoundarySpec,
        GlobalInvariantEngine,
    )
    _SBS_AVAILABLE = True
    _SBS_MODE = SBS_MODE
    _InvariantViolation = InvariantViolation
    _ExecutionStage = ExecutionStage

    def _build_collect_state(drl_ref, ccl_ref, f2_ref, desc_ref):
        """Build collect_state() closure over layer references."""
        def collect_state() -> dict:
            return {
                "drl": drl_ref() if callable(drl_ref) else drl_ref,
                "ccl": ccl_ref() if callable(ccl_ref) else ccl_ref,
                "f2": f2_ref() if callable(f2_ref) else f2_ref,
                "desc": desc_ref() if callable(desc_ref) else desc_ref,
            }
        return collect_state
    _COLLECT_STATE = _build_collect_state

except Exception:
    pass

# ── Layer state references (populated via set_layers) ─────────────────────────
_drl_state_ref = lambda: {}
_ccl_state_ref = lambda: {}
_f2_state_ref = lambda: {}
_desc_state_ref = lambda: {}

# Keep references to the original defaults so we can detect "never set" state
_atomos_pkg_drl_default = _drl_state_ref
_atomos_pkg_ccl_default = _ccl_state_ref
_atomos_pkg_f2_default = _f2_state_ref
_atomos_pkg_desc_default = _desc_state_ref


@dataclass
class RiskProfile:
    action_type: str
    resource_impact: float
    reversibility: float
    blast_radius: float
    threat_vector: str
    risk_score: float = 0.0
    is_critical: bool = False

@dataclass
class SimulatedStep:
    step_id: str
    description: str
    risk_profile: RiskProfile
    predicted_state_delta: dict
    rollback_plan: dict
    can_proceed: bool = False
    block_reason: str = ""

@dataclass
class ExecutionPlan:
    plan_id: str
    intent: str
    steps: list
    total_risk_score: float = 0.0
    is_safe: bool = False
    blocked_at_step: str = ""
    blocked_reason: str = ""
    federation_hint: str = ""
    verification_hash: str = ""

class ExecutionLoop:
    """
    ATOM OS v14.2 — Deterministic 8-Step Execution Loop
    Steps: PARSE → SIMULATE → RISK → VERIFY → APPROVE → EXECUTE → AUDIT → FEDERATE
    """

    def __init__(self, policy_kernel, federation_layer=None):
        self.pk = policy_kernel
        self.federation = federation_layer
        self._trace = []
        self._executed_plans = {}

    def execute(self, intent: str, context: dict = None) -> ExecutionPlan:
        warnings.warn(
            "ExecutionLoop.execute() is deprecated. Use ExecutionGateway.execute() instead.",
            DeprecationWarning,
        )
        if _GATEWAY_AVAILABLE:
            return _GW.execute(intent, context)
        ctx = context or {}
        step_graph = self._parse_intent(intent, ctx)
        plan_id = hashlib.sha256(
            f"{intent}{time.time_ns()}{random.random()}".encode()
        ).hexdigest()[:16]

        plan = ExecutionPlan(
            plan_id=plan_id, intent=intent, steps=[],
            total_risk_score=0.0, is_safe=False,
        )

        for raw in step_graph:
            simulated = self._simulate_step(raw, plan.steps)
            risk = self._compute_risk(simulated, intent)
            simulated.risk_profile = risk
            simulated.can_proceed = risk.risk_score < 0.7
            if risk.is_critical:
                simulated.can_proceed = False
                simulated.block_reason = f"CRITICAL: {risk.threat_vector}"
            if simulated.can_proceed:
                safe, reason = self._verify_safety(simulated, plan.steps)
                if not safe:
                    simulated.can_proceed = False
                    simulated.block_reason = f"VERIFICATION FAILED: {reason}"
            if simulated.can_proceed:
                action = {"type": raw.get("type", "unknown"), "params": raw.get("params", {})}
                verdict, reason, trace, details = self.pk.evaluate(
                    action=action,
                    context={"intent": intent, "plan_id": plan_id},
                    user_intent=intent,
                )
                if verdict == "VETO":
                    simulated.can_proceed = False
                    simulated.block_reason = f"POLICY VETO: {reason}"
            if not simulated.can_proceed and not plan.blocked_at_step:
                plan.blocked_at_step = raw.get("id", "?")
                plan.blocked_reason = simulated.block_reason
                plan.is_safe = False
                break
            plan.steps.append(simulated)
            plan.total_risk_score += risk.risk_score

        plan.federation_hint = self._federation_hint(plan)
        plan.verification_hash = hashlib.sha256(
            f"{plan_id}{plan.total_risk_score}{len(plan.steps)}".encode()
        ).hexdigest()[:24]
        plan.is_safe = (
            plan.blocked_at_step == "" and plan.total_risk_score < 2.5
        )
        self._executed_plans[plan_id] = plan
        return plan

    # ══════════════════════════════════════════════════════════════════
    # SBS RUNTIME ENFORCEMENT LAYER v5.2
    # ══════════════════════════════════════════════════════════════════

    def set_layers(
        self,
        drl_state_getter: callable,
        ccl_state_getter: callable,
        f2_state_getter: callable,
        desc_state_getter: callable,
    ) -> None:
        """
        Register layer state getter functions for SBS collect_state().

        Call this BEFORE execute_with_sbs() to enable SBS enforcement.

        Parameters
        ----------
        drl_state_getter : callable → dict
            Returns current DRL layer state snapshot.
        ccl_state_getter : callable → dict
            Returns current CCL layer state snapshot.
        f2_state_getter : callable → dict
            Returns current F2 quorum kernel state snapshot.
        desc_state_getter : callable → dict
            Returns current DESC event-sourcing state snapshot.

        Example
        -------
        >>> loop.set_layers(
        ...     drl_state_getter=lambda: drl.get_state(),
        ...     ccl_state_getter=lambda: ccl.get_state(),
        ...     f2_state_getter=lambda: f2.get_state(),
        ...     desc_state_getter=lambda: desc.get_state(),
        ... )
        """
        global _drl_state_ref, _ccl_state_ref, _f2_state_ref, _desc_state_ref
        _drl_state_ref = drl_state_getter
        _ccl_state_ref = ccl_state_getter
        _f2_state_ref = f2_state_getter
        _desc_state_ref = desc_state_getter

    def collect_state(self) -> dict:
        """
        Collect aggregate state snapshot from all registered layers.

        Returns
        -------
        dict
            ``{"drl": {...}, "ccl": {...}, "f2": {...}, "desc": {...}}``

        Call this at any SBS enforcement point to capture a consistent
        cross-layer snapshot for invariant evaluation.
        """
        return {
            "drl": _drl_state_ref(),
            "ccl": _ccl_state_ref(),
            "f2": _f2_state_ref(),
            "desc": _desc_state_ref(),
        }

    def execute_with_sbs(
        self,
        intent: str,
        context: dict = None,
        sbs_enforcer=None,
        sbs_mode=None,
    ) -> tuple[ExecutionPlan, dict | None]:
        """
        Execute intent WITH SBS runtime enforcement.

        SBS enforcement points inserted into the execution flow:
            pre_drl → post_drl → post_quorum → pre_commit → post_commit

        If ``sbs_enforcer`` is None or SBS is unavailable, falls back
        to regular ``execute()``.

        Parameters
        ----------
        intent : str
            User/system intent to execute.
        context : dict | None
            Execution context.
        sbs_enforcer : SBSRuntimeEnforcer | None
            Pre-configured SBS enforcer. Created automatically if None
            (requires layers to be registered via ``set_layers``).
        sbs_mode : SBS_MODE | None
            Override enforcement mode. Defaults to ENFORCED.

        Returns
        -------
        tuple[ExecutionPlan, dict | None]
            ``(plan, violation_state)`` where ``violation_state`` is None
            on success, or a dict with violation details if SBS blocked
            execution.

        Raises
        ------
        InvariantViolation
            In ENFORCED mode when SBS invariants are violated.
        """
        if not _SBS_AVAILABLE:
            return self.execute(intent, context), None

        # Build or validate enforcer.
        # When sbs_enforcer is None AND layers aren't configured yet,
        # default to AUDIT mode so the system fails open (logs, doesn't block)
        # until the caller explicitly wires up layer state getters.
        enforcer = sbs_enforcer
        if enforcer is None:
            spec = SystemBoundarySpec()
            engine = GlobalInvariantEngine(spec)
            # Detect "never-set" state: all refs point to the empty-defaults
            using_defaults = (
                _drl_state_ref is _atomos_pkg_drl_default
                and _ccl_state_ref is _atomos_pkg_ccl_default
                and _f2_state_ref is _atomos_pkg_f2_default
                and _desc_state_ref is _atomos_pkg_desc_default
            )
            # Graceful degradation: AUDIT when layers not registered yet
            mode = sbs_mode or (
                _SBS_MODE.AUDIT if using_defaults else _SBS_MODE.ENFORCED
            )
            enforcer = SBSRuntimeEnforcer(spec, engine, mode=mode)

        mode = enforcer.mode

        def enforce(stage: str, state: dict) -> bool:
            """SBS enforce helper — raises on violation in ENFORCED mode."""
            return enforcer.enforce(stage, state)

        # ── pre_drl ────────────────────────────────────────────────────
        state = self.collect_state()
        enforce(_ExecutionStage.PRE_DRL, state)

        # ── Main execution (mirrors execute()) ─────────────────────────
        ctx = context or {}
        step_graph = self._parse_intent(intent, ctx)
        plan_id = hashlib.sha256(
            f"{intent}{time.time_ns()}{random.random()}".encode()
        ).hexdigest()[:16]

        plan = ExecutionPlan(
            plan_id=plan_id, intent=intent, steps=[],
            total_risk_score=0.0, is_safe=False,
        )

        for raw in step_graph:
            simulated = self._simulate_step(raw, plan.steps)
            risk = self._compute_risk(simulated, intent)
            simulated.risk_profile = risk
            simulated.can_proceed = risk.risk_score < 0.7
            if risk.is_critical:
                simulated.can_proceed = False
                simulated.block_reason = f"CRITICAL: {risk.threat_vector}"
            if simulated.can_proceed:
                safe, reason = self._verify_safety(simulated, plan.steps)
                if not safe:
                    simulated.can_proceed = False
                    simulated.block_reason = f"VERIFICATION FAILED: {reason}"
            if simulated.can_proceed:
                action = {
                    "type": raw.get("type", "unknown"),
                    "params": raw.get("params", {}),
                }
                verdict, reason, trace, details = self.pk.evaluate(
                    action=action,
                    context={"intent": intent, "plan_id": plan_id},
                    user_intent=intent,
                )
                if verdict == "VETO":
                    simulated.can_proceed = False
                    simulated.block_reason = f"POLICY VETO: {reason}"

            # ── post_drl ───────────────────────────────────────────────
            state = self.collect_state()
            enforce(_ExecutionStage.POST_DRL, state)

            if not simulated.can_proceed and not plan.blocked_at_step:
                plan.blocked_at_step = raw.get("id", "?")
                plan.blocked_reason = simulated.block_reason
                plan.is_safe = False
                break

            plan.steps.append(simulated)
            plan.total_risk_score += risk.risk_score

        # ── post_quorum ────────────────────────────────────────────────
        state = self.collect_state()
        enforce(_ExecutionStage.POST_QUORUM, state)

        # ── pre_commit ────────────────────────────────────────────────
        state = self.collect_state()
        enforce(_ExecutionStage.PRE_COMMIT, state)

        # ── execute / finalise ────────────────────────────────────────
        if plan.blocked_at_step:
            plan.federation_hint = "BROADCAST_BLOCK"
            plan.verification_hash = hashlib.sha256(
                f"{plan_id}{plan.total_risk_score}{len(plan.steps)}".encode()
            ).hexdigest()[:24]
            self._executed_plans[plan_id] = plan
            return plan, None

        plan.federation_hint = self._federation_hint(plan)
        plan.verification_hash = hashlib.sha256(
            f"{plan_id}{plan.total_risk_score}{len(plan.steps)}".encode()
        ).hexdigest()[:24]
        plan.is_safe = (
            plan.blocked_at_step == "" and plan.total_risk_score < 2.5
        )
        self._executed_plans[plan_id] = plan

        # ── post_commit ───────────────────────────────────────────────
        state = self.collect_state()
        enforce(_ExecutionStage.POST_COMMIT, state)

        return plan, None

    @staticmethod
    def sbs_is_available() -> bool:
        """Return True if SBS runtime is available and imported."""
        return _SBS_AVAILABLE

    @staticmethod
    def get_sbs_mode_enum():
        """Return SBS_MODE enum if available, else None."""
        return _SBS_MODE

    def _parse_intent(self, intent: str, ctx: dict) -> list[dict]:
        steps = []
        lowered = intent.lower()
        devops_kw = ["ci fail", "github", "workflow", "build", "pipeline",
                     "lint", "ruff", "pytest", "test", "module", "error",
                     "run failed", "job", "step"]
        create_kw = ["create", "generate", "make", "new"]
        write_kw = ["write", "update", "patch", "fix", "modify"]
        delete_kw = ["delete", "remove", "rm", "destroy"]
        detected = []
        for kw, lst in [(devops_kw, ["devops"]), (create_kw, ["create"]),
                         (write_kw, ["write"]), (delete_kw, ["delete"])]:
            if any(k in lowered for k in kw):
                detected.extend(lst)
        aid = 0
        type_map = {
            "devops": ("devops_analyze", {"log": intent}),
            "create": ("file_write", {"path": f"/workspace/{ctx.get('target','default')}", "content": "auto"}),
            "write": ("file_modify", {"match": intent[:60]}),
            "delete": ("file_delete", {"path": "/workspace"}),
        }
        for kw in ["devops", "create", "write", "delete"]:
            if kw in detected:
                atype, params = type_map[kw]
                steps.append({"id": f"step_{aid}", "type": atype, "params": params})
                aid += 1
        if not steps:
            steps.append({"id": "step_0", "type": "generic", "params": {"intent": intent[:120]}})
        return steps

    def _simulate_step(self, raw: dict, prior_steps: list) -> SimulatedStep:
        step_id = raw.get("id", "?")
        atype = raw.get("type", "unknown")
        params = raw.get("params", {})
        delta = {"files_read": 0, "files_written": 0, "memory_delta_mb": 0}
        rollback = {"action": "no-op"}
        if atype == "devops_analyze":
            delta = {"files_read": 10, "memory_delta_mb": 50}
            rollback = {"action": "no-op"}
        elif atype == "file_write":
            delta = {"files_written": 1, "memory_delta_mb": 5}
            rollback = {"action": "delete", "path": params.get("path", "/tmp")}
        elif atype == "file_modify":
            delta = {"files_written": 1, "memory_delta_mb": 10}
            rollback = {"action": "git_restore", "path": params.get("match", "")}
        elif atype == "file_delete":
            delta = {"files_written": -1}
            rollback = {"action": "restore_from_backup", "path": params.get("path", "/tmp")}
        return SimulatedStep(
            step_id=step_id, description=f"{atype}",
            risk_profile=RiskProfile(
                action_type=atype,
                resource_impact=abs(delta.get("files_written", 0)) / 10,
                reversibility=0.9 if atype not in ("file_write", "file_modify") else 0.7,
                blast_radius=0.1 if atype != "file_delete" else 0.8,
                threat_vector="none",
            ),
            predicted_state_delta=delta, rollback_plan=rollback,
            can_proceed=False,
        )

    def _compute_risk(self, step: SimulatedStep, intent: str) -> RiskProfile:
        rp = step.risk_profile
        lowered = intent.lower()
        score = rp.resource_impact * 0.3
        score += (1.0 - rp.reversibility) * 0.25
        score += rp.blast_radius * 0.3
        score += rp.resource_impact * 0.15
        destroy_kw = ["rm -rf", "drop", "truncate", "delete all", "format"]
        system_kw = ["sudo", "chmod 777", "/etc", "/sys", "/proc"]
        network_kw = ["curl ", "wget", "http://", "ssh", "nc "]
        escape_kw = ["chroot", "namespace", "--privileged", "docker run"]
        if any(k in lowered for k in destroy_kw):
            score = max(score, 0.85); rp.threat_vector = "DESTRUCTION"
        elif any(k in lowered for k in system_kw):
            score = max(score, 0.70); rp.threat_vector = "SYSTEM_ESCALATION"
        elif any(k in lowered for k in network_kw):
            score = max(score, 0.50); rp.threat_vector = "NETWORK_EXFILTRATION"
        elif any(k in lowered for k in escape_kw):
            score = max(score, 0.75); rp.threat_vector = "CONTAINER_ESCAPE"
        rp.risk_score = min(score, 1.0)
        rp.is_critical = rp.risk_score >= 0.80
        return rp

    def _verify_safety(self, step: SimulatedStep, prior_steps: list) -> tuple[bool, str]:
        rp = step.risk_profile
        if rp.blast_radius > 0.9:
            return False, "Blast radius exceeds safety threshold"
        if rp.reversibility < 0.2 and rp.risk_score > 0.5:
            return False, "Irreversible action with high risk"
        for ps in prior_steps:
            if not ps.can_proceed:
                return False, f"Prior step {ps.step_id} not approved"
        total = sum(s.risk_profile.risk_score for s in prior_steps)
        if total + step.risk_profile.risk_score > 2.5:
            return False, "Cumulative risk exceeds threshold"
        return True, "VERIFIED"

    def _federation_hint(self, plan: ExecutionPlan) -> str:
        if plan.total_risk_score > 2.0:
            return "BROADCAST_BLOCK"
        elif plan.is_safe and plan.total_risk_score < 0.5:
            return "FEDERATE_SUCCESS"
        return "FEDERATE_ADVISORY"

    def execute_plan(self, plan: ExecutionPlan) -> dict:
        results = {
            "plan_id": plan.plan_id, "executed_steps": [],
            "blocked": plan.blocked_at_step != "",
            "blocked_reason": plan.blocked_reason,
            "status": "COMPLETED" if not plan.blocked_at_step else "BLOCKED",
            "risk_score": plan.total_risk_score,
        }
        if plan.blocked_at_step:
            return results
        for step in plan.steps:
            results["executed_steps"].append({
                "step_id": step.step_id, "description": step.description,
                "risk_score": step.risk_profile.risk_score, "status": "executed",
            })
        self._trace.append(results)
        return results

if __name__ == "__main__":
    print("╔══════════════════════════════════════╗")
    print("║  ATOM OS v14.2 — 8-Step Execution    ║")
    print("║  Loop with Risk Scoring (DETERMINISTIC)║")
    print("╚══════════════════════════════════════╝")
    import sys
    # Support imports from workspace: atomos_pkg AND agents/ are both under /home/workspace
    _ATOMOS_WS = "/home/workspace"
    if _ATOMOS_WS not in sys.path:
        sys.path.insert(0, _ATOMOS_WS)
    sys.path.insert(0, '/home/workspace/atomos_pkg')
    sys.path.insert(0, '/home/workspace/agents')
    from policy_kernel_v4 import PolicyKernelV4
    pk = PolicyKernelV4()
    loop = ExecutionLoop(policy_kernel=pk)
    for intent in [
        "ci fail: ruff error agents/ci_analyzer.py",
        "create new agent swarm engine for parallel tasks",
        "read system status and show logs",
        "fix import error in tools_adapter.py line 25",
    ]:
        print(f"\n{'='*60}")
        plan = loop.execute(intent)
        status = "✅ SAFE" if plan.is_safe else f"🚫 BLOCKED at {plan.blocked_at_step}"
        print(f"Intent : {intent[:60]}")
        print(f"Plan ID: {plan.plan_id}")
        print(f"Steps  : {len(plan.steps)}")
        print(f"Risk   : {plan.total_risk_score:.3f} {status}")
        if plan.blocked_reason:
            print(f"Block  : {plan.blocked_reason}")
        print(f"Hash   : {plan.verification_hash}")
        print(f"Federate: {plan.federation_hint}")
    print("\n[8-STEP LOOP] ✅ All tests complete")