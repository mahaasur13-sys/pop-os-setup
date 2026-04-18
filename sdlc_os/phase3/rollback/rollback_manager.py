"""Rollback manager — reverts file system state on failure."""

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phase3.exceptions import RollbackError


@dataclass
class RollbackCheckpoint:
    """Checkpoint storing state for rollback."""
    checkpoint_id: str
    snapshot: dict
    file_backups: dict[str, str]  # file_path -> backup_content_or_path
    timestamp: str = ""
    
    def __post_init__(self):
        if self.timestamp == "":
            self.timestamp = datetime.now(timezone.utc).isoformat()


class RollbackManager:
    """
    Manages rollback checkpoints and state restoration.
    
    Trigger conditions:
        - post-execution validation fails
        - drift_score increases after patch
        - executor raises error during execution
    
    Rollback MUST be idempotent.
    """
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self._checkpoints_dir = Path(tempfile.mkdtemp(prefix="sdlc_rollbacks_"))
        self._current_checkpoint: RollbackCheckpoint | None = None
    
    def create_checkpoint(self, snapshot: dict) -> RollbackCheckpoint:
        """
        Create checkpoint before patch application.
        
        Stores current file state for all tracked files.
        """
        import uuid
        checkpoint_id = f"cp_{uuid.uuid4().hex[:8]}"
        
        file_backups: dict[str, str] = {}
        
        # Backup all files in graph nodes
        for node in snapshot.get("graph_nodes", []):
            file_path = node.get("file_path", "")
            if file_path:
                full_path = self.repo_path / file_path
                if full_path.exists():
                    # Store content directly for small files
                    try:
                        content = full_path.read_text()
                        file_backups[file_path] = content
                    except Exception:
                        # Binary or large file — skip backup
                        pass
        
        checkpoint = RollbackCheckpoint(
            checkpoint_id=checkpoint_id,
            snapshot=snapshot,
            file_backups=file_backups,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Save checkpoint to disk
        cp_file = self._checkpoints_dir / f"{checkpoint_id}.json"
        with open(cp_file, "w") as f:
            json.dump({
                "checkpoint_id": checkpoint.checkpoint_id,
                "snapshot": checkpoint.snapshot,
                "file_backups": checkpoint.file_backups,
                "timestamp": checkpoint.timestamp
            }, f, default=str)
        
        self._current_checkpoint = checkpoint
        return checkpoint
    
    def rollback(self, reason: str = "") -> dict:
        """
        Perform rollback to last checkpoint.
        
        Args:
            reason: Why rollback is being performed.
            
        Returns:
            Snapshot state before patch.
            
        Raises:
            RollbackError: If no checkpoint exists or rollback fails.
        """
        if self._current_checkpoint is None:
            raise RollbackError("No checkpoint available for rollback")
        
        cp = self._current_checkpoint
        
        # Restore all files
        for file_path, content in cp.file_backups.items():
            full_path = self.repo_path / file_path
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
            except Exception as e:
                raise RollbackError(f"Failed to restore file {file_path}: {e}") from e
        
        # Cleanup checkpoint
        self._cleanup_checkpoint(cp)
        
        return cp.snapshot
    
    def verify_rollback(self, snapshot_before: dict, snapshot_after: dict) -> bool:
        """
        Verify rollback restored original state.
        
        Returns True if state matches checkpoint, False otherwise.
        """
        # Compare key metrics
        if snapshot_before.get("drift_score") != snapshot_after.get("drift_score"):
            return False
        
        if snapshot_before.get("drift_level") != snapshot_after.get("drift_level"):
            return False
        
        return True
    
    def _cleanup_checkpoint(self, checkpoint: RollbackCheckpoint) -> None:
        """Remove checkpoint file after successful rollback."""
        cp_file = self._checkpoints_dir / f"{checkpoint.checkpoint_id}.json"
        if cp_file.exists():
            cp_file.unlink()
        self._current_checkpoint = None
    
    def list_checkpoints(self) -> list[dict]:
        """List all available checkpoints."""
        checkpoints = []
        for cp_file in self._checkpoints_dir.glob("*.json"):
            try:
                with open(cp_file) as f:
                    data = json.load(f)
                    checkpoints.append({
                        "checkpoint_id": data.get("checkpoint_id"),
                        "timestamp": data.get("timestamp"),
                        "file_count": len(data.get("file_backups", {}))
                    })
            except Exception:
                continue
        return checkpoints
