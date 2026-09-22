"""Domain service orchestrating repository scanning, parsing, indexing, and search."""

import logging
from pathlib import Path
from typing import Optional

from app.retrieval.index import CodeIndex, RepositoryNotIndexedError
from app.retrieval.models import IndexStatus
from app.retrieval.parser import ParseError, PythonAstParser
from app.retrieval.scanner import RepositoryNotFoundError, SourceScanner
from app.retrieval.schemas import (
    IndexSummaryResponse,
    SearchResponse,
    SearchResultItem,
)

logger = logging.getLogger(__name__)


class RetrievalService:
    """Coordinates repository scanning, AST parsing, and in-memory lexical code retrieval.

    Pure domain service with zero HTTP or framework-level dependencies.
    """

    def __init__(
        self,
        index: CodeIndex,
        scanner: Optional[SourceScanner] = None,
        parser: Optional[PythonAstParser] = None,
        default_repo_path: str = "demo_app",
    ) -> None:
        self._index = index
        self._scanner = scanner or SourceScanner()
        self._parser = parser or PythonAstParser()
        self._default_repo_path = default_repo_path

    def index_repository(self, repository_path: Optional[str] = None) -> IndexSummaryResponse:
        """Discovers, parses, and atomically indexes Python files in the given repository.

        Args:
            repository_path: Local filesystem path to repository. Defaults to configured path.

        Returns:
            IndexSummaryResponse detailing discovered, indexed, and skipped files.

        Raises:
            RepositoryNotFoundError: If repository_path does not exist on disk.
        """
        target_path = repository_path or self._default_repo_path
        discovered_files = self._scanner.scan(target_path)

        all_chunks = []
        files_indexed = 0
        files_skipped = 0

        for rel_posix_path, abs_path in discovered_files:
            try:
                chunks = self._parser.parse_file(rel_posix_path, abs_path)
                all_chunks.extend(chunks)
                files_indexed += 1
            except ParseError as exc:
                logger.warning("Skipping unparseable source file '%s': %s", rel_posix_path, exc)
                files_skipped += 1

        repo_name = Path(target_path).name
        self._index.rebuild(repository=repo_name, chunks=all_chunks)
        status = self._index.get_status()

        return IndexSummaryResponse(
            repository=repo_name,
            files_discovered=len(discovered_files),
            files_indexed=files_indexed,
            files_skipped=files_skipped,
            chunks_created=len(all_chunks),
            indexed_at=status.indexed_at,
        )

    def get_status(self) -> IndexStatus:
        """Returns the current state and metadata of the repository index."""
        return self._index.get_status()

    def search(self, query: str, limit: int = 5) -> SearchResponse:
        """Searches indexed source code chunks using lexical scoring.

        Args:
            query: The query text.
            limit: Maximum chunks to return (1-20).

        Returns:
            SearchResponse containing matching scored code chunks.

        Raises:
            RepositoryNotIndexedError: If search is attempted before indexing.
        """
        scored_chunks = self._index.search(query=query, limit=limit)
        results = [
            SearchResultItem(
                id=sc.chunk.id,
                file_path=sc.chunk.file_path,
                symbol_name=sc.chunk.symbol_name,
                symbol_type=sc.chunk.symbol_type,
                start_line=sc.chunk.start_line,
                end_line=sc.chunk.end_line,
                content=sc.chunk.content,
                score=sc.score,
            )
            for sc in scored_chunks
        ]
        return SearchResponse(
            query=query,
            total=len(results),
            results=results,
        )
