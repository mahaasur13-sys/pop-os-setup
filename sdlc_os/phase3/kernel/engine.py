"""Kernel — the main SDLC OS Phase 3 execution engine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phase3.exceptions import (
    ValidationError,
    ExecutionBlockedError,
    RollbackError,
    SnapshotError,
)
from phase3.validator.gate_engine import GateEngine, ValidationReport
from phase3.validator.gates.graph_gate import GraphGate
from phase3.validator.gates.policy_gate import PolicyGate
from phase3.validator.gates.diff_gate import DiffGate
from phase3.validator.gates.determinism_gate import DeterminismGate
from phase3.validator.gates.safety_gate import SafetyGate
from phase3.executor.patch_executor import PatchExecutor, ExecutionResult
from phase3.rollback.rollback_manager import RollbackManager
from phase3.commit.commit_manager import CommitManager, CommitReadyOutput
from phase3.audit.ledger import AuditLedger, AuditEntry


@dataclass
class KernelResult:
    """
    Result from Kernel execution.
    
    Attributes:
        status: "success" | "validation_failed" | "execution_blocked" | "rollback" | "error"
        validation_report: Report from gate validation.
        execution_result: Result from patch execution (if executed).
        commit_output: Commit-ready output (if executed).
        audit_entry: Audit log entry (if executed).
        error: Error message if failed.
    """
    status: str
    validation_report: ValidationReport | None = None
    execution_result: ExecutionResult | None = None
    commit_output: CommitReadyOutput | None = None
    audit_entry: AuditEntry | None = None
    error: str | None = None
    timestamp: str = ""


class Kernel:
    """
    Main SDLC OS Phase 3 execution kernel.
    
    This is the ONLY entry point for patch execution.
    
    Pipeline (HARD CONTRACT):
        1. repair_plan
        2. -> validator.validate(plan)
        3. -> validation_report
            4. -> executor.execute(plan, report)
            5. -> execution_result
                6. -> commit_manager.prepare(result)
                7. -> audit_ledger.append(entry)
    
    If validation fails at step 2:
        -> executor MUST NOT run (raise ValidationError)
    
    If execution fails at step 4:
        -> rollback_manager.rollback()
        -> audit_ledger.append(failed entry)
    
    HARD RULES:
        - Validator must pass before execution
        - Executor will NOT run without valid report
        - Rollback must succeed — system crashes if it fails
        - Audit ledger append-only — no overwrites
    """
    
    def __init__(
        self,
        repo_path: str,
        ledger_path: str | None = None,
        enable_rollback: bool = True,
        dry_run: bool = False
    ):
        self.repo_path = Path(repo_path)
        self.dry_run = dry_run
        self.enable_rollback = enable_rollback
        
        # Initialize components
        self.validator = GateEngine()
        self.executor = PatchExecutor(repo_path=str(self.repo_path), dry_run=dry_run)
        self.rollback_mgr = RollbackManager(repo_path=str(self.repo_path))
        self.commit_mgr = CommitManager(repo_path=str(self.repo_path))
        self.audit_ledger = AuditLedger(ledger_path=ledger_path)
        
        # Register all gates
        self._register_gates()
        
        # Internal state
        self._snapshot_before: dict | None = None
    
    def _register_gates(self) -> None:
        """Register all validation gates."""
        self.validator.register_gate(GraphGate())
        self.validator.register_gate(PolicyGate())
        self.validator.register_gate(DiffGate(max_files=15))
        self.validator.register_gate(DeterminismGate(runs=2))
        self.validator.register_gate(SafetyGate(risk_threshold=0.5))
    
    def run(
        self,
        plan: dict,
        snapshot: dict
    ) -> KernelResult:
        """
        Execute repair plan through Phase 3 pipeline.
        
        Args:
            plan: Repair plan dict with 'actions' key.
            snapshot: Current system state snapshot.
            
        Returns:
            KernelResult with all outputs from pipeline stages.
            
        Raises:
            ValidationError: If validation fails (caught and returned in result).
            ExecutionBlockedError: If executor would run without validation.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Store snapshot for commit manager
        self._snapshot_before = snapshot
        
        try:
            # STEP 1: Validate plan
            validation_report = self.validator.validate(plan, snapshot)
            
            # CRITICAL CHECK — raise if validation failed
            if not validation_report.passed:
                return KernelResult(
                    status="validation_failed",
                    validation_report=validation_report,
                    error=f"Validation failed for gates: {validation_report.failed_gates}",
                    timestamp=timestamp
                )
            
            # STEP 2: Create rollback checkpoint
            if self.enable_rollback:
                self.rollback_mgr.create_checkpoint(snapshot)
            
            # STEP 3: Execute patch
            execution_result = self.executor.execute(
                plan=plan,
                validation_report=validation_report,
                snapshot=snapshot
            )
            
            # STEP 4: Prepare commit output
            new_snapshot = execution_result.new_snapshot
            commit_output = self.commit_mgr.prepare(
                execution_result=execution_result.__dict__,
                snapshot_before=snapshot,
                snapshot_after=new_snapshot
            )
            
            # STEP 5: Append audit entry
            audit_entry = self.audit_ledger.append(
                snapshot_hash=new_snapshot.get("snapshot_hash", ""),
                drift_score=new_snapshot.get("drift_score", 0.0),
                execution_result={
                    "status": execution_result.status,
                    "changed_files": execution_result.changed_files,
                    "execution_time_ms": execution_result.execution_time_ms
                }
            )
            
            return KernelResult(
                status="success",
                validation_report=validation_report,
                execution_result=execution_result,
                commit_output=commit_output,
                audit_entry=audit_entry,
                timestamp=timestamp
            )
            
        except ValidationError as e:
            return KernelResult(
                status="validation_failed",
                error=str(e),
                timestamp=timestamp
            )
            
        except ExecutionBlockedError as e:
            return KernelResult(
                status="execution_blocked",
                error=str(e),
                timestamp=timestamp
            )
            
        except Exception as e:
            # Attempt rollback
            if self.enable_rollback and self._snapshot_before:
                try:
                    self.rollback_mgr.rollback(reason=str(e))
                except RollbackError as re:
                    # CRITICAL: Rollback failed — system must crash
                    raise SnapshotError(
                        f"FATAL: Execution failed AND rollback failed. System in inconsistent state. {re}"
                    ) from re
            
            return KernelResult(
                status="error",
                error=str(e),
                timestamp=timestamp
            )
    
    def get_audit_log(self) -> list[AuditEntry]:
        """Get all audit entries."""
        return self.audit_ledger.get_all()
    
    def get_last_audit_entry(self) -> AuditEntry | None:
        """Get most recent audit entry."""
        return self.audit_ledger.get_last()
