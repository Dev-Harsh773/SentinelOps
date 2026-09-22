"""Automated tests for Stage 4 repository scanning, parsing, indexing, and retrieval."""

from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retrieval.dependencies import _shared_code_index
from app.retrieval.index import CodeIndex, RepositoryNotIndexedError, tokenize
from app.retrieval.parser import ParseError, PythonAstParser
from app.retrieval.scanner import RepositoryNotFoundError, SourceScanner
from app.retrieval.service import RetrievalService

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_in_memory_index():
    """Reset the shared in-memory code index before and after tests."""
    with _shared_code_index._lock:
        _shared_code_index._chunks = []
        _shared_code_index._repository = None
        _shared_code_index._indexed_at = None
    yield
    with _shared_code_index._lock:
        _shared_code_index._chunks = []
        _shared_code_index._repository = None
        _shared_code_index._indexed_at = None


# =====================================================================
# Unit Tests: Scanner
# =====================================================================


def test_scanner_discovers_python_files_and_ignores_excluded():
    """Scanner should find all Python files in demo_app and exclude runtime, tests, etc."""
    scanner = SourceScanner()
    discovered = scanner.scan("demo_app")

    assert len(discovered) > 0
    rel_paths = [rel for rel, _ in discovered]

    # Deterministic sorting check
    assert rel_paths == sorted(rel_paths)

    # Path normalization check: POSIX format, starts with demo_app/
    for rel in rel_paths:
        assert "\\" not in rel
        assert rel.startswith("demo_app/")
        assert rel.endswith(".py")
        assert not any(excluded in rel.split("/") for excluded in ["tests", "runtime", ".git", "__pycache__"])

    # Core files must be present
    assert "demo_app/main.py" in rel_paths
    assert "demo_app/services/order_service.py" in rel_paths
    assert "demo_app/api/orders.py" in rel_paths


def test_scanner_raises_on_nonexistent_repo():
    """Scanner must raise RepositoryNotFoundError when directory does not exist."""
    scanner = SourceScanner()
    with pytest.raises(RepositoryNotFoundError):
        scanner.scan("nonexistent_directory_xyz_123")


# =====================================================================
# Unit Tests: Parser & AST Chunker
# =====================================================================


def test_parser_extracts_clean_chunks_with_decorators_and_no_duplication():
    """Parser must preserve decorators on functions and avoid duplicating methods inside class chunks."""
    parser = PythonAstParser()
    order_service_path = Path("demo_app/services/order_service.py")
    chunks = parser.parse_file("demo_app/services/order_service.py", order_service_path)

    assert len(chunks) >= 4

    # Check class chunk for OrderService
    class_chunks = [c for c in chunks if c.symbol_type == "class" and c.symbol_name == "OrderService"]
    assert len(class_chunks) == 1
    cls_chunk = class_chunks[0]
    assert "class OrderService:" in cls_chunk.content
    # Crucial: Class chunk must NOT include create_order method implementation
    assert "def create_order" not in cls_chunk.content

    # Check method chunk for OrderService.create_order
    method_chunks = [c for c in chunks if c.symbol_type == "method" and c.symbol_name == "OrderService.create_order"]
    assert len(method_chunks) == 1
    m_chunk = method_chunks[0]
    assert "def create_order(self, request: OrderCreateRequest)" in m_chunk.content
    assert "raise OrderProcessingError" in m_chunk.content

    # Check function with decorator from demo_app/api/orders.py
    orders_api_path = Path("demo_app/api/orders.py")
    api_chunks = parser.parse_file("demo_app/api/orders.py", orders_api_path)
    fn_chunks = [c for c in api_chunks if c.symbol_type == "function" and c.symbol_name == "create_order"]
    assert len(fn_chunks) == 1
    fn_chunk = fn_chunks[0]
    # Decorator must be preserved and start line must be on the decorator
    assert "@router.post(" in fn_chunk.content
    assert fn_chunk.start_line == 13


def test_parser_deterministic_chunk_ids():
    """Same file parsed twice must generate identical chunk IDs."""
    parser = PythonAstParser()
    path = Path("demo_app/services/order_service.py")

    chunks1 = parser.parse_file("demo_app/services/order_service.py", path)
    chunks2 = parser.parse_file("demo_app/services/order_service.py", path)

    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.id == c2.id
        assert c1.id.startswith("chunk-")
        assert c1.file_path == c2.file_path
        assert c1.start_line == c2.start_line
        assert c1.end_line == c2.end_line


def test_parser_raises_parse_error_on_syntax_error():
    """Parser must raise ParseError when encountering broken Python syntax."""
    parser = PythonAstParser()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as tmp:
        tmp.write("def broken_func(:\n    pass\n")
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(ParseError) as exc_info:
            parser.parse_file("broken.py", tmp_path)
        assert "broken.py" in str(exc_info.value)
    finally:
        tmp_path.unlink(missing_ok=True)


# =====================================================================
# Unit Tests: Tokenizer & Index
# =====================================================================


def test_tokenizer_splits_camelcase_and_snake_case():
    """Tokenizer should split snake_case, PascalCase, camelCase, paths, and punctuation."""
    tokens = tokenize("OrderProcessingError in demo_app/services/order_service.py")
    assert "order" in tokens
    assert "processing" in tokens
    assert "error" in tokens
    assert "services" in tokens
    assert "service" in tokens


def test_relevance_threshold_filters_nonsense_queries():
    """Nonsense query must yield empty search results."""
    scanner = SourceScanner()
    parser = PythonAstParser()
    index = CodeIndex()
    service = RetrievalService(index=index, scanner=scanner, parser=parser)
    service.index_repository("demo_app")

    resp = service.search("quantum banana spaceship")
    assert resp.total == 0
    assert len(resp.results) == 0


def test_parse_error_resilience_skips_malformed_file():
    """Service must skip malformed files, increment files_skipped, and index valid ones."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        # Create a valid file
        valid_file = repo_dir / "valid.py"
        valid_file.write_text("def valid_function():\n    return 42\n", encoding="utf-8")
        # Create an invalid file
        invalid_file = repo_dir / "invalid.py"
        invalid_file.write_text("def invalid_syntax(:\n", encoding="utf-8")

        index = CodeIndex()
        service = RetrievalService(index=index)
        summary = service.index_repository(str(repo_dir))

        assert summary.files_discovered == 2
        assert summary.files_indexed == 1
        assert summary.files_skipped == 1
        assert summary.chunks_created >= 1

        status = service.get_status()
        assert status.indexed is True
        assert status.files_indexed == 1


# =====================================================================
# API Integration Tests
# =====================================================================


def test_status_endpoint_before_indexing():
    """GET /repository/status before indexing should report indexed=false."""
    response = client.get("/repository/status")
    assert response.status_code == 200
    data = response.json()
    assert data["indexed"] is False
    assert data["files_indexed"] == 0
    assert data["chunks"] == 0
    assert data["repository"] is None
    assert data["indexed_at"] is None


def test_search_endpoint_before_indexing_returns_409():
    """POST /repository/search before indexing must return HTTP 409 Conflict."""
    response = client.post("/repository/search", json={"query": "order processing"})
    assert response.status_code == 409
    assert "not been built yet" in response.json()["detail"].lower()


def test_index_repository_endpoint():
    """POST /repository/index builds the index and returns summary."""
    response = client.post("/repository/index")
    assert response.status_code == 200
    data = response.json()
    assert data["repository"] == "demo_app"
    assert data["files_discovered"] >= 10
    assert data["files_indexed"] == data["files_discovered"]
    assert data["files_skipped"] == 0
    assert data["chunks_created"] > 20
    assert data["indexed_at"] is not None

    # Verify status now reports indexed
    status_resp = client.get("/repository/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["indexed"] is True
    assert status_data["files_indexed"] == data["files_indexed"]
    assert status_data["chunks"] == data["chunks_created"]
    assert status_data["repository"] == "demo_app"


def test_search_repository_order_processing_failure():
    """POST /repository/search for 'order processing failure' prioritizes execution path above admin toggles."""
    # Index repository first
    client.post("/repository/index")

    response = client.post("/repository/search", json={"query": "order processing failure", "limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "order processing failure"
    assert data["total"] > 0
    assert len(data["results"]) <= 5

    # Check top result: must be OrderService.create_order
    top_chunk = data["results"][0]
    assert top_chunk["id"].startswith("chunk-")
    assert top_chunk["score"] > 0.0
    assert "\\" not in top_chunk["file_path"]
    assert top_chunk["symbol_name"] == "OrderService.create_order"
    assert "order_service.py" in top_chunk["file_path"]

    # Verify that OrderService.create_order ranks above administrative toggle functions
    symbols_in_order = [r["symbol_name"] for r in data["results"]]
    assert "OrderService.create_order" in symbols_in_order
    admin_indices = [
        idx for idx, sym in enumerate(symbols_in_order)
        if sym in ["enable_order_processing_failure", "disable_order_processing_failure"]
    ]
    if admin_indices:
        order_idx = symbols_in_order.index("OrderService.create_order")
        assert order_idx < min(admin_indices)


def test_retrieval_quality_execution_path_ranks_above_admin_controls():
    """Isolated test repo: business method raising OrderProcessingError ranks above admin control functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        # 1. Administrative control file with query tokens in symbol names
        admin_code = (
            "def enable_order_processing_failure():\n"
            "    '''Enable order processing failure toggle.'''\n"
            "    return {'enabled': True}\n\n"
            "def disable_order_processing_failure():\n"
            "    '''Disable order processing failure toggle.'''\n"
            "    return {'enabled': False}\n"
        )
        (repo_dir / "admin.py").write_text(admin_code, encoding="utf-8")

        # 2. Business service executing orders and raising the failure exception
        service_code = (
            "class OrderProcessingError(Exception):\n"
            "    pass\n\n"
            "class OrderService:\n"
            "    def process_order(self, order_id: str):\n"
            "        '''Perform order checkout and processing.'''\n"
            "        if True:\n"
            "            raise OrderProcessingError('Payment gateway failure during order processing')\n"
            "        return {'status': 'completed'}\n"
        )
        (repo_dir / "order_service.py").write_text(service_code, encoding="utf-8")

        index = CodeIndex()
        service = RetrievalService(index=index)
        service.index_repository(str(repo_dir))

        search_resp = service.search("order processing failure", limit=5)
        assert search_resp.total >= 2

        results = search_resp.results
        top_match = results[0]

        # The actual execution path method must rank first
        assert top_match.symbol_name == "OrderService.process_order"
        assert "order_service.py" in top_match.file_path

        # Admin functions must rank below the execution path method
        admin_ranks = [i for i, r in enumerate(results) if "admin.py" in r.file_path]
        if admin_ranks:
            assert 0 < min(admin_ranks)


def test_search_repository_exact_symbol():
    """POST /repository/search for exact symbol boosts it to top."""
    client.post("/repository/index")

    response = client.post("/repository/search", json={"query": "OrderService.create_order", "limit": 3})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    top = data["results"][0]
    assert top["symbol_name"] == "OrderService.create_order"
    assert top["symbol_type"] == "method"
    assert top["file_path"] == "demo_app/services/order_service.py"
    assert top["score"] >= 40.0


def test_search_query_validation():
    """Empty or whitespace-only query must fail validation with 422."""
    client.post("/repository/index")

    # Empty string
    resp1 = client.post("/repository/search", json={"query": ""})
    assert resp1.status_code == 422

    # Whitespace only
    resp2 = client.post("/repository/search", json={"query": "   "})
    assert resp2.status_code == 422

    # Limit too high
    resp3 = client.post("/repository/search", json={"query": "order", "limit": 50})
    assert resp3.status_code == 422

    # Limit too low
    resp4 = client.post("/repository/search", json={"query": "order", "limit": 0})
    assert resp4.status_code == 422


def test_reindexing_atomicity_and_deterministic_ids():
    """Reindexing twice replaces the collection without doubling chunk count, keeping identical IDs."""
    r1 = client.post("/repository/index").json()
    chunks_first = r1["chunks_created"]

    # Search top result to capture its ID
    s1 = client.post("/repository/search", json={"query": "OrderService.create_order", "limit": 1}).json()
    id_first = s1["results"][0]["id"]

    # Reindex
    r2 = client.post("/repository/index").json()
    chunks_second = r2["chunks_created"]

    # Chunk count should match exactly, not double
    assert chunks_second == chunks_first

    # Search top result again
    s2 = client.post("/repository/search", json={"query": "OrderService.create_order", "limit": 1}).json()
    id_second = s2["results"][0]["id"]

    # Chunk ID must be identical (deterministic)
    assert id_second == id_first
