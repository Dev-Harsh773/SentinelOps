"""Pydantic request and response schemas for SentinelOps repository retrieval."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IndexSummaryResponse(BaseModel):
    """Response returned upon index completion."""

    repository: str = Field(..., description="Logical repository name")
    files_discovered: int = Field(..., description="Total files discovered during scanning")
    files_indexed: int = Field(..., description="Total files successfully parsed and indexed")
    files_skipped: int = Field(..., description="Files skipped due to parse or read errors")
    chunks_created: int = Field(..., description="Total semantic code chunks generated")
    indexed_at: datetime = Field(..., description="Timestamp when indexing finished (UTC)")

    model_config = ConfigDict(from_attributes=True)


class IndexStatusResponse(BaseModel):
    """Response returned for repository index status inspection."""

    indexed: bool = Field(..., description="Whether the repository has been indexed")
    files_indexed: int = Field(..., description="Number of distinct source files currently indexed")
    chunks: int = Field(..., description="Number of code chunks currently in memory")
    repository: Optional[str] = Field(None, description="Indexed repository name")
    indexed_at: Optional[datetime] = Field(None, description="Timestamp of last indexing run (UTC)")

    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    """Request payload for lexical source-code search."""

    query: str = Field(..., min_length=1, description="Code or natural language search query")
    limit: int = Field(5, ge=1, le=20, description="Result limit (must be between 1 and 20)")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Query string cannot be empty or whitespace only.")
        return cleaned


class SearchResultItem(BaseModel):
    """Individual code chunk matching a search query."""

    id: str = Field(..., description="Stable deterministic chunk fingerprint")
    file_path: str = Field(..., description="Repository-relative POSIX path")
    symbol_name: Optional[str] = Field(None, description="Symbol name if chunk represents a symbol")
    symbol_type: str = Field(..., description="Symbol type ('class', 'method', 'function', 'module')")
    start_line: int = Field(..., description="1-based start line number in file")
    end_line: int = Field(..., description="1-based end line number in file")
    content: str = Field(..., description="Raw source code content snippet")
    score: float = Field(..., description="Lexical relevance score")

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    """Response container for retrieval search results."""

    query: str = Field(..., description="The queried text")
    total: int = Field(..., description="Count of returned results")
    results: List[SearchResultItem] = Field(..., description="Ranked list of matching code chunks")

    model_config = ConfigDict(from_attributes=True)
