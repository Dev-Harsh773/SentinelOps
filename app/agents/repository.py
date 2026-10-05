"""Repository interface and in-memory persistence for incident investigations."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.agents.models import Investigation


class InvestigationRepository(ABC):
    """Abstract storage interface for incident investigations."""

    @abstractmethod
    def save(self, investigation: Investigation) -> Investigation:
        """Persists an investigation record."""
        pass

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[Investigation]:
        """Retrieves the latest investigation for a given incident ID."""
        pass

    @abstractmethod
    def get_by_id(self, investigation_id: str) -> Optional[Investigation]:
        """Retrieves an investigation by its primary ID."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clears all stored investigations (primarily for test isolation)."""
        pass


class InMemoryInvestigationRepository(InvestigationRepository):
    """In-memory implementation of InvestigationRepository."""

    def __init__(self) -> None:
        self._investigations: Dict[str, Investigation] = {}
        self._by_incident: Dict[str, str] = {}  # incident_id -> investigation_id

    def save(self, investigation: Investigation) -> Investigation:
        self._investigations[investigation.investigation_id] = investigation
        self._by_incident[investigation.incident_id] = investigation.investigation_id
        return investigation

    def get_by_incident_id(self, incident_id: str) -> Optional[Investigation]:
        inv_id = self._by_incident.get(incident_id)
        if not inv_id:
            return None
        return self._investigations.get(inv_id)

    def get_by_id(self, investigation_id: str) -> Optional[Investigation]:
        return self._investigations.get(investigation_id)

    def clear(self) -> None:
        self._investigations.clear()
        self._by_incident.clear()


class SqliteInvestigationRepository(InvestigationRepository):
    """SQLite-backed durable persistence store for incident investigations."""

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
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                runtime_analysis_json TEXT,
                code_query TEXT,
                code_results_json TEXT,
                code_analysis_json TEXT,
                git_context_json TEXT,
                change_analysis_json TEXT,
                historical_context_json TEXT,
                rca_json TEXT,
                validation_json TEXT,
                errors_json TEXT
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_investigations_incident_id ON investigations(incident_id);"
        )
        self._conn.commit()

    def _row_to_investigation(self, row: Any) -> Investigation:
        from dataclasses import asdict
        from datetime import datetime
        import json
        from app.agents.models import (
            ChangeAnalysis,
            CodeAnalysis,
            EvidenceReference,
            HistoricalIncidentContext,
            Investigation,
            InvestigationStatus,
            RCAValidation,
            RootCauseAnalysis,
            RuntimeAnalysis,
        )

        ra = None
        if row["runtime_analysis_json"]:
            d = json.loads(row["runtime_analysis_json"])
            ra = RuntimeAnalysis(
                observed_failures=d.get("observed_failures", []),
                service=d.get("service", ""),
                endpoint=d.get("endpoint"),
                exception_type=d.get("exception_type"),
                important_messages=d.get("important_messages", []),
                request_ids=d.get("request_ids", []),
                timeline=d.get("timeline", []),
                initial_hypotheses=d.get("initial_hypotheses", []),
                missing_information=d.get("missing_information", []),
            )

        ca = None
        if row["code_analysis_json"]:
            d = json.loads(row["code_analysis_json"])
            ca = CodeAnalysis(
                relevant_symbols=d.get("relevant_symbols", []),
                relevant_files=d.get("relevant_files", []),
                code_observations=d.get("code_observations", []),
                possible_relationship_to_failure=d.get("possible_relationship_to_failure", []),
                missing_code_context=d.get("missing_code_context", []),
            )

        cha = None
        if row["change_analysis_json"]:
            d = json.loads(row["change_analysis_json"])
            cha = ChangeAnalysis(
                relevant_changes=d.get("relevant_changes", []),
                potential_relationships=d.get("potential_relationships", []),
                timing_observations=d.get("timing_observations", []),
                contradictions=d.get("contradictions", []),
                uncertainty=d.get("uncertainty", []),
                facts=d.get("facts", []),
                inferences=d.get("inferences", []),
            )

        rca = None
        if row["rca_json"]:
            d = json.loads(row["rca_json"])
            sup_ev = [
                EvidenceReference(type=e["type"], id=e["id"], description=e.get("description"))
                for e in d.get("supporting_evidence", [])
            ]
            con_ev = [
                EvidenceReference(type=e["type"], id=e["id"], description=e.get("description"))
                for e in d.get("contradicting_evidence", [])
            ]
            rca = RootCauseAnalysis(
                failure_location=d.get("failure_location", ""),
                triggering_condition=d.get("triggering_condition", ""),
                root_cause_hypothesis=d.get("root_cause_hypothesis", ""),
                affected_component=d.get("affected_component", ""),
                summary=d.get("summary", ""),
                supporting_evidence=sup_ev,
                contradicting_evidence=con_ev,
                confidence=d.get("confidence", 0.0),
                uncertainties=d.get("uncertainties", []),
            )

        val = None
        if row["validation_json"]:
            d = json.loads(row["validation_json"])
            val = RCAValidation(
                valid=d.get("valid", True),
                issues=d.get("issues", []),
                unsupported_claims=d.get("unsupported_claims", []),
                missing_evidence=d.get("missing_evidence", []),
            )

        hist = []
        if row["historical_context_json"]:
            for h in json.loads(row["historical_context_json"]):
                hist.append(
                    HistoricalIncidentContext(
                        incident_id=h["incident_id"],
                        title=h["title"],
                        service=h["service"],
                        failure_location=h["failure_location"],
                        triggering_condition=h["triggering_condition"],
                        root_cause_hypothesis=h["root_cause_hypothesis"],
                        similarity_score=h["similarity_score"],
                        matched_signals=h.get("matched_signals", []),
                        resolution_notes=h.get("resolution_notes"),
                    )
                )

        return Investigation(
            investigation_id=row["investigation_id"],
            incident_id=row["incident_id"],
            status=InvestigationStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            runtime_analysis=ra,
            code_query=row["code_query"],
            code_results=json.loads(row["code_results_json"]) if row["code_results_json"] else [],
            code_analysis=ca,
            git_context=json.loads(row["git_context_json"]) if row["git_context_json"] else [],
            change_analysis=cha,
            historical_context=hist,
            rca=rca,
            validation=val,
            errors=json.loads(row["errors_json"]) if row["errors_json"] else [],
        )

    def save(self, investigation: Investigation) -> Investigation:
        from dataclasses import asdict
        import json

        ra_json = json.dumps(asdict(investigation.runtime_analysis)) if investigation.runtime_analysis else None
        ca_json = json.dumps(asdict(investigation.code_analysis)) if investigation.code_analysis else None
        cha_json = json.dumps(asdict(investigation.change_analysis)) if investigation.change_analysis else None
        rca_json = json.dumps(asdict(investigation.rca)) if investigation.rca else None
        val_json = json.dumps(asdict(investigation.validation)) if investigation.validation else None
        hist_json = json.dumps([asdict(h) for h in investigation.historical_context]) if investigation.historical_context else None

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO investigations (
                    investigation_id, incident_id, status, created_at, completed_at,
                    runtime_analysis_json, code_query, code_results_json, code_analysis_json,
                    git_context_json, change_analysis_json, historical_context_json,
                    rca_json, validation_json, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(investigation_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    completed_at=excluded.completed_at,
                    runtime_analysis_json=excluded.runtime_analysis_json,
                    code_query=excluded.code_query,
                    code_results_json=excluded.code_results_json,
                    code_analysis_json=excluded.code_analysis_json,
                    git_context_json=excluded.git_context_json,
                    change_analysis_json=excluded.change_analysis_json,
                    historical_context_json=excluded.historical_context_json,
                    rca_json=excluded.rca_json,
                    validation_json=excluded.validation_json,
                    errors_json=excluded.errors_json;
                """,
                (
                    investigation.investigation_id,
                    investigation.incident_id,
                    investigation.status.value if hasattr(investigation.status, "value") else str(investigation.status),
                    investigation.created_at.isoformat(),
                    investigation.completed_at.isoformat() if investigation.completed_at else None,
                    ra_json,
                    investigation.code_query,
                    json.dumps(investigation.code_results) if investigation.code_results else None,
                    ca_json,
                    json.dumps(investigation.git_context) if investigation.git_context else None,
                    cha_json,
                    hist_json,
                    rca_json,
                    val_json,
                    json.dumps(investigation.errors) if investigation.errors else None,
                ),
            )
            self._conn.commit()
            return investigation

    def get_by_incident_id(self, incident_id: str) -> Optional[Investigation]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM investigations WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1;",
                (incident_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_investigation(row)

    def get_by_id(self, investigation_id: str) -> Optional[Investigation]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?;",
                (investigation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_investigation(row)

    def clear(self) -> None:
        """Reset repository storage. Guarded against production DB deletion."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production investigation database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM investigations;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
