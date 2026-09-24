"""Tests for Stage 7 Incident Memory and Historical RAG."""

import datetime
from unittest.mock import MagicMock
import uuid
import pytest
from fastapi.testclient import TestClient

from app.agents.dependencies import (
    get_investigation_repository,
)
from app.agents.models import (
    CodeAnalysis,
    EvidenceReference,
    Investigation,
    InvestigationStatus,
    RCAValidation,
    RootCauseAnalysis,
    RuntimeAnalysis,
)
from app.incidents.dependencies import get_incident_repository
from app.incidents.models import Incident, IncidentStatus, Severity
from app.main import app
from app.memory.dependencies import (
    get_memory_repository,
    get_memory_service,
    reset_memory_repository,
)
from app.memory.matcher import IncidentMemoryMatcher
from app.memory.models import (
    HistoricalIncidentContext,
    HistoricalSearchQuery,
    IncidentMemory,
)
from app.memory.repository import (
    InMemoryIncidentMemoryRepository,
)
from app.memory.service import IncidentMemoryService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import Evidence, EvidenceType


# =====================================================================
# Fixtures & Helpers
# =====================================================================


@pytest.fixture(autouse=True)
def clean_repositories():
    """Ensure in-memory repositories are cleared before and after each test."""
    reset_memory_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()
    yield
    reset_memory_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()


@pytest.fixture
def client() -> TestClient:
    """Provides a TestClient instance."""
    return TestClient(app)


def attach_evidence(
    incident_id: str,
    service: str = "order-service",
    message: str = "Order processing failed",
    exception_type: str = "OrderProcessingError",
    endpoint: str = "/api/v1/orders",
    event: str = "order_creation_failed",
) -> Evidence:
    """Helper attaching verified runtime evidence directly into evidence repository."""
    ev_repo = get_evidence_repository()
    now = datetime.datetime.now(datetime.timezone.utc)
    ev = Evidence(
        id=str(uuid.uuid4()),
        incident_id=incident_id,
        type=EvidenceType.RUNTIME_LOG,
        source="demo_app.jsonl",
        timestamp=now,
        service=service,
        request_id="req-test-12345",
        level="ERROR",
        event=event,
        message=message,
        endpoint=endpoint,
        exception_type=exception_type,
        created_at=now,
    )
    ev_repo.create(ev)
    return ev


def make_test_incident(incident_id: str = "inc-100", service: str = "order-service") -> Incident:
    return Incident(
        id=incident_id,
        title=f"Failure in {service}",
        service=service,
        environment="production",
        severity=Severity.CRITICAL,
        status=IncidentStatus.INVESTIGATING,
        summary=f"Orders failing in {service}",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )


def make_test_investigation(
    incident_id: str = "inc-100",
    status: InvestigationStatus = InvestigationStatus.COMPLETED,
    valid: bool = True,
    service: str = "order-service",
    exception_type: str = "OrderProcessingError",
    endpoint: str = "/api/v1/orders",
    failure_location: str = "OrderService.create_order",
    triggering_condition: str = "self._failure_controller.is_order_processing_error_enabled() evaluated true",
    root_cause_hypothesis: str = "OrderService.create_order raised OrderProcessingError when condition evaluated true",
) -> Investigation:
    now = datetime.datetime.now(datetime.timezone.utc)
    rca = RootCauseAnalysis(
        failure_location=failure_location,
        triggering_condition=triggering_condition,
        root_cause_hypothesis=root_cause_hypothesis,
        affected_component=failure_location,
        summary=f"Incident caused by {triggering_condition}",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="ev-123", description="Runtime error"),
            EvidenceReference(type="code", id="chunk-456", description="Code chunk"),
        ],
        confidence=0.85,
    )
    validation = RCAValidation(
        valid=valid,
        issues=[] if valid else ["Ungrounded claim detected"],
        unsupported_claims=[] if valid else ["Ungrounded claim"],
        missing_evidence=[],
    )
    return Investigation(
        investigation_id="inv-100",
        incident_id=incident_id,
        status=status,
        created_at=now,
        completed_at=now,
        runtime_analysis=RuntimeAnalysis(
            service=service,
            endpoint=endpoint,
            exception_type=exception_type,
            important_messages=["Order processing failed unexpectedly"],
            observed_failures=[f"{exception_type} occurred"],
        ),
        code_analysis=CodeAnalysis(
            relevant_symbols=[failure_location, "OrderService"],
            relevant_files=["app/orders/service.py"],
        ),
        rca=rca,
        validation=validation,
    )


# =====================================================================
# Unit Tests: Ingestion Eligibility & Idempotency
# =====================================================================


def test_ingest_eligible_investigation():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-01")
    inv = make_test_investigation("inc-01", status=InvestigationStatus.COMPLETED, valid=True)

    mem = service.ingest_investigation(inv, incident)
    assert mem is not None
    assert mem.incident_id == "inc-01"
    assert mem.service == "order-service"
    assert mem.failure_location == "OrderService.create_order"
    assert mem.exception_type == "OrderProcessingError"
    assert mem.endpoint == "/api/v1/orders"

    retrieved = repo.get_by_incident_id("inc-01")
    assert retrieved is not None
    assert retrieved.incident_id == "inc-01"


def test_reject_failed_investigation():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-02")
    inv = make_test_investigation("inc-02", status=InvestigationStatus.FAILED, valid=False)

    mem = service.ingest_investigation(inv, incident)
    assert mem is None
    assert repo.get_by_incident_id("inc-02") is None


def test_reject_invalid_validation():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-03")
    inv = make_test_investigation("inc-03", status=InvestigationStatus.COMPLETED, valid=False)

    mem = service.ingest_investigation(inv, incident)
    assert mem is None
    assert repo.get_by_incident_id("inc-03") is None


def test_reject_missing_rca():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-04")
    inv = make_test_investigation("inc-04", status=InvestigationStatus.COMPLETED, valid=True)
    inv.rca = None

    mem = service.ingest_investigation(inv, incident)
    assert mem is None
    assert repo.get_by_incident_id("inc-04") is None


def test_idempotent_refresh_updates_existing_memory():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-05")
    inv1 = make_test_investigation("inc-05", root_cause_hypothesis="Initial hypothesis")
    mem1 = service.ingest_investigation(inv1, incident)
    assert mem1 is not None
    created_at = mem1.created_at

    # Later valid investigation updates the same incident memory
    inv2 = make_test_investigation("inc-05", root_cause_hypothesis="Refined hypothesis")
    mem2 = service.ingest_investigation(inv2, incident)
    assert mem2 is not None
    assert mem2.root_cause_hypothesis == "Refined hypothesis"
    assert mem2.created_at == created_at  # Preserves initial creation time
    assert len(repo.list_all()) == 1


def test_failed_investigation_never_overwrites_existing_valid_memory():
    repo = InMemoryIncidentMemoryRepository()
    service = IncidentMemoryService(repository=repo)

    incident = make_test_incident("inc-06")
    inv1 = make_test_investigation("inc-06", root_cause_hypothesis="Trusted RCA")
    service.ingest_investigation(inv1, incident)

    # Subsequent failed investigation must not touch or overwrite existing memory
    inv2 = make_test_investigation("inc-06", status=InvestigationStatus.FAILED, valid=False)
    mem2 = service.ingest_investigation(inv2, incident)
    assert mem2 is None

    stored = repo.get_by_incident_id("inc-06")
    assert stored is not None
    assert stored.root_cause_hypothesis == "Trusted RCA"


# =====================================================================
# Unit Tests: Matcher Scoring, Self-Exclusion, and Ranking
# =====================================================================


def test_matcher_self_exclusion():
    matcher = IncidentMemoryMatcher(threshold=3.0)
    candidate = IncidentMemory(
        incident_id="inc-current",
        service="order-service",
        environment="production",
        title="Order failure",
        failure_location="OrderService.create_order",
        triggering_condition="flag evaluated true",
        root_cause_hypothesis="order error",
        summary="summary",
        exception_type="OrderProcessingError",
        endpoint="/orders",
    )
    query = HistoricalSearchQuery(
        current_incident_id="inc-current",
        service="order-service",
        exception_type="OrderProcessingError",
        endpoint="/orders",
    )
    results = matcher.match(query, [candidate])
    # Must exclude itself
    assert len(results) == 0


def test_matcher_categorical_and_lexical_scoring():
    matcher = IncidentMemoryMatcher(threshold=3.0)
    candidate = IncidentMemory(
        incident_id="inc-past-1",
        service="order-service",
        environment="production",
        title="Payment timeout in order processing",
        failure_location="OrderService.create_order",
        triggering_condition="flag evaluated true",
        root_cause_hypothesis="Payment processing raised OrderProcessingError",
        summary="Payment timeout caused order processing failure",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
        relevant_symbols=["OrderService.create_order"],
    )

    query = HistoricalSearchQuery(
        current_incident_id="inc-current",
        service="order-service",  # +3.0
        exception_type="OrderProcessingError",  # +4.0
        endpoint="/api/v1/orders",  # +2.0
        relevant_symbols=["OrderService.create_order"],  # +5.0
        query_text="Payment timeout order processing",  # Lexical overlap
    )

    results = matcher.match(query, [candidate])
    assert len(results) == 1
    match = results[0]
    assert match.incident_id == "inc-past-1"
    # Base categorical: 3.0 + 4.0 + 2.0 + 5.0 = 14.0 + lexical score
    assert match.similarity_score >= 14.0
    assert "service_match" in match.matched_signals
    assert "exception_type_match" in match.matched_signals
    assert "endpoint_match" in match.matched_signals
    assert "symbol_match" in match.matched_signals
    assert any("lexical_overlap" in s for s in match.matched_signals)


def test_matcher_noise_filtering_same_service_vs_genuinely_related():
    """Verify that a genuinely related incident ranks above an unrelated incident that merely shares the service name."""
    matcher = IncidentMemoryMatcher(threshold=3.0)

    # Candidate A: Same service only, totally different failure (noise)
    unrelated_same_service = IncidentMemory(
        incident_id="inc-noise",
        service="order-service",
        environment="production",
        title="Inventory sync database lock",
        failure_location="InventorySyncWorker.sync",
        triggering_condition="db connection timeout",
        root_cause_hypothesis="Lock contention on database table",
        summary="Database lock prevented inventory sync",
        exception_type="DatabaseLockError",
        endpoint="/internal/sync",
    )

    # Candidate B: Genuinely related (same service + matching exception + matching symbol)
    genuinely_related = IncidentMemory(
        incident_id="inc-related",
        service="order-service",
        environment="production",
        title="Order creation failure under controlled fault injection",
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError",
        summary="Controlled fault mode caused order creation failure",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
        relevant_symbols=["OrderService.create_order"],
    )

    query = HistoricalSearchQuery(
        current_incident_id="inc-current",
        service="order-service",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
        relevant_symbols=["OrderService.create_order"],
        query_text="Order processing failure under controlled condition",
        limit=1,
    )

    results = matcher.match(query, [unrelated_same_service, genuinely_related])
    # With limit=1, the genuinely related candidate MUST be selected
    assert len(results) == 1
    assert results[0].incident_id == "inc-related"
    assert results[0].similarity_score > 10.0


def test_matcher_below_threshold_excluded():
    matcher = IncidentMemoryMatcher(threshold=3.0)
    # Different service, different exception, endpoint match only (+2.0 < 3.0)
    candidate = IncidentMemory(
        incident_id="inc-past-2",
        service="auth-service",
        environment="production",
        title="Auth failure",
        failure_location="AuthService.verify",
        triggering_condition="expired token",
        root_cause_hypothesis="token expired",
        summary="summary",
        endpoint="/api/v1/orders",  # Only +2.0
        exception_type="TokenExpiredError",
    )
    query = HistoricalSearchQuery(
        current_incident_id="inc-current",
        service="order-service",
        endpoint="/api/v1/orders",
    )
    results = matcher.match(query, [candidate])
    assert len(results) == 0


# =====================================================================
# Graph Integration Tests: Cold Start, Populated Retrieval, Failure Resilience
# =====================================================================


def test_graph_cold_start_empty_memory(client: TestClient):
    """When memory repository is empty, investigation runs normally and historical_context is empty."""
    # 1. Create incident
    inc_resp = client.post(
        "/incidents",
        json={
            "title": "Cold start order failure",
            "service": "order-service",
            "environment": "production",
            "severity": "high",
            "summary": "Order failure cold start test",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]

    # 2. Attach runtime evidence
    attach_evidence(
        inc_id,
        service="order-service",
        message="OrderProcessingError: order processing failed",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
    )

    # 3. Investigate
    inv_resp = client.post(f"/incidents/{inc_id}/investigate")
    assert inv_resp.status_code == 200
    data = inv_resp.json()
    assert data["status"] == "completed"
    assert data["historical_context"] == []


def test_graph_retrieves_past_memory_and_auto_ingests(client: TestClient):
    """Investigation 1 completes and auto-ingests. Investigation 2 on similar incident retrieves Investigation 1 as context."""
    # --- Incident 1 ---
    inc1_resp = client.post(
        "/incidents",
        json={
            "title": "Order processing error incident 1",
            "service": "order-service",
            "environment": "production",
            "severity": "critical",
            "summary": "First failure incident",
        },
    )
    inc1_id = inc1_resp.json()["id"]
    attach_evidence(
        inc1_id,
        service="order-service",
        message="OrderProcessingError: first order processing failed",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
    )
    inv1_resp = client.post(f"/incidents/{inc1_id}/investigate")
    assert inv1_resp.status_code == 200
    assert inv1_resp.json()["status"] == "completed"

    # Verify Incident 1 was ingested into memory
    mem_resp = client.get(f"/memory/{inc1_id}")
    assert mem_resp.status_code == 200
    assert mem_resp.json()["incident_id"] == inc1_id

    # --- Incident 2 (Similar failure) ---
    inc2_resp = client.post(
        "/incidents",
        json={
            "title": "Order processing error incident 2",
            "service": "order-service",
            "environment": "production",
            "severity": "critical",
            "summary": "Second failure incident with same signature",
        },
    )
    inc2_id = inc2_resp.json()["id"]
    attach_evidence(
        inc2_id,
        service="order-service",
        message="OrderProcessingError: second order processing failed",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
    )

    inv2_resp = client.post(f"/incidents/{inc2_id}/investigate")
    assert inv2_resp.status_code == 200
    data2 = inv2_resp.json()
    assert data2["status"] == "completed"

    # Verify historical context contains Incident 1
    assert len(data2["historical_context"]) >= 1
    matched = data2["historical_context"][0]
    assert matched["incident_id"] == inc1_id
    assert matched["service"] == "order-service"
    assert matched["similarity_score"] >= 3.0

    # Provenance isolation check: RCA supporting_evidence must NOT cite historical incident IDs
    rca = data2["rca"]
    for ref in rca["supporting_evidence"]:
        assert ref["id"] != inc1_id
        assert "inc-" not in ref["id"]  # only runtime log IDs, chunk IDs, or commit hashes


def test_memory_search_failure_resilience(monkeypatch, client: TestClient):
    """If memory search raises an unexpected exception, the investigation must NOT crash."""
    mem_service = get_memory_service()

    def mock_search_fail(query):
        raise RuntimeError("Memory backend connection timeout")

    monkeypatch.setattr(mem_service, "search_history", mock_search_fail)

    inc_resp = client.post(
        "/incidents",
        json={
            "title": "Resilience test incident",
            "service": "order-service",
            "environment": "production",
            "severity": "medium",
            "summary": "Testing resilience to memory failure",
        },
    )
    inc_id = inc_resp.json()["id"]
    attach_evidence(
        inc_id,
        service="order-service",
        message="OrderProcessingError: order processing failed",
        exception_type="OrderProcessingError",
        endpoint="/api/v1/orders",
    )

    inv_resp = client.post(f"/incidents/{inc_id}/investigate")
    assert inv_resp.status_code == 200
    data = inv_resp.json()
    # Investigation completes despite memory failure
    assert data["status"] == "completed"
    assert data["historical_context"] == []
    # Error should be non-fatal and noted in errors list
    assert any("Historical memory retrieval failed" in err for err in data["errors"])


# =====================================================================
# API Endpoints Tests: GET /memory, GET /memory/{id}, POST /memory/search
# =====================================================================


def test_memory_api_endpoints(client: TestClient):
    # Initial state: empty
    list_resp = client.get("/memory")
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    # Non-existent incident memory returns 404
    get_resp = client.get("/memory/non-existent")
    assert get_resp.status_code == 404

    # Seed a memory directly via repository
    repo = get_memory_repository()
    repo.save(
        IncidentMemory(
            incident_id="inc-api-test",
            service="order-service",
            environment="production",
            title="API Seed Incident",
            failure_location="OrderService.create_order",
            triggering_condition="fault active",
            root_cause_hypothesis="fault caused error",
            summary="API test summary",
            exception_type="OrderProcessingError",
            endpoint="/api/v1/orders",
            relevant_symbols=["OrderService.create_order"],
            investigation_id="inv-api-test",
        )
    )

    # Verify GET /memory lists the memory
    list_resp = client.get("/memory")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["incident_id"] == "inc-api-test"

    # Verify GET /memory/{incident_id}
    single_resp = client.get("/memory/inc-api-test")
    assert single_resp.status_code == 200
    assert single_resp.json()["incident_id"] == "inc-api-test"
    assert single_resp.json()["failure_location"] == "OrderService.create_order"

    # Verify POST /memory/search
    search_resp = client.post(
        "/memory/search",
        json={
            "current_incident_id": "inc-current-different",
            "service": "order-service",
            "exception_type": "OrderProcessingError",
            "endpoint": "/api/v1/orders",
            "relevant_symbols": ["OrderService.create_order"],
            "query_text": "API Seed Incident",
            "limit": 2,
        },
    )
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["total"] == 1
    assert search_data["results"][0]["incident_id"] == "inc-api-test"
    assert search_data["results"][0]["similarity_score"] >= 10.0
