"""Commit manager — generates commit-ready outputs (NO git mutation)."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CommitReadyOutput:
    """
    Commit-ready output from commit manager.
    
    This is a SAFE artifact — can be reviewed before git commit.
    
    Attributes:
        commit_message: Generated commit message (conventional format).
        changed_files: List of files that would be committed.
        diff_summary: Summary of changes by type.
        hash: Content hash for verification.
    """
    commit_message: str
    changed_files: list[str]
    diff_summary: dict[str, Any]
    hash: str
    timestamp: str = ""
    
    def __post_init__(self):
        if self.timestamp == "":
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> dict:
        return {
            "commit_message": self.commit_message,
            "changed_files": self.changed_files,
            "diff_summary": self.diff_summary,
            "hash": self.hash,
            "timestamp": self.timestamp
        }
    
    def save(self, path: str) -> None:
        """Save output to file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


class CommitManager:
    """
    Generates commit-ready artifacts WITHOUT mutating git.
    
    SAFE OPERATIONS:
        ✅ generate_commit_message()
        ✅ list_changed_files()
        ✅ compute_diff_summary()
        ✅ save_commit_output()
    
    FORBIDDEN OPERATIONS:
        ✖ git commit
        ✖ git push
        ✖ git merge
        ✖ Any remote operations
    """
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
    
    def prepare(self, execution_result: dict, snapshot_before: dict, snapshot_after: dict) -> CommitReadyOutput:
        """
        Prepare commit-ready output from execution result.
        
        Args:
            execution_result: Result from PatchExecutor.
            snapshot_before: State before patch.
            snapshot_after: State after patch.
            
        Returns:
            CommitReadyOutput with all artifacts for review.
        """
        changed_files = execution_result.get("changed_files", [])
        
        # Generate commit message
        commit_message = self._generate_commit_message(snapshot_before, snapshot_after, changed_files)
        
        # Compute diff summary
        diff_summary = self._compute_diff_summary(snapshot_before, snapshot_after, changed_files)
        
        # Compute content hash
        content_hash = self._compute_content_hash(changed_files, diff_summary)
        
        return CommitReadyOutput(
            commit_message=commit_message,
            changed_files=changed_files,
            diff_summary=diff_summary,
            hash=content_hash
        )
    
    def _generate_commit_message(self, before: dict, after: dict, changed_files: list[str]) -> str:
        """
        Generate conventional commit message.
        
        Format:
            <type>(<scope>): <subject>
            
            [body]
        """
        diffs = after.get("diffs", [])
        drift_before = before.get("drift_score", 0.0)
        drift_after = after.get("drift_score", 0.0)
        
        # Determine change type
        if drift_after < drift_before:
            change_type = "fix"
            subject = f"reduce drift {drift_before:.3f} -> {drift_after:.3f}"
        elif drift_after > drift_before:
            change_type = "chore"
            subject = f"drift increased {drift_before:.3f} -> {drift_after:.3f}"
        else:
            change_type = "refactor"
            subject = f"update {len(changed_files)} file(s)"
        
        scope = "sdlc" if not changed_files else Path(changed_files[0]).parts[0] if changed_files else "sdlc"
        
        message = f"{change_type}({scope}): {subject}\n\n"
        message += f"Changed files: {', '.join(changed_files)}\n"
        message += f"Drift score: {drift_before:.3f} -> {drift_after:.3f}\n"
        message += f"Diffs: {len(diffs)} semantic change(s)\n"
        
        return message
    
    def _compute_diff_summary(self, before: dict, after: dict, changed_files: list[str]) -> dict:
        """Compute diff summary by category."""
        diffs_before = before.get("diffs", [])
        diffs_after = after.get("diffs", [])
        
        summary = {
            "total_files": len(changed_files),
            "total_diffs": len(diffs_after),
            "diffs_by_type": {},
            "drift_delta": after.get("drift_score", 0.0) - before.get("drift_score", 0.0),
            "drift_before": before.get("drift_score", 0.0),
            "drift_after": after.get("drift_score", 0.0),
        }
        
        for diff in diffs_after:
            diff_type = diff.get("diff_type", "unknown")
            summary["diffs_by_type"][diff_type] = summary["diffs_by_type"].get(diff_type, 0) + 1
        
        return summary
    
    def _compute_content_hash(self, changed_files: list[str], diff_summary: dict) -> str:
        """Compute deterministic hash of commit content."""
        content = json.dumps({
            "files": sorted(changed_files),
            "summary": diff_summary
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def save_commit_output(self, output: CommitReadyOutput, path: str) -> None:
        """Save commit output to file for later review."""
        output.save(path)
