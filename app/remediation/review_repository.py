"""Remediation review repository abstractions and in-memory implementation."""

from abc import ABC, abstractmethod
import threading
from typing import Dict, List, Optional

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
