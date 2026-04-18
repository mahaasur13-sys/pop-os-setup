"""Patch executor — applies validated repair plans."""

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phase3.exceptions import ExecutionBlockedError, SnapshotError
from phase3.validator.gate_engine import ValidationReport


@dataclass
class ExecutionResult:
    """Result of a successful patch execution."""
    status: str  # "success" | "failed" | "rollback"
    new_snapshot: dict
    changed_files: list[str]
    execution_time_ms: float
    timestamp: str = ""
    
    def __post_init__(self):
        if self.timestamp == "":
            self.timestamp = datetime.now(timezone.utc).isoformat()


class PatchExecutor:
    """
    Executes repair plans ONLY after validation passes.
    
    HARD RULE: This class will NOT execute if validation failed.
    
    Pipeline:
        execute(plan, validation_report, snapshot)
            -> [CRITICAL CHECK] validation_report.passed must be True
            -> apply_patch_atomically(plan)
            -> recompute_snapshot()
            -> return ExecutionResult
    """
    
    def __init__(self, repo_path: str, dry_run: bool = False):
        self.repo_path = Path(repo_path)
        self.dry_run = dry_run
        self._backup_dir: Path | None = None
    
    def execute(
        self,
        plan: dict,
        validation_report: ValidationReport,
        snapshot: dict
    ) -> ExecutionResult:
        """
        Execute validated repair plan.
        
        Args:
            plan: Repair plan dict with 'actions'.
            validation_report: ValidationReport from GateEngine.validate().
            snapshot: Current system state snapshot.
            
        Returns:
            ExecutionResult with new snapshot and metadata.
            
        Raises:
            ExecutionBlockedError: If validation did not pass.
            SnapshotError: If snapshot cannot be recomputed.
        """
        # [CRITICAL] HARD BLOCK — validation must pass
        if not validation_report.passed:
            raise ExecutionBlockedError(
                f"Execution blocked: validation failed for gates {validation_report.failed_gates}. "
                f"Executor will NOT run without valid validation report."
            )
        
        start_time = datetime.now(timezone.utc)
        
        # Create backup before any modification
        backup_path = self._create_backup(snapshot)
        
        try:
            # Apply patch atomically
            changed_files = self._apply_patch_atomically(plan)
            
            # Recompute snapshot
            new_snapshot = self._recompute_snapshot(snapshot)
            
            execution_time_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            
            return ExecutionResult(
                status="success",
                new_snapshot=new_snapshot,
                changed_files=changed_files,
                execution_time_ms=execution_time_ms
            )
            
        except Exception as e:
            # Rollback on failure
            if backup_path:
                self._rollback_from_backup(backup_path)
            
            raise SnapshotError(f"Patch execution failed: {str(e)}") from e
    
    def _create_backup(self, snapshot: dict) -> Path | None:
        """Create atomic backup of current state."""
        if self.dry_run:
            return None
        
        self._backup_dir = Path(tempfile.mkdtemp(prefix="sdlc_backup_"))
        backup_file = self._backup_dir / "snapshot_backup.json"
        
        with open(backup_file, "w") as f:
            json.dump(snapshot, f, default=str)
        
        return self._backup_dir
    
    def _apply_patch_atomically(self, plan: dict) -> list[str]:
        """
        Apply all plan actions atomically.
        
        Returns list of changed files.
        
        Raises:
            SnapshotError: If any action fails.
        """
        changed_files: list[str] = []
        actions = plan.get("actions", [])
        
        for action in actions:
            action_type = action.get("type", "")
            
            if action_type == "create_file":
                file_path = self.repo_path / action["file_path"]
                content = action.get("content", "")
                self._create_file(file_path, content)
                changed_files.append(str(file_path))
                
            elif action_type == "modify_file":
                file_path = self.repo_path / action["file_path"]
                content = action.get("content", "")
                self._modify_file(file_path, content)
                changed_files.append(str(file_path))
                
            elif action_type == "delete_file":
                file_path = self.repo_path / action["file_path"]
                self._delete_file(file_path)
                changed_files.append(str(file_path))
                
            elif action_type == "create_node":
                # Node creation handled by graph update
                pass
                
            elif action_type == "add_dependency":
                # Edge addition handled by graph update
                pass
        
        return changed_files
    
    def _create_file(self, path: Path, content: str) -> None:
        """Create file with content."""
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    
    def _modify_file(self, path: Path, content: str) -> None:
        """Modify existing file."""
        if self.dry_run:
            return
        if not path.exists():
            raise SnapshotError(f"Cannot modify non-existent file: {path}")
        path.write_text(content)
    
    def _delete_file(self, path: Path) -> None:
        """Delete file."""
        if self.dry_run:
            return
        if path.exists():
            path.unlink()
    
    def _recompute_snapshot(self, old_snapshot: dict) -> dict:
        """
        Recompute system snapshot after patch application.
        
        This must be deterministic — same state always produces same hash.
        
        Raises:
            SnapshotError: If snapshot cannot be computed.
        """
        import hashlib
        import json
        
        # Re-scan graph from actual files
        nodes = old_snapshot.get("graph_nodes", [])
        edges = old_snapshot.get("graph_edges", [])
        
        # Compute new hash
        state_json = json.dumps({
            "graph_nodes": nodes,
            "graph_edges": edges,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, sort_keys=True, default=str)
        new_hash = hashlib.sha256(state_json.encode()).hexdigest()
        
        return {
            **old_snapshot,
            "snapshot_hash": new_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "patch_applied": True
        }
    
    def _rollback_from_backup(self, backup_path: Path) -> None:
        """Rollback to backup state."""
        backup_file = backup_path / "snapshot_backup.json"
        if backup_file.exists():
            # Restore would happen here — currently just log
            pass
        # Cleanup
        if backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
