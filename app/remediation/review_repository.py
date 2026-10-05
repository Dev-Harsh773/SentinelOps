"""Remediation review repository abstractions and in-memory implementation."""

from abc import ABC, abstractmethod
import threading
from typing import Any, Dict, List, Optional

from app.remediation.models import RemediationReview


class RemediationReviewRepository(ABC):
    """Abstract interface for persisting and querying human review audit records."""

    @abstractmethod
    def save(self, review: RemediationReview) -> RemediationReview:
        """Persist a review audit record."""
        ...

    @abstractmethod
    def get_by_id(self, review_id: str) -> Optional[RemediationReview]:
        """Retrieve a review by its unique ID."""
        ...

    @abstractmethod
    def list_for_incident(self, incident_id: str) -> List[RemediationReview]:
        """List all review records for an incident in descending chronological order."""
        ...

    @abstractmethod
    def get_latest_for_incident(self, incident_id: str) -> Optional[RemediationReview]:
        """Retrieve the most recent review record for an incident."""
        ...

    @abstractmethod
    def get_latest_for_remediation(self, remediation_id: str) -> Optional[RemediationReview]:
        """Retrieve the most recent review record for a specific remediation proposal."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored reviews (used in test isolation)."""
        ...


class InMemoryRemediationReviewRepository(RemediationReviewRepository):
    """Thread-safe in-memory implementation maintaining an append-only review audit log."""

    def __init__(self) -> None:
        self._reviews: Dict[str, RemediationReview] = {}
        self._incident_reviews: Dict[str, List[str]] = {}
        self._remediation_reviews: Dict[str, List[str]] = {}
        self._lock = threading.Lock()

    def save(self, review: RemediationReview) -> RemediationReview:
        with self._lock:
            self._reviews[review.review_id] = review

            if review.incident_id not in self._incident_reviews:
                self._incident_reviews[review.incident_id] = []
            self._incident_reviews[review.incident_id].append(review.review_id)

            if review.remediation_id not in self._remediation_reviews:
                self._remediation_reviews[review.remediation_id] = []
            self._remediation_reviews[review.remediation_id].append(review.review_id)

            return review

    def get_by_id(self, review_id: str) -> Optional[RemediationReview]:
        with self._lock:
            return self._reviews.get(review_id)

    def list_for_incident(self, incident_id: str) -> List[RemediationReview]:
        with self._lock:
            rev_ids = self._incident_reviews.get(incident_id, [])
            records = [self._reviews[r_id] for r_id in rev_ids if r_id in self._reviews]
            # Sort newest first
            return sorted(records, key=lambda r: r.created_at, reverse=True)

    def get_latest_for_incident(self, incident_id: str) -> Optional[RemediationReview]:
        records = self.list_for_incident(incident_id)
        return records[0] if records else None

    def get_latest_for_remediation(self, remediation_id: str) -> Optional[RemediationReview]:
        with self._lock:
            rev_ids = self._remediation_reviews.get(remediation_id, [])
            records = [self._reviews[r_id] for r_id in rev_ids if r_id in self._reviews]
            if not records:
                return None
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records[0]

    def clear(self) -> None:
        with self._lock:
            self._reviews.clear()
            self._incident_reviews.clear()
            self._remediation_reviews.clear()


class SqliteRemediationReviewRepository(RemediationReviewRepository):
    """SQLite-backed append-only storage for human remediation reviews."""

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
            CREATE TABLE IF NOT EXISTS remediation_reviews (
                review_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                remediation_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_reviews_incident_id ON remediation_reviews(incident_id);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_reviews_rem_id ON remediation_reviews(remediation_id);"
        )
        self._conn.commit()

    def _row_to_review(self, row: Any) -> RemediationReview:
        from datetime import datetime
        from app.remediation.models import RemediationReview, ReviewDecision

        return RemediationReview(
            review_id=row["review_id"],
            incident_id=row["incident_id"],
            remediation_id=row["remediation_id"],
            investigation_id=row["investigation_id"],
            decision=ReviewDecision(row["decision"]),
            reviewer=row["reviewer"],
            comment=row["comment"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save(self, review: RemediationReview) -> RemediationReview:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO remediation_reviews (
                    review_id, incident_id, remediation_id, investigation_id,
                    decision, reviewer, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    remediation_id=excluded.remediation_id,
                    investigation_id=excluded.investigation_id,
                    decision=excluded.decision,
                    reviewer=excluded.reviewer,
                    comment=excluded.comment,
                    created_at=excluded.created_at;
                """,
                (
                    review.review_id,
                    review.incident_id,
                    review.remediation_id,
                    review.investigation_id,
                    review.decision.value if hasattr(review.decision, "value") else str(review.decision),
                    review.reviewer,
                    review.comment,
                    review.created_at.isoformat(),
                ),
            )
            self._conn.commit()
            return review

    def get_by_id(self, review_id: str) -> Optional[RemediationReview]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_reviews WHERE review_id = ?;",
                (review_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_review(row)

    def list_for_incident(self, incident_id: str) -> List[RemediationReview]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_reviews WHERE incident_id = ? ORDER BY created_at DESC;",
                (incident_id,),
            )
            return [self._row_to_review(r) for r in cursor.fetchall()]

    def get_latest_for_incident(self, incident_id: str) -> Optional[RemediationReview]:
        records = self.list_for_incident(incident_id)
        return records[0] if records else None

    def get_latest_for_remediation(self, remediation_id: str) -> Optional[RemediationReview]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_reviews WHERE remediation_id = ? ORDER BY created_at DESC LIMIT 1;",
                (remediation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_review(row)

    def clear(self) -> None:
        """Clear all stored reviews (used in test isolation)."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production remediation review database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM remediation_reviews;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
