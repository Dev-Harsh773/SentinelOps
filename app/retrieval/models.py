"""Domain models for source-code retrieval and indexing in SentinelOps."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Optional


@dataclass(frozen=True)
class CodeChunk:
    """Represents an indexed semantic unit of source code."""

    id: str
    file_path: str  # POSIX-normalized repository-relative path (e.g. demo_app/services/order_service.py)
    symbol_name: Optional[str]
    symbol_type: str  # "class", "method", "function", "module"
    start_line: int
    end_line: int
    content: str

    @classmethod
    def create(
        cls,
        *,
        file_path: str,
        symbol_name: Optional[str],
        symbol_type: str,
        start_line: int,
        end_line: int,
        content: str,
    ) -> "CodeChunk":
        """Factory creating a CodeChunk with a deterministic, reproducible identifier.

        The chunk ID is derived from the stable tuple (file_path, symbol_name, symbol_type, start_line, end_line),
        ensuring unchanged code units retain identical IDs across reindexing runs.
        """
        norm_sym = symbol_name or ""
        identity_str = f"{file_path}|{norm_sym}|{symbol_type}|{start_line}|{end_line}"
        chunk_hash = hashlib.sha256(identity_str.encode("utf-8")).hexdigest()[:16]
        chunk_id = f"chunk-{chunk_hash}"

        return cls(
            id=chunk_id,
            file_path=file_path,
            symbol_name=symbol_name,
            symbol_type=symbol_type,
            start_line=start_line,
            end_line=end_line,
            content=content,
        )


@dataclass(frozen=True)
class IndexStatus:
    """Status metadata for the repository in-memory code index."""

    indexed: bool
    files_indexed: int
    chunks: int
    repository: Optional[str]
    indexed_at: Optional[datetime]
