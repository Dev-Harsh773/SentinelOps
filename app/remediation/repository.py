"""Remediation repository abstractions and in-memory implementation."""

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.remediation.models import RemediationProposal


class RemediationRepository(ABC):
    """Abstract interface for storing and querying remediation proposals."""

    @abstractmethod
    def save(self, proposal: RemediationProposal) -> RemediationProposal:
        """Persist or update a remediation proposal."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationProposal]:
        """Retrieve the active remediation proposal for an incident."""
        ...

    @abstractmethod
    def get_by_id(self, remediation_id: str) -> Optional[RemediationProposal]:
        """Retrieve a remediation proposal by its unique ID."""
        ...

    @abstractmethod
    def list_all(self) -> List[RemediationProposal]:
        """List all stored remediation proposals."""
        ...

    @abstractmethod
    def list_for_incident(self, incident_id: str) -> List[RemediationProposal]:
        """List all proposals (including historical) for an incident, newest first."""
        ...

    @abstractmethod
    def delete_by_incident_id(self, incident_id: str) -> bool:
        """Delete remediation proposal for an incident if present."""
        ...


class InMemoryRemediationRepository(RemediationRepository):
    """Thread-safe in-memory implementation maintaining single active proposal per incident."""

    def __init__(self) -> None:
        self._storage: Dict[str, RemediationProposal] = {}
        self._incident_index: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, proposal: RemediationProposal) -> RemediationProposal:
        with self._lock:
            self._storage[proposal.remediation_id] = proposal
            self._incident_index[proposal.incident_id] = proposal.remediation_id
            return proposal

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            rem_id = self._incident_index.get(incident_id)
            if not rem_id:
                return None
            return self._storage.get(rem_id)

    def get_by_id(self, remediation_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            return self._storage.get(remediation_id)

    def list_all(self) -> List[RemediationProposal]:
        with self._lock:
            return list(self._storage.values())

    def list_for_incident(self, incident_id: str) -> List[RemediationProposal]:
        with self._lock:
            proposals = [p for p in self._storage.values() if p.incident_id == incident_id]
            return sorted(proposals, key=lambda p: p.created_at, reverse=True)

    def delete_by_incident_id(self, incident_id: str) -> bool:
        with self._lock:
            rem_id = self._incident_index.pop(incident_id, None)
            if rem_id:
                self._storage.pop(rem_id, None)
                return True
            return False

    def clear(self) -> None:
        """Clear all stored proposals (used in test isolation)."""
        with self._lock:
            self._storage.clear()
            self._incident_index.clear()


class SqliteRemediationRepository(RemediationRepository):
    """SQLite-backed durable storage for remediation proposals."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        import os
        from pathlib import Path
        import sqlite3
        import threading

        self._db_path = str(Path(db_path).resolve()) if db_path != ":memory:" else ":memory:"
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema()

    def _init_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_proposals (
                remediation_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                target_files_json TEXT NOT NULL,
                target_symbols_json TEXT NOT NULL,
                proposed_changes_json TEXT NOT NULL,
                rationale TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                validation_steps_json TEXT NOT NULL,
                evidence_references_json TEXT NOT NULL,
                validation_json TEXT,
                assumptions_json TEXT,
                advisory_historical_context_json TEXT,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediations_incident_id ON remediation_proposals(incident_id);"
        )
        self._conn.commit()

    def _row_to_proposal(self, row: Any) -> RemediationProposal:
        from dataclasses import asdict
        from datetime import datetime
        import json
        from app.agents.models import EvidenceReference
        from app.remediation.models import (
            ChangeType,
            ProposedChange,
            RemediationProposal,
            RemediationStatus,
            RemediationValidation,
        )

        p_changes = []
        if row["proposed_changes_json"]:
            for c in json.loads(row["proposed_changes_json"]):
                p_changes.append(
                    ProposedChange(
                        file_path=c["file_path"],
                        change_type=ChangeType(c["change_type"]),
                        description=c["description"],
                        reason=c["reason"],
                        symbol=c.get("symbol"),
                    )
                )

        ev_refs = []
        if row["evidence_references_json"]:
            for e in json.loads(row["evidence_references_json"]):
                ev_refs.append(
                    EvidenceReference(
                        type=e["type"],
                        id=e["id"],
                        description=e.get("description"),
                    )
                )

        val = None
        if row["validation_json"]:
            vd = json.loads(row["validation_json"])
            val = RemediationValidation(
                valid=vd.get("valid", True),
                issues=vd.get("issues", []),
                unsupported_files=vd.get("unsupported_files", []),
                unsupported_symbols=vd.get("unsupported_symbols", []),
                missing_elements=vd.get("missing_elements", []),
            )

        return RemediationProposal(
            remediation_id=row["remediation_id"],
            incident_id=row["incident_id"],
            investigation_id=row["investigation_id"],
            status=RemediationStatus(row["status"]),
            summary=row["summary"],
            target_files=json.loads(row["target_files_json"]) if row["target_files_json"] else [],
            target_symbols=json.loads(row["target_symbols_json"]) if row["target_symbols_json"] else [],
            proposed_changes=p_changes,
            rationale=row["rationale"],
            risks=json.loads(row["risks_json"]) if row["risks_json"] else [],
            validation_steps=json.loads(row["validation_steps_json"]) if row["validation_steps_json"] else [],
            evidence_references=ev_refs,
            validation=val,
            assumptions=json.loads(row["assumptions_json"]) if row["assumptions_json"] else [],
            advisory_historical_context=json.loads(row["advisory_historical_context_json"]) if row["advisory_historical_context_json"] else [],
            confidence=float(row["confidence"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save(self, proposal: RemediationProposal) -> RemediationProposal:
        from dataclasses import asdict
        import json

        changes_data = [
            {
                "file_path": c.file_path,
                "change_type": c.change_type.value if hasattr(c.change_type, "value") else str(c.change_type),
                "description": c.description,
                "reason": c.reason,
                "symbol": c.symbol,
            }
            for c in proposal.proposed_changes
        ]
        ev_data = [
            {"type": e.type, "id": e.id, "description": e.description}
            for e in proposal.evidence_references
        ]
        val_json = json.dumps(asdict(proposal.validation)) if proposal.validation else None

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO remediation_proposals (
                    remediation_id, incident_id, investigation_id, status, summary,
                    target_files_json, target_symbols_json, proposed_changes_json,
                    rationale, risks_json, validation_steps_json, evidence_references_json,
                    validation_json, assumptions_json, advisory_historical_context_json,
                    confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(remediation_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    investigation_id=excluded.investigation_id,
                    status=excluded.status,
                    summary=excluded.summary,
                    target_files_json=excluded.target_files_json,
                    target_symbols_json=excluded.target_symbols_json,
                    proposed_changes_json=excluded.proposed_changes_json,
                    rationale=excluded.rationale,
                    risks_json=excluded.risks_json,
                    validation_steps_json=excluded.validation_steps_json,
                    evidence_references_json=excluded.evidence_references_json,
                    validation_json=excluded.validation_json,
                    assumptions_json=excluded.assumptions_json,
                    advisory_historical_context_json=excluded.advisory_historical_context_json,
                    confidence=excluded.confidence,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at;
                """,
                (
                    proposal.remediation_id,
                    proposal.incident_id,
                    proposal.investigation_id,
                    proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status),
                    proposal.summary,
                    json.dumps(proposal.target_files),
                    json.dumps(proposal.target_symbols),
                    json.dumps(changes_data),
                    proposal.rationale,
                    json.dumps(proposal.risks),
                    json.dumps(proposal.validation_steps),
                    json.dumps(ev_data),
                    val_json,
                    json.dumps(proposal.assumptions),
                    json.dumps(proposal.advisory_historical_context),
                    proposal.confidence,
                    proposal.created_at.isoformat(),
                    proposal.updated_at.isoformat(),
                ),
            )
            self._conn.commit()
            return proposal

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_proposals WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1;",
                (incident_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_proposal(row)

    def get_by_id(self, remediation_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_proposals WHERE remediation_id = ?;",
                (remediation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_proposal(row)

    def list_all(self) -> List[RemediationProposal]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM remediation_proposals ORDER BY created_at DESC;")
            return [self._row_to_proposal(r) for r in cursor.fetchall()]

    def list_for_incident(self, incident_id: str) -> List[RemediationProposal]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_proposals WHERE incident_id = ? ORDER BY created_at DESC;",
                (incident_id,),
            )
            return [self._row_to_proposal(r) for r in cursor.fetchall()]

    def delete_by_incident_id(self, incident_id: str) -> bool:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM remediation_proposals WHERE incident_id = ?;", (incident_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def clear(self) -> None:
        """Clear all stored proposals (used in test isolation)."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production remediation database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM remediation_proposals;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
