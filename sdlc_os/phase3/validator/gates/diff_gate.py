"""Diff gate — validates patch scope and structural change classification."""

from phase3.validator.gates.base_gate import BaseGate, GateResult


class DiffGate(BaseGate):
    """
    Validates patch scope and change classification.
    
    FAILS if:
        - Patch modifies more than MAX_FILES (configurable, default 10)
        - Structural change without proper classification
    
    This gate prevents "big bang" changes that are hard to review.
    """
    
    def __init__(self, max_files: int = 10, max_structural_changes: int = 3):
        self.max_files = max_files
        self.max_structural_changes = max_structural_changes
    
    @property
    def name(self) -> str:
        return "diff_gate"
    
    def check(self, plan: dict, snapshot: dict) -> GateResult:
        """
        Check patch scope and structural change compliance.
        
        Args:
            plan: Repair plan with file modifications.
            snapshot: Current system state.
        """
        actions = plan.get("actions", [])
        
        # Count file modifications
        file_modifications: set[str] = set()
        structural_changes: list[dict] = []
        
        for action in actions:
            action_type = action.get("type", "")
            
            if action_type in ("modify_file", "create_file", "delete_file"):
                file_path = action.get("file_path", "")
                if file_path:
                    file_modifications.add(file_path)
            
            elif action_type == "modify_graph":
                # This is structural change — must be classified
                structural_changes.append(action)
        
        # Check 1: File count limit
        if len(file_modifications) > self.max_files:
            return self._fail(
                reason=f"Patch modifies {len(file_modifications)} files (limit: {self.max_files})",
                severity="high",
                details={
                    "file_count": len(file_modifications),
                    "max_allowed": self.max_files,
                    "files": list(file_modifications)
                }
            )
        
        # Check 2: Structural changes require classification
        for change in structural_changes:
            diff_type = change.get("diff_type", "")
            if not diff_type:
                return self._fail(
                    reason="Structural change without diff_type classification",
                    severity="medium",
                    details={"change": change}
                )
        
        # Check 3: Limit structural changes
        if len(structural_changes) > self.max_structural_changes:
            return self._fail(
                reason=f"Too many structural changes: {len(structural_changes)} (max: {self.max_structural_changes})",
                severity="medium",
                details={
                    "structural_change_count": len(structural_changes),
                    "max_allowed": self.max_structural_changes
                }
            )
        
        return self._pass(
            reason=f"Diff check passed. {len(file_modifications)} files, {len(structural_changes)} structural changes.",
            details={
                "file_count": len(file_modifications),
                "structural_changes": len(structural_changes),
                "files": list(file_modifications)
            }
        )