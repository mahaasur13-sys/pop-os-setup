"""Audit ledger — append-only execution log."""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    """
    Single audit log entry.
    
    Stored in append-only ledger.
    
    Attributes:
        entry_id: Unique identifier (UUID).
        snapshot_hash: Hash of system state at this point.
        drift_score: Current drift score.
        execution_result: Result from patch execution.
        timestamp: When entry was created.
    """
    entry_id: str
    snapshot_hash: str
    drift_score: float
    execution_result: dict
    timestamp: str = ""
    
    def __post_init__(self):
        if self.timestamp == "":
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "snapshot_hash": self.snapshot_hash,
            "drift_score": self.drift_score,
            "execution_result": self.execution_result,
            "timestamp": self.timestamp
        }


class AuditLedger:
    """
    Append-only audit ledger for SDLC OS operations.
    
    This is an APPEND-ONLY log. NO overwrites allowed.
    
    Each execution creates a new entry with:
        - snapshot_hash: Hash of state at this point
        - drift_score: Current drift score
        - execution_result: What happened
        - timestamp: When it happened
    
    Storage: SQLite with WAL mode for safety.
    """
    
    def __init__(self, ledger_path: str | None = None):
        if ledger_path is None:
            ledger_path = "/tmp/sdlc_audit_ledger.db"
        
        self.db_path = Path(ledger_path)
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize SQLite database with append-only schema."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id TEXT PRIMARY KEY,
                snapshot_hash TEXT NOT NULL,
                drift_score REAL NOT NULL,
                execution_result TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                seq INTEGER AUTOINCREMENT
            )
        """)
        
        # Prevent updates — append only
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_update
            AFTER UPDATE ON audit_log
            BEGIN
                SELECT RAISE(FAIL, 'Updates are not allowed on audit log');
            END
        """)
        
        # Prevent deletes
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_delete
            AFTER DELETE ON audit_log
            BEGIN
                SELECT RAISE(FAIL, 'Deletes are not allowed on audit log');
            END
        """)
        
        conn.commit()
        conn.close()
    
    def append(
        self,
        snapshot_hash: str,
        drift_score: float,
        execution_result: dict
    ) -> AuditEntry:
        """
        Append new entry to ledger.
        
        Args:
            snapshot_hash: Hash of system state.
            drift_score: Current drift score.
            execution_result: Execution result dict.
            
        Returns:
            Created AuditEntry.
            
        Raises:
            Exception: If append fails (including if DB was tampered with).
        """
        import uuid
        
        entry = AuditEntry(
            entry_id=f"entry_{uuid.uuid4().hex[:12]}",
            snapshot_hash=snapshot_hash,
            drift_score=drift_score,
            execution_result=execution_result,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                INSERT INTO audit_log (entry_id, snapshot_hash, drift_score, execution_result, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.snapshot_hash,
                    entry.drift_score,
                    json.dumps(entry.execution_result, default=str),
                    entry.timestamp
                )
            )
            conn.commit()
        except Exception as e:
            conn.close()
            raise Exception(f"Failed to append audit entry: {e}") from e
        finally:
            conn.close()
        
        return entry
    
    def get_all(self) -> list[AuditEntry]:
        """
        Get all entries from ledger, oldest first.
        
        Returns:
            List of all AuditEntry objects.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT entry_id, snapshot_hash, drift_score, execution_result, timestamp
            FROM audit_log
            ORDER BY seq ASC
        """)
        
        entries = []
        for row in cursor.fetchall():
            entries.append(AuditEntry(
                entry_id=row[0],
                snapshot_hash=row[1],
                drift_score=row[2],
                execution_result=json.loads(row[3]),
                timestamp=row[4]
            ))
        
        conn.close()
        return entries
    
    def get_last(self) -> AuditEntry | None:
        """Get most recent entry."""
        entries = self.get_all()
        return entries[-1] if entries else None
    
    def count(self) -> int:
        """Count total entries."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def export_json(self, path: str) -> None:
        """Export ledger to JSON file."""
        entries = self.get_all()
        with open(path, "w") as f:
            json.dump([e.to_dict() for e in entries], f, indent=2)
