"""Deterministic matcher for historical incident retrieval."""

import re
from typing import List, Optional, Set

from app.memory.models import (
    HistoricalIncidentContext,
    HistoricalSearchQuery,
    IncidentMemory,
)


class IncidentMemoryMatcher:
    """Calculates deterministic categorical and lexical similarity scores for historical incidents."""

    def __init__(self, threshold: float = 3.0) -> None:
        self.threshold = threshold

    def _tokenize(self, text: str) -> Set[str]:
        """Extract alphanumeric tokens (length >= 2) from text in lowercase."""
        if not text:
            return set()
        return set(re.findall(r"\b[a-zA-Z0-9_]{2,}\b", text.lower()))

    def _symbols_match(self, candidate: IncidentMemory, query_symbols: List[str]) -> bool:
        """Check if candidate failure location or relevant symbols match any query symbols."""
        if not query_symbols:
            return False

        clean_query_syms = [s.strip().lower() for s in query_symbols if s.strip()]
        if not clean_query_syms:
            return False

        # Check candidate failure_location
        if candidate.failure_location:
            c_loc = candidate.failure_location.strip().lower()
            for q_sym in clean_query_syms:
                if q_sym in c_loc or c_loc in q_sym:
                    return True

        # Check candidate relevant_symbols
        for c_sym in candidate.relevant_symbols:
            c_sym_clean = c_sym.strip().lower()
            for q_sym in clean_query_syms:
                if q_sym == c_sym_clean or q_sym in c_sym_clean or c_sym_clean in q_sym:
                    return True

        return False

    def match(
        self,
        query: HistoricalSearchQuery,
        candidates: List[IncidentMemory],
    ) -> List[HistoricalIncidentContext]:
        """Scores candidate historical memories against query and returns deterministic ranked results."""
        scored_results: List[HistoricalIncidentContext] = []

        query_tokens = self._tokenize(query.query_text)

        for candidate in candidates:
            # 1. Self-exclusion: Never return the incident currently being investigated
            if candidate.incident_id == query.current_incident_id:
                continue

            score = 0.0
            matched_signals: List[str] = []

            # 2. Categorical Scoring
            # Service match (+3.0)
            if (
                query.service
                and candidate.service
                and candidate.service.strip().lower() == query.service.strip().lower()
            ):
                score += 3.0
                matched_signals.append("service_match")

            # Exception type match (+4.0)
            if (
                query.exception_type
                and candidate.exception_type
                and candidate.exception_type.strip().lower() == query.exception_type.strip().lower()
            ):
                score += 4.0
                matched_signals.append("exception_type_match")

            # Endpoint match (+2.0)
            if (
                query.endpoint
                and candidate.endpoint
                and candidate.endpoint.strip().lower() == query.endpoint.strip().lower()
            ):
                score += 2.0
                matched_signals.append("endpoint_match")

            # Failure location / symbol overlap (+5.0)
            if self._symbols_match(candidate, query.relevant_symbols):
                score += 5.0
                matched_signals.append("symbol_match")

            # 3. Deterministic Lexical Overlap (Jaccard * 3.0)
            candidate_text = (
                f"{candidate.title} {candidate.summary} "
                f"{candidate.root_cause_hypothesis} {candidate.triggering_condition}"
            )
            candidate_tokens = self._tokenize(candidate_text)
            if query_tokens and candidate_tokens:
                intersection = len(query_tokens & candidate_tokens)
                union = len(query_tokens | candidate_tokens)
                if union > 0:
                    jaccard = intersection / union
                    lexical_score = round(jaccard * 3.0, 4)
                    if lexical_score > 0:
                        score += lexical_score
                        matched_signals.append(f"lexical_overlap({lexical_score:.2f})")

            # 4. Filter by minimum relevance threshold
            if score >= self.threshold:
                scored_results.append(
                    HistoricalIncidentContext(
                        incident_id=candidate.incident_id,
                        title=candidate.title,
                        service=candidate.service,
                        failure_location=candidate.failure_location,
                        triggering_condition=candidate.triggering_condition,
                        root_cause_hypothesis=candidate.root_cause_hypothesis,
                        similarity_score=round(score, 2),
                        matched_signals=matched_signals,
                        resolution_notes=candidate.resolution_notes,
                    )
                )

        # 5. Deterministic Ranking: score descending, then incident_id ascending
        scored_results.sort(key=lambda item: (-item.similarity_score, item.incident_id))

        # 6. Apply limit
        limit = query.limit if query.limit and query.limit > 0 else 2
        return scored_results[:limit]
