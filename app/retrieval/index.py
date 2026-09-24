"""In-memory source-code index and lexical retrieval engine for SentinelOps."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
import threading
from typing import Dict, List, Optional, Set

from app.retrieval.models import CodeChunk, IndexStatus

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}

MIN_RELEVANCE_SCORE = 1.0


def tokenize(text: str) -> List[str]:
    """Tokenizes code identifiers and natural language queries into lowercase tokens.

    Splits camelCase, PascalCase, snake_case, path segments, and punctuation.
    """
    if not text:
        return []
    # Split PascalCase / camelCase
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    raw_tokens = re.findall(r"[a-zA-Z0-9]+", s)
    return [t.lower() for t in raw_tokens if t]


@dataclass(frozen=True)
class ScoredChunk:
    """Represents a CodeChunk scored against a search query."""

    chunk: CodeChunk
    score: float


class RepositoryNotIndexedError(Exception):
    """Raised when retrieval search is attempted on an unindexed repository."""

    def __init__(self):
        super().__init__(
            "Repository index is empty or has not been built yet. Call POST /repository/index first."
        )


class CodeIndex:
    """Thread-safe in-memory index of code chunks with lexical search capabilities."""

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: List[CodeChunk] = []
        self._doc_freq: Dict[str, int] = Counter()
        self._repository: Optional[str] = None
        self._indexed_at: Optional[datetime] = None

    def is_indexed(self) -> bool:
        """Returns True if the index contains parsed chunks."""
        with self._lock:
            return self._indexed_at is not None

    def clear(self) -> None:
        """Clears all indexed chunks and metadata (primarily for test isolation)."""
        with self._lock:
            self._chunks = []
            self._doc_freq = Counter()
            self._repository = None
            self._indexed_at = None

    def rebuild(self, repository: str, chunks: List[CodeChunk]) -> None:
        """Atomically replaces the active index with a new collection of chunks and computes document frequencies."""
        now = datetime.now(timezone.utc)
        doc_freq = Counter()
        for chunk in chunks:
            chunk_tokens = set(
                tokenize(chunk.content)
                + (tokenize(chunk.symbol_name) if chunk.symbol_name else [])
                + tokenize(chunk.file_path)
            )
            for t in chunk_tokens:
                doc_freq[t] += 1

        with self._lock:
            self._repository = repository
            self._chunks = list(chunks)
            self._doc_freq = dict(doc_freq)
            self._indexed_at = now

    def get_status(self) -> IndexStatus:
        """Returns current status and metadata of the code index."""
        with self._lock:
            if self._indexed_at is None:
                return IndexStatus(
                    indexed=False,
                    files_indexed=0,
                    chunks=0,
                    repository=None,
                    indexed_at=None,
                )
            distinct_files = {chunk.file_path for chunk in self._chunks}
            return IndexStatus(
                indexed=True,
                files_indexed=len(distinct_files),
                chunks=len(self._chunks),
                repository=self._repository,
                indexed_at=self._indexed_at,
            )

    def search(self, query: str, limit: int = 5) -> List[ScoredChunk]:
        """Searches indexed chunks using hierarchical lexical scoring with IDF and implementation weighting.

        Scoring rules:
        - Exact symbol match (dominant boost for direct symbol lookups)
        - Symbol token match (IDF-weighted and normalized by symbol length to prevent multi-word name inflation)
        - File path token match (IDF-weighted)
        - Implementation content match (TF-IDF weighted, query coverage bonus, subphrase matches, and runtime exception site bonus)
        - Deterministic tie-breaking: (-score, file_path, start_line)
        - Chunks below MIN_RELEVANCE_SCORE are omitted.
        """
        with self._lock:
            if self._indexed_at is None:
                raise RepositoryNotIndexedError()
            chunks_snapshot = list(self._chunks)
            doc_freq_snapshot = dict(self._doc_freq)

        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        raw_q_tokens = tokenize(cleaned_query)
        if not raw_q_tokens:
            return []

        # Filter stopwords unless all tokens are stopwords
        q_tokens = [t for t in raw_q_tokens if t not in STOP_WORDS]
        if not q_tokens:
            q_tokens = raw_q_tokens

        unique_q_tokens: Set[str] = set(q_tokens)
        normalized_full_query = cleaned_query.lower()
        n_total = max(1, len(chunks_snapshot))

        def idf(token: str) -> float:
            df = doc_freq_snapshot.get(token, 0)
            return math.log((n_total + 1.0) / (df + 1.0)) + 1.0

        scored_results: List[ScoredChunk] = []

        for chunk in chunks_snapshot:
            score = 0.0

            # 1. Exact Symbol Matches
            if chunk.symbol_name:
                norm_sym = chunk.symbol_name.lower()
                short_sym = norm_sym.split(".")[-1]
                if norm_sym == normalized_full_query:
                    score += 100.0
                elif short_sym == normalized_full_query:
                    score += 75.0
                else:
                    # Partial symbol token matches (IDF-weighted, normalized by symbol length)
                    sym_tokens = tokenize(chunk.symbol_name)
                    sym_token_set = set(sym_tokens)
                    matched_sym_tokens = unique_q_tokens.intersection(sym_token_set)
                    if matched_sym_tokens:
                        precision = len(matched_sym_tokens) / len(sym_tokens)
                        score += sum(idf(t) for t in matched_sym_tokens) * precision * 2.0

            # 2. File Path Token Matches
            path_tokens = tokenize(chunk.file_path)
            path_token_set = set(path_tokens)
            matched_path_tokens = unique_q_tokens.intersection(path_token_set)
            if matched_path_tokens:
                precision_p = len(matched_path_tokens) / len(path_tokens)
                score += sum(idf(t) for t in matched_path_tokens) * precision_p * 1.5

            # 3. Content Matching (Core driver for implementation and failure search)
            content_tokens = tokenize(chunk.content)
            content_token_set = set(content_tokens)
            matched_content_tokens = unique_q_tokens.intersection(content_token_set)

            if matched_content_tokens:
                # TF-IDF term frequency scoring on content
                content_term_score = 0.0
                for token in matched_content_tokens:
                    tf = 1.0 + math.log(1.0 + content_tokens.count(token))
                    content_term_score += tf * idf(token) * 3.0
                score += content_term_score

                # Query concept coverage in implementation body
                coverage = len(matched_content_tokens) / len(unique_q_tokens)
                score += coverage * 15.0

                # Full phrase or adjacent sub-phrase match in content
                content_lower = chunk.content.lower()
                if len(normalized_full_query) >= 3 and normalized_full_query in content_lower:
                    score += 8.0
                else:
                    for i in range(len(q_tokens) - 1):
                        pair = f"{q_tokens[i]} {q_tokens[i+1]}"
                        if pair in content_lower:
                            score += 4.0

                # Runtime failure/exception site detection:
                # Chunks that raise exceptions sharing concepts with the query (e.g. raise OrderProcessingError)
                raise_matches = re.findall(r"raise\s+([A-Za-z0-9_]+)", chunk.content)
                if raise_matches:
                    for exc_name in raise_matches:
                        exc_tokens = set(tokenize(exc_name))
                        matched_exc = unique_q_tokens.intersection(exc_tokens)
                        if matched_exc:
                            score += 20.0 + len(matched_exc) * 5.0
                        else:
                            score += 5.0

            # Filter by relevance threshold
            if score >= MIN_RELEVANCE_SCORE:
                rounded_score = round(score, 2)
                scored_results.append(ScoredChunk(chunk=chunk, score=rounded_score))

        # Deterministic tie-breaking: score desc, file_path asc, start_line asc
        scored_results.sort(
            key=lambda item: (-item.score, item.chunk.file_path, item.chunk.start_line)
        )

        return scored_results[:limit]
