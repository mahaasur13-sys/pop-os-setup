"""Safety gate — blocks high-risk patches."""

from phase3.validator.gates.base_gate import BaseGate, GateResult


class SafetyGate(BaseGate):
    """
    Validates patch risk score is within acceptable bounds.
    
    FAILS if:
        - patch.risk > RISK_THRESHOLD (default 0.5)
        - high-risk actions detected without justification
    """
    
    def __init__(self, risk_threshold: float = 0.5):
        self.risk_threshold = risk_threshold
    
    @property
    def name(self) -> str:
        return "safety_gate"
    
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Check patch risk level is acceptable.
        
        Args:
            plan: Repair plan with risk assessment.
            snapshot: Current system state.
        """
        # Extract risk from plan
        risk = plan.get("risk", 0.0)
        
        # Check 1: Risk threshold
        if risk > self.risk_threshold:
            return self._fail(
                reason=f"Patch risk {risk} exceeds threshold {self.risk_threshold}",
                severity="high",
                details={"risk": risk, "threshold": self.risk_threshold}
            )
        
        # Check 2: High-risk action categories
        high_risk_actions = {"delete_node", "drop_table", "kill_process", "rm_rf"}
        actions = plan.get("actions", [])
        
        risky_actions = []
        for action in actions:
            action_type = action.get("type", "")
            if action_type in high_risk_actions:
                justification = action.get("justification", "")
                if not justification:
                    risky_actions.append(action_type)
        
        if risky_actions:
            return self._fail(
                reason=f"High-risk actions without justification: {risky_actions}",
                severity="high",
                details={"risky_actions": risky_actions}
            )
        
        return self._pass(
            reason=f"Safety check passed. Risk={risk} <= {self.risk_threshold}",
            details={"risk": risk, "threshold": self.risk_threshold}
        )
