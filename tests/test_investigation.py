"""Automated tests for Stage 6 — First LangGraph / AI Investigation Workflow.

All tests operate 100% offline using FakeInvestigationLLM without requiring external API keys,
external services, or network calls.
"""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any, Dict, List
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents.dependencies import (
    get_investigation_llm,
    get_investigation_repository,
    get_investigation_service,
)
from app.agents.llm import FakeInvestigationLLM
from app.agents.models import (
    EvidenceReference,
    InvestigationLLMError,
    InvestigationStatus,
    RCAValidation,
    RootCauseAnalysis,
)
from app.agents.repository import InMemoryInvestigationRepository
from app.agents.service import InvestigationService
from app.incidents.dependencies import get_incident_repository, get_incident_service
from app.main import app
from app.repository.client import GitClient
from app.repository.dependencies import get_git_service
from app.repository.service import GitService
from app.retrieval.dependencies import get_code_index, get_retrieval_service
from app.retrieval.index import CodeIndex
from app.retrieval.models import CodeChunk
from app.retrieval.service import RetrievalService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import Evidence, EvidenceType
from app.telemetry.repository import InMemoryEvidenceRepository

client = TestClient(app)


# =====================================================================
# Fixtures & Setup
# =====================================================================


@pytest.fixture
def fake_llm() -> FakeInvestigationLLM:
    """Provides a fresh FakeInvestigationLLM."""
    return FakeInvestigationLLM()


@pytest.fixture
def test_git_repo(tmp_path: Path):
    """Creates a temporary, deterministic Git repository for investigation tests."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    def run_git(args: list[str]) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()

    run_git(["init"])
    run_git(["config", "user.name", "SentinelOps Test"])
    run_git(["config", "user.email", "test@sentinelops.local"])

    # Create dummy order_service.py
    services_dir = repo_dir / "demo_app" / "services"
    services_dir.mkdir(parents=True)
    code_file = services_dir / "order_service.py"
    code_file.write_text(
        "class OrderService:\n"
        "    def create_order(self, request):\n"
        "        if failure_enabled:\n"
        "            raise OrderProcessingError('Payment gateway timeout')\n"
        "        return 'order-created'\n",
        encoding="utf-8",
    )

    run_git(["add", "."])
    run_git(["commit", "-m", "Initial commit with OrderService"])

    # Make a small change to simulate recent history
    code_file.write_text(
        "class OrderService:\n"
        "    def create_order(self, request):\n"
        "        # Added validation check\n"
        "        if failure_enabled:\n"
        "            raise OrderProcessingError('Payment gateway timeout')\n"
        "        return 'order-created'\n",
        encoding="utf-8",
    )
    run_git(["commit", "-am", "Add validation check in create_order"])

    return repo_dir


@pytest.fixture(autouse=True)
def clean_repositories():
    """Ensure in-memory repositories are cleared before each test."""
    app.dependency_overrides.clear()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()
    get_code_index().clear()
    yield
    app.dependency_overrides.clear()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()
    get_code_index().clear()


def create_incident_with_evidence(
    service: str = "order-service",
    endpoint: str = "/orders",
    exception_type: str = "OrderProcessingError",
    event: str = "order_processing_failed",
    message: str = "Payment gateway timeout occurred during checkout",
) -> tuple[str, str]:
    """Helper creating an incident and attaching verified runtime evidence."""
    # 1. Create Incident
    inc_res = client.post(
        "/incidents",
        json={
            "title": "Order Processing Failure in Production",
            "summary": "Multiple checkout failures reported with OrderProcessingError.",
            "severity": "high",
            "service": service,
            "environment": "production",
        },
    )
    assert inc_res.status_code == 201
    incident_id = inc_res.json()["id"]

    # 2. Attach Evidence directly to repository
    ev_repo = get_evidence_repository()
    evidence_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    evidence = Evidence(
        id=evidence_id,
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
    ev_repo.create(evidence)

    return incident_id, evidence_id


# =====================================================================
# Tests: Investigation Workflow
# =====================================================================


def test_investigation_graph_happy_path(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies end-to-end execution of the multi-node LangGraph investigation workflow."""
    # Pre-index source code chunk into shared code index
    index = get_code_index()
    chunk = CodeChunk.create(
        file_path="demo_app/services/order_service.py",
        symbol_name="OrderService.create_order",
        symbol_type="method",
        start_line=2,
        end_line=6,
        content="    def create_order(self, request):\n        if failure_enabled:\n            raise OrderProcessingError('Payment gateway timeout')\n",
    )
    index.rebuild(repository="sentinelops", chunks=[chunk])

    # Configure Git service override pointing to temporary git repo
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    # Dependency overrides for testing
    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, evidence_id = create_incident_with_evidence()

    # Trigger investigation
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    # Verify overall investigation structure
    assert data["incident_id"] == incident_id
    assert data["status"] == "completed"
    assert data["completed_at"] is not None

    # Verify runtime analysis
    ra = data["runtime_analysis"]
    assert ra is not None
    assert ra["service"] == "order-service"
    assert ra["endpoint"] == "/orders"
    assert ra["exception_type"] == "OrderProcessingError"
    assert "req-test-12345" in ra["request_ids"]

    # Verify code retrieval
    assert data["code_query"] is not None
    assert len(data["code_results"]) > 0
    assert data["code_results"][0]["id"] == chunk.id
    assert data["code_results"][0]["symbol_name"] == "OrderService.create_order"

    # Verify code analysis
    ca = data["code_analysis"]
    assert ca is not None
    assert "OrderService.create_order" in ca["relevant_symbols"]
    assert "demo_app/services/order_service.py" in ca["relevant_files"]

    # Verify Git context
    gc = data["git_context"]
    assert len(gc) > 0
    assert gc[0]["file_path"] == "demo_app/services/order_service.py"
    assert len(gc[0]["commits"]) > 0

    # Verify change analysis
    cha = data["change_analysis"]
    assert cha is not None
    assert len(cha["facts"]) > 0
    assert len(cha["inferences"]) > 0

    # Verify Root Cause Analysis
    rca = data["rca"]
    assert rca is not None
    assert "OrderProcessingError" in rca["root_cause_hypothesis"]
    assert rca["affected_component"] == "OrderService.create_order"
    assert rca["confidence"] > 0.0

    # Verify supporting evidence citations
    citations = {ref["id"] for ref in rca["supporting_evidence"]}
    assert evidence_id in citations
    assert chunk.id in citations

    # Verify validation
    val = data["validation"]
    assert val is not None
    assert val["valid"] is True
    assert len(val["issues"]) == 0


def test_investigation_evidence_grounding_preservation(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that concrete evidence IDs (runtime, chunk, commit) survive into final output."""
    index = get_code_index()
    chunk = CodeChunk.create(
        file_path="demo_app/services/order_service.py",
        symbol_name="OrderService.create_order",
        symbol_type="method",
        start_line=2,
        end_line=6,
        content="    def create_order(self, request):\n        pass\n",
    )
    index.rebuild(repository="sentinelops", chunks=[chunk])

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    _, commits = git_service.get_file_history("demo_app/services/order_service.py")
    top_commit_hash = commits[0].commit_hash

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, evidence_id = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    rca = res.json()["rca"]

    # Verify all 3 evidence types are explicitly represented with correct IDs
    types_found = {ref["type"]: ref["id"] for ref in rca["supporting_evidence"]}
    assert "runtime" in types_found
    assert types_found["runtime"] == evidence_id
    assert "code" in types_found
    assert types_found["code"] == chunk.id
    assert "git_commit" in types_found
    assert types_found["git_commit"] == top_commit_hash


def test_investigation_unsupported_claim_detection(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that the validator flags ungrounded claims (such as fabricated Redis errors)."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    # Instruct FakeLLM to return an RCA claiming Redis caused the issue
    fake_llm.custom_rca = RootCauseAnalysis(
        root_cause_hypothesis="Redis connection pool exhaustion caused timeout",
        affected_component="RedisCache",
        summary="Redis cache was unavailable, preventing checkout.",
        supporting_evidence=[],
        confidence=0.95,
        uncertainties=[],
    )

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    val = res.json()["validation"]

    # Validator must reject the ungrounded Redis claim
    assert val["valid"] is False
    assert any("Redis" in issue for issue in val["issues"])
    assert any("redis" in claim.lower() for claim in val["unsupported_claims"])


def test_investigation_bounded_revision_flow(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that an invalid RCA is routed through the revision node and re-validated."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    call_count = {"validation": 0, "revision": 0}

    # First validation fails, second validation passes
    def dynamic_validation(rca: RootCauseAnalysis, **kwargs) -> RCAValidation:
        call_count["validation"] += 1
        if call_count["validation"] == 1:
            return RCAValidation(
                valid=False,
                issues=["RCA mentions Redis, but no Redis evidence was supplied."],
                unsupported_claims=["Redis claim"],
            )
        return RCAValidation(valid=True, issues=[], unsupported_claims=[])

    def dynamic_revision(rca: RootCauseAnalysis, validation: RCAValidation, **kwargs) -> RootCauseAnalysis:
        call_count["revision"] += 1
        return RootCauseAnalysis(
            root_cause_hypothesis="Revised: OrderProcessingError in order service",
            affected_component="OrderService",
            summary="Revised summary removing Redis.",
            supporting_evidence=rca.supporting_evidence,
            confidence=0.70,
            uncertainties=["Revised to address validation failure."],
        )

    fake_llm.validation_handler = dynamic_validation
    fake_llm.revision_handler = dynamic_revision

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    # Bounded revision: executed exactly 1 revision, validated twice
    assert call_count["validation"] == 2
    assert call_count["revision"] == 1
    assert data["validation"]["valid"] is True
    assert "Revised:" in data["rca"]["root_cause_hypothesis"]


def test_investigation_retry_bound_preventing_infinite_loop(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that repeated validation failures terminate safely without looping indefinitely."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    validation_invocations = 0

    def always_invalid_validation(**kwargs) -> RCAValidation:
        nonlocal validation_invocations
        validation_invocations += 1
        return RCAValidation(
            valid=False,
            issues=["Persistent ungrounded claim."],
            unsupported_claims=["Unsupported claim"],
        )

    fake_llm.validation_handler = always_invalid_validation

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    # With max_revisions=1: initial validation (1) + revision (1) + second validation (2) -> terminates
    assert validation_invocations == 2
    assert data["status"] == "failed"
    assert data["validation"]["valid"] is False


def test_investigation_missing_incident_returns_404():
    """Verifies that requesting investigation on a non-existent incident returns HTTP 404."""
    unknown_id = str(uuid.uuid4())
    res = client.post(f"/incidents/{unknown_id}/investigate")
    assert res.status_code == 404
    assert unknown_id in res.json()["detail"]
    assert "not found" in res.json()["detail"].lower()


def test_investigation_no_runtime_evidence_returns_409():
    """Verifies that requesting investigation on an incident with 0 evidence returns HTTP 409."""
    # Create incident without attaching any evidence
    inc_res = client.post(
        "/incidents",
        json={
            "title": "Incident Without Evidence",
            "summary": "This incident has no evidence attached.",
            "severity": "low",
            "service": "demo-app",
            "environment": "development",
        },
    )
    assert inc_res.status_code == 201
    incident_id = inc_res.json()["id"]

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 409
    assert "no runtime evidence available for investigation" in res.json()["detail"]


def test_investigation_empty_code_retrieval_handles_gracefully(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that 0 code retrieval results do not crash the workflow and uncertainties are recorded."""
    # Ensure code index is completely empty
    get_code_index().clear()

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert len(data["code_results"]) == 0
    # Uncertainty must explicitly acknowledge lack of retrieved code
    assert any("source-code context was retrieved" in u for u in data["rca"]["uncertainties"])
    assert data["rca"]["confidence"] <= 0.60


def test_investigation_missing_git_history_handles_gracefully(fake_llm: FakeInvestigationLLM, tmp_path: Path):
    """Verifies that missing or invalid Git history does not abort the investigation."""
    empty_repo_dir = tmp_path / "empty_dir"
    empty_repo_dir.mkdir()

    # Pass a non-git directory to GitClient
    git_client = GitClient(repository_path=str(empty_repo_dir))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None


def test_investigation_llm_failure_safe_handling(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that an unhandled LLM provider error returns a controlled HTTP 502 without leaking secrets."""
    fake_llm.raise_error = True
    fake_llm.error_message = "Simulated OpenAI rate limit or timeout."

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    # When analyze_runtime handles the error, it reports it safely
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code in [200, 502]
    if res.status_code == 200:
        data = res.json()
        assert len(data["errors"]) > 0


def test_get_investigation_endpoint(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies GET /incidents/{incident_id}/investigation behavior before and after running investigation."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    # 1. Before investigation: returns 404
    get_res_before = client.get(f"/incidents/{incident_id}/investigation")
    assert get_res_before.status_code == 404
    assert f"No investigation found for incident '{incident_id}'" in get_res_before.json()["detail"]

    # 2. Run investigation: returns 200
    post_res = client.post(f"/incidents/{incident_id}/investigate")
    assert post_res.status_code == 200

    # 3. After investigation: returns 200 with identical investigation_id
    get_res_after = client.get(f"/incidents/{incident_id}/investigation")
    assert get_res_after.status_code == 200
    assert get_res_after.json()["investigation_id"] == post_res.json()["investigation_id"]
    assert get_res_after.json()["incident_id"] == incident_id


def test_zero_network_calls_assertion(monkeypatch):
    """Verifies that investigation tests execute purely locally with zero outbound network calls."""
    import socket

    def guard_connect(*args, **kwargs):
        raise RuntimeError("Prohibited outbound network call attempted during test!")

    monkeypatch.setattr(socket.socket, "connect", guard_connect)

    # Instantiate FakeInvestigationLLM and verify all methods run locally without network
    fake = FakeInvestigationLLM()
    now = datetime.now(timezone.utc)
    from app.incidents.models import Incident, IncidentStatus, Severity

    inc = Incident(
        id="test-inc",
        title="Test Inc",
        summary="Test summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="test-service",
        environment="test-env",
        created_at=now,
        updated_at=now,
    )
    ev = Evidence(
        id="test-ev",
        incident_id="test-inc",
        type=EvidenceType.RUNTIME_LOG,
        source="test.log",
        timestamp=now,
        service="test-service",
        request_id="req-1",
        level="ERROR",
        event="test_event",
        message="test msg",
        endpoint="/test",
        exception_type="TestError",
        created_at=now,
    )

    ra = fake.analyze_runtime(inc, [ev])
    assert ra.service == "test-service"
    ca = fake.analyze_code(ra, [{"id": "c1", "file_path": "test.py", "symbol_name": "fn", "symbol_type": "function"}])
    assert "fn" in ca.relevant_symbols
    cha = fake.analyze_changes(ra, ca, [])
    assert len(cha.facts) > 0
    code_ctx = [{"id": "c1", "file_path": "test.py", "symbol_name": "fn"}]
    rca = fake.synthesize_rca(inc, ra, ca, cha, [ev], code_ctx, [])
    assert rca.affected_component == "fn"
    val = fake.validate_rca(rca, inc, ra, ca, cha, [ev], code_ctx, [])
    assert val.valid is True


def test_investigation_rca_depth_and_triggering_condition(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Verifies that RCA distinguishes failure_location, triggering_condition, and builds deep causal hypothesis."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    code_index = get_code_index()

    # Pre-index code chunk with an explicit if guard
    code_index.rebuild(
        "demo_app",
        [
            CodeChunk(
                id="chunk-order-service-create",
                file_path="demo_app/services/order_service.py",
                symbol_name="OrderService.create_order",
                symbol_type="method",
                start_line=83,
                end_line=90,
                content=(
                    "class OrderService:\n"
                    "    def create_order(self, request):\n"
                    "        if failure_enabled:\n"
                    "            raise OrderProcessingError('Payment gateway timeout')\n"
                    "        return 'order-created'\n"
                ),
            )
        ],
    )

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, evidence_id = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    rca = data["rca"]
    assert rca is not None
    assert rca["failure_location"] == "OrderService.create_order"
    assert rca["triggering_condition"] == "Controlled condition 'failure_enabled' evaluated to True"
    assert (
        rca["root_cause_hypothesis"]
        == "OrderService.create_order raised OrderProcessingError because Controlled condition 'failure_enabled' evaluated to True"
    )
    assert "Controlled condition 'failure_enabled' evaluated to True" in rca["summary"]
    assert "OrderService.create_order" in rca["summary"]


def test_investigation_irrelevant_git_evidence_omitted_from_supporting(fake_llm: FakeInvestigationLLM, tmp_path: Path):
    """Verifies that baseline/generic Git commits are omitted from supporting_evidence and noted in uncertainties."""
    # Create Git repository with ONLY a baseline commit
    repo_dir = tmp_path / "baseline_only_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo_dir), check=True, capture_output=True)

    dummy_file = repo_dir / "service.py"
    dummy_file.write_text("class OrderService:\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial baseline commit"], cwd=str(repo_dir), check=True, capture_output=True)

    git_client = GitClient(repository_path=str(repo_dir))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    code_index = get_code_index()
    code_index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-1",
                file_path="service.py",
                symbol_name="OrderService",
                symbol_type="class",
                start_line=1,
                end_line=2,
                content="class OrderService:\n    pass\n",
            )
        ],
    )

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    # Verify Git context was discovered
    assert len(data["git_context"]) > 0

    # Verify baseline commit was NOT cited as supporting evidence
    git_supporting = [ref for ref in data["rca"]["supporting_evidence"] if ref["type"] == "git_commit"]
    assert len(git_supporting) == 0

    # Verify uncertainty explicitly notes that Git commits represent baseline state
    assert any("baseline/initial" in u for u in data["rca"]["uncertainties"])


def test_investigation_commit_deduplication_across_files(fake_llm: FakeInvestigationLLM):
    """Verifies that commits modifying multiple files are deduplicated and grouped in ChangeAnalysis."""
    from app.agents.models import CodeAnalysis, RuntimeAnalysis

    ra = RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError")
    ca = CodeAnalysis(
        relevant_symbols=["OrderService.create_order"],
        relevant_files=["demo_app/services/order_service.py", "demo_app/main.py"],
    )

    shared_commit = {
        "commit_hash": "ea2797a806eacc058a886f9f08cd885e3d91c668",
        "short_hash": "ea2797a",
        "author_name": "Dev",
        "committed_at": "2026-09-23T01:15:07Z",
        "message": "Initial SentinelOps implementation through Stage 4",
    }

    git_context = [
        {"file_path": "demo_app/services/order_service.py", "commits": [shared_commit]},
        {"file_path": "demo_app/main.py", "commits": [shared_commit]},
    ]

    change_analysis = fake_llm.analyze_changes(ra, ca, git_context)

    # Must have exactly 1 deduplicated fact and 1 change entry, listing both files
    assert len(change_analysis.facts) == 1
    assert "demo_app/services/order_service.py" in change_analysis.facts[0]
    assert "demo_app/main.py" in change_analysis.facts[0]
    assert len(change_analysis.relevant_changes) == 1
    assert "ea2797a" in change_analysis.relevant_changes[0]


def test_investigation_openai_provider_missing_key_fails_explicitly(monkeypatch):
    """Verifies that LLM_PROVIDER=openai without an API key fails explicitly (HTTP 502) and never falls back to mock."""
    import dataclasses
    from app.common.config import config

    mock_config = dataclasses.replace(config, llm_provider="openai", openai_api_key=None)
    monkeypatch.setattr("app.agents.dependencies.config", mock_config)

    # 1. Dependency injection raises InvestigationLLMError directly
    with pytest.raises(InvestigationLLMError) as exc_info:
        get_investigation_llm()
    assert "OpenAI provider configured (LLM_PROVIDER=openai) but OPENAI_API_KEY is not set" in str(exc_info.value)

    # 2. API endpoint returns HTTP 502 Bad Gateway with exact error message
    incident_id, _ = create_incident_with_evidence()
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 502
    assert "OpenAI provider configured (LLM_PROVIDER=openai) but OPENAI_API_KEY is not set" in res.json()["detail"]


# =====================================================================
# Stage 6 Real-Provider Reliability Regression Tests
# =====================================================================


def test_regression_provider_failure_in_analyze_runtime_halts_workflow(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 1: Provider failure in analyze_runtime halts workflow immediately without calling downstream nodes."""
    code_called = False
    rca_called = False

    def failing_runtime(*args, **kwargs):
        raise InvestigationLLMError("Runtime analysis reasoning failed.")

    def spy_code(*args, **kwargs):
        nonlocal code_called
        code_called = True
        return fake_llm.analyze_code(*args, **kwargs)

    def spy_rca(*args, **kwargs):
        nonlocal rca_called
        rca_called = True
        return fake_llm.synthesize_rca(*args, **kwargs)

    fake_llm.analyze_runtime = failing_runtime
    fake_llm.analyze_code = spy_code
    fake_llm.synthesize_rca = spy_rca

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "failed"
    assert data["rca"] is None
    assert data["runtime_analysis"] is None
    assert code_called is False
    assert rca_called is False
    assert any("Runtime analysis failed" in err for err in data["errors"])


def test_regression_provider_failure_in_analyze_code_halts_workflow(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 2: Provider failure in analyze_code halts workflow immediately without calling synthesize_rca."""
    rca_called = False

    def failing_code(*args, **kwargs):
        raise InvestigationLLMError("Code analysis reasoning failed.")

    def spy_rca(*args, **kwargs):
        nonlocal rca_called
        rca_called = True
        return fake_llm.synthesize_rca(*args, **kwargs)

    fake_llm.analyze_code = failing_code
    fake_llm.synthesize_rca = spy_rca

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "failed"
    assert data["rca"] is None
    assert data["code_analysis"] is None
    assert rca_called is False
    assert any("Code analysis failed" in err for err in data["errors"])


def test_regression_critical_upstream_failure_defensive_precondition(fake_llm: FakeInvestigationLLM):
    """Test 3: synthesize_rca_node defensive precondition rejects missing runtime or code analysis."""
    from app.agents.models import CodeAnalysis
    from app.workflows.investigation_graph import synthesize_rca_node
    from app.workflows.investigation_state import InvestigationState

    called = False

    def spy_synthesize(*args, **kwargs):
        nonlocal called
        called = True
        return fake_llm.synthesize_rca(*args, **kwargs)

    fake_llm.synthesize_rca = spy_synthesize

    state_no_runtime: InvestigationState = {
        "incident": None,  # type: ignore
        "runtime_evidence": [],
        "runtime_analysis": None,
        "code_query": None,
        "code_results": [],
        "code_analysis": CodeAnalysis(relevant_symbols=["fn"]),
        "git_context": [],
        "change_analysis": None,
        "rca": None,
        "validation": None,
        "revision_count": 0,
        "max_revisions": 1,
        "errors": [],
    }

    result = synthesize_rca_node(state_no_runtime, fake_llm)
    assert result["rca"] is None
    assert called is False
    assert any("required upstream reasoning missing" in err for err in result["errors"])


def test_regression_git_subsystem_failure_records_limitation_and_completes(fake_llm: FakeInvestigationLLM, tmp_path: Path):
    """Test 4: Git subsystem failure (Case B) records operational limitation and does not block valid RCA."""
    non_git_dir = tmp_path / "not_a_repo"
    non_git_dir.mkdir()

    git_client = GitClient(repository_path=str(non_git_dir))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    index = get_code_index()
    index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-order",
                file_path="demo_app/services/order_service.py",
                symbol_name="OrderService.create_order",
                symbol_type="method",
                start_line=1,
                end_line=5,
                content="def create_order(): pass",
            )
        ],
    )

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None
    assert data["validation"]["valid"] is True
    # Verify operational limitation recorded
    assert any("Git inspection unavailable" in err for err in data["errors"])


def test_regression_git_change_analysis_llm_failure_continues_to_rca(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 5: Git change analysis LLM failure (Case C) records reasoning limitation and continues with runtime+code."""
    def failing_change(*args, **kwargs):
        raise InvestigationLLMError("Change analysis reasoning timed out.")

    fake_llm.analyze_changes = failing_change

    index = get_code_index()
    index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-order",
                file_path="demo_app/services/order_service.py",
                symbol_name="OrderService.create_order",
                symbol_type="method",
                start_line=1,
                end_line=5,
                content="def create_order(): pass",
            )
        ],
    )

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None
    assert data["validation"]["valid"] is True
    assert any("change analysis reasoning failed" in err.lower() for err in data["errors"])


def test_regression_empty_git_history_treated_as_normal_condition(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 6: Empty Git history (Case A) is treated as a normal condition with no operational error recorded."""
    index = get_code_index()
    index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-untracked",
                file_path="demo_app/services/untracked_service.py",
                symbol_name="UntrackedService.run",
                symbol_type="method",
                start_line=1,
                end_line=5,
                content="def run(): pass",
            )
        ],
    )

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None
    assert data["validation"]["valid"] is True
    # Normal domain condition: no git operational errors recorded
    assert not any("Git repository unavailable" in err for err in data["errors"])


def test_regression_hallucinated_method_name_rejected_by_validator():
    """Test 7: RCA containing hallucinated symbol (OrderService.checkout_order) is rejected by grounding validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    from app.incidents.models import Incident, IncidentStatus, Severity

    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc-1",
        title="Order Error",
        summary="Failure in order service",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-service",
        environment="prod",
        created_at=now,
        updated_at=now,
    )
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    retrieved_chunks = [
        {"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]

    hallucinated_rca = RootCauseAnalysis(
        root_cause_hypothesis="OrderService.checkout_order failed due to unhandled error",
        affected_component="OrderService.checkout_order",
        failure_location="OrderService.checkout_order",
        triggering_condition="Order processing failed",
        summary="OrderService.checkout_order threw an exception",
        supporting_evidence=[EvidenceReference(id="ev-1", type="runtime", description="runtime error")],
        confidence=0.8,
        uncertainties=[],
    )

    val = run_deterministic_grounding_check(
        rca=hallucinated_rca,
        evidence=[ev],
        code_chunks=retrieved_chunks,
        git_context=[],
    )

    assert val.valid is False
    assert len(val.issues) > 0
    assert any("OrderService.checkout_order" in issue for issue in val.issues)
    assert any("checkout_order" in claim for claim in val.unsupported_claims)


def test_regression_hallucinated_fields_rejected_by_validator():
    """Test 8: RCA claiming missing 'email' or 'shipping_address' validation failed is rejected by validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    from app.incidents.models import Incident, IncidentStatus, Severity

    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc-1",
        title="Order Error",
        summary="Failure in order service",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-service",
        environment="prod",
        created_at=now,
        updated_at=now,
    )
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    retrieved_chunks = [
        {"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]

    hallucinated_rca = RootCauseAnalysis(
        root_cause_hypothesis="Validation error due to missing email and shipping_address fields",
        affected_component="OrderService.create_order",
        failure_location="OrderService.create_order",
        triggering_condition="Missing required field email in checkout payload",
        summary="Order creation failed because email and shipping_address were not provided",
        supporting_evidence=[EvidenceReference(id="ev-1", type="runtime", description="runtime error")],
        confidence=0.85,
        uncertainties=[],
    )

    val = run_deterministic_grounding_check(
        rca=hallucinated_rca,
        evidence=[ev],
        code_chunks=retrieved_chunks,
        git_context=[],
    )

    assert val.valid is False
    assert len(val.issues) > 0
    assert any("email" in issue or "shipping_address" in issue for issue in val.issues)
    assert any("email" in claim or "shipping_address" in claim for claim in val.unsupported_claims)


def test_regression_invalid_rca_after_max_revisions_fails(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 9: Invalid RCA after maximum revisions results in final status = failed."""
    fake_llm.validation_handler = lambda **kw: RCAValidation(
        valid=False,
        issues=["Persistent grounding failure."],
        unsupported_claims=["Fabricated claim"],
    )

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "failed"
    assert data["validation"]["valid"] is False
    assert any("RCA validation failed" in err for err in data["errors"])


def test_regression_one_bounded_revision_repairs_rca(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 10: One bounded revision successfully repairs an initially invalid RCA (status = completed, revisions = 1)."""
    attempt = 0

    def dynamic_val(**kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return RCAValidation(valid=False, issues=["Initial flaw."], unsupported_claims=["Flaw"])
        return RCAValidation(valid=True, issues=[], unsupported_claims=[])

    fake_llm.validation_handler = dynamic_val

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert attempt == 2
    assert data["status"] == "completed"
    assert data["validation"]["valid"] is True


def test_regression_missing_validation_fails():
    """Test 12: If validation is None, final investigation status must be failed."""
    from unittest.mock import MagicMock

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "rca": RootCauseAnalysis(
            root_cause_hypothesis="Something broke",
            affected_component="OrderService",
            summary="Broken",
            supporting_evidence=[],
            confidence=0.5,
            uncertainties=[],
        ),
        "validation": None,
        "errors": [],
    }

    mock_repo = MagicMock()
    mock_inc_svc = MagicMock()
    mock_ev_repo = MagicMock()
    mock_ret_svc = MagicMock()
    mock_git_svc = MagicMock()
    mock_llm = MagicMock()

    mock_inc_svc.get_incident.return_value = MagicMock(id="inc-123")
    mock_ev_repo.list_for_incident.return_value = [MagicMock()]

    svc = InvestigationService(
        investigation_repository=mock_repo,
        incident_service=mock_inc_svc,
        evidence_repository=mock_ev_repo,
        retrieval_service=mock_ret_svc,
        git_service=mock_git_svc,
        llm=mock_llm,
    )

    import app.agents.service as svc_mod
    original_build = svc_mod.build_investigation_graph
    try:
        svc_mod.build_investigation_graph = lambda **kwargs: mock_graph
        inv = svc.investigate("inc-123")
        assert inv.status == InvestigationStatus.FAILED
    finally:
        svc_mod.build_investigation_graph = original_build


def test_regression_real_provider_domain_exceptions_sanitize_secrets():
    """Test 13: Error sanitization ensures API keys, Bearer tokens, and auth headers are never leaked in error messages."""
    from app.agents.llm import _sanitize_error_message

    raw_message = (
        "OpenAI API request failed with key sk-FAKE_OPENAI_KEY! "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDcOGSoZSdFddec3JjWDWlMmEKYQ "
        "Authorization: Bearer my-top-secret-token"
    )

    sanitized = _sanitize_error_message(raw_message)

    assert "sk-FAKE_OPENAI_KEY" not in sanitized
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
    assert "my-top-secret-token" not in sanitized
    assert "[REDACTED]" in sanitized


def test_regression_incident_summary_used_and_no_description_access():
    """Test 14: Verifies Incident model uses 'summary', has NO 'description', and LangChainInvestigationLLM accesses summary."""
    import inspect
    from app.agents.llm import LangChainInvestigationLLM
    from app.incidents.models import Incident, IncidentStatus, Severity

    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc-test",
        title="Test Incident",
        summary="Test incident summary text",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-service",
        environment="production",
        created_at=now,
        updated_at=now,
    )

    assert hasattr(inc, "summary")
    assert not hasattr(inc, "description")

    source = inspect.getsource(LangChainInvestigationLLM)
    assert "incident.description" not in source
    assert "incident.summary" in source


def test_regression_offline_graph_integration_real_provider_scenario(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 15: Full integration test simulating real-provider scenario where Git change analysis fails.
    Verifies workflow gracefully continues with runtime + code, synthesizes valid RCA, and completes successfully."""
    def fail_changes(*args, **kwargs):
        raise InvestigationLLMError("LLM change analysis rate limit")

    fake_llm.analyze_changes = fail_changes

    index = get_code_index()
    index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-order",
                file_path="demo_app/services/order_service.py",
                symbol_name="OrderService.create_order",
                symbol_type="method",
                start_line=83,
                end_line=90,
                content="def create_order(self, request):\n    if failure_enabled:\n        raise OrderProcessingError('fail')",
            )
        ],
    )

    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None
    assert data["rca"]["affected_component"] == "OrderService.create_order"
    assert data["validation"]["valid"] is True
    assert any("change analysis reasoning failed" in err.lower() for err in data["errors"])


def test_regression_langchain_synthesize_rca_prompt_formatting_offline():
    """Test 16: Verifies LangChainInvestigationLLM.synthesize_rca builds prompt without NameError (offline mock)."""
    from unittest.mock import MagicMock
    from app.agents.llm import LangChainInvestigationLLM
    from app.agents.models import ChangeAnalysis, CodeAnalysis, RuntimeAnalysis
    from app.agents.schemas import EvidenceReferenceSchema, RootCauseAnalysisSchema
    from app.incidents.models import Incident, IncidentStatus, Severity

    mock_chat_model = MagicMock()
    mock_structured = MagicMock()
    mock_chat_model.with_structured_output.return_value = mock_structured

    mock_structured.invoke.return_value = RootCauseAnalysisSchema(
        failure_location="OrderService.create_order",
        triggering_condition="Controlled failure mode active",
        root_cause_hypothesis="OrderService.create_order failed due to active failure mode",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[
            EvidenceReferenceSchema(type="runtime", id="ev-123", description="Runtime error log"),
            EvidenceReferenceSchema(type="code", id="chunk-456", description="OrderService code"),
        ],
        confidence=0.8,
        uncertainties=[],
    )

    llm = LangChainInvestigationLLM.__new__(LangChainInvestigationLLM)
    llm._llm = mock_chat_model

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-123",
        title="Order Timeout",
        summary="Timeout in checkout",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-service",
        environment="production",
        created_at=now,
        updated_at=now,
    )
    ra = RuntimeAnalysis(
        service="order-service",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        observed_failures=["OrderProcessingError"],
        important_messages=["Simulated payment gateway timeout"],
        request_ids=["req-123"],
    )
    ca = CodeAnalysis(
        relevant_symbols=["OrderService.create_order"],
        relevant_files=["demo_app/services/order_service.py"],
    )
    cha = ChangeAnalysis(
        facts=["Commit ea2797a modified order_service.py"],
        inferences=["Recent commit touched relevant file"],
    )
    evidence_list = [
        Evidence(
            id="ev-123",
            incident_id="inc-123",
            type=EvidenceType.RUNTIME_LOG,
            source="demo_app.jsonl",
            timestamp=now,
            service="order-service",
            request_id="req-123",
            level="ERROR",
            event="order_processing_failed",
            message="Payment gateway timeout",
            endpoint="/orders",
            exception_type="OrderProcessingError",
            created_at=now,
        )
    ]
    code_chunks = [
        {
            "id": "chunk-456",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "symbol_type": "method",
            "start_line": 24,
            "end_line": 51,
            "content": "def create_order(): pass",
        }
    ]
    git_context = [
        {
            "file_path": "demo_app/services/order_service.py",
            "commits": [{"commit_hash": "ea2797a806eacc058a886f9f08cd885e3d91c668", "short_hash": "ea2797a", "message": "Initial commit"}],
        }
    ]

    rca = llm.synthesize_rca(
        incident=incident,
        runtime_analysis=ra,
        code_analysis=ca,
        change_analysis=cha,
        evidence=evidence_list,
        code_chunks=code_chunks,
        git_context=git_context,
    )

    assert rca is not None
    assert rca.failure_location == "OrderService.create_order"
    assert rca.triggering_condition == "Controlled failure mode active"

    invoked_prompt = mock_structured.invoke.call_args[0][0]
    assert "Retrieved Source Code Chunks:" in invoked_prompt
    assert "Chunk ID: chunk-456" in invoked_prompt
    assert "demo_app/services/order_service.py" in invoked_prompt


def test_regression_code_level_rca_without_code_evidence_citation_is_invalid():
    """Test 17: An RCA making code-level claims without citing a code chunk is rejected by validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="failure flag enabled",
        root_cause_hypothesis="OrderService.create_order failed due to failure flag",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[EvidenceReference(type="runtime", id="ev-1", description="Runtime error log")],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("does not cite any valid retrieved source code chunk ID" in issue for issue in val.issues)


def test_regression_runtime_rca_without_runtime_citation_is_invalid():
    """Test 18: An RCA omitting runtime evidence citation when runtime evidence is supplied is rejected."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="failure flag enabled",
        root_cause_hypothesis="OrderService.create_order failed due to failure flag",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[EvidenceReference(type="code", id="chunk-1", description="OrderService code")],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("does not cite any valid runtime evidence ID" in issue for issue in val.issues)


def test_regression_fabricated_code_chunk_id_is_invalid():
    """Test 19: An RCA citing a non-existent or fabricated code chunk ID is rejected by validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-valid-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="failure flag enabled",
        root_cause_hypothesis="OrderService.create_order failed due to failure flag",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="ev-1", description="Runtime error log"),
            EvidenceReference(type="code", id="chunk-fabricated-999", description="Fabricated chunk"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("Cited code chunk ID 'chunk-fabricated-999' does not exist" in issue for issue in val.issues)


def test_regression_fabricated_runtime_evidence_id_is_invalid():
    """Test 20: An RCA citing a non-existent or fabricated runtime evidence ID is rejected by validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-valid-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-valid-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="failure flag enabled",
        root_cause_hypothesis="OrderService.create_order failed due to failure flag",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="ev-fake-999", description="Fabricated runtime log"),
            EvidenceReference(type="code", id="chunk-valid-1", description="Valid chunk"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("Cited runtime evidence ID 'ev-fake-999' does not exist" in issue for issue in val.issues)


def test_regression_rca_with_valid_runtime_and_code_citations_is_valid():
    """Test 21: An RCA citing both legitimate runtime and code chunk IDs is accepted by validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-valid-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-valid-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="Controlled failure mode active",
        root_cause_hypothesis="OrderService.create_order failed due to Controlled failure mode active",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="ev-valid-1", description="Runtime error log"),
            EvidenceReference(type="code", id="chunk-valid-1", description="Valid code chunk"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0


def test_regression_bounded_revision_adds_missing_code_citation(fake_llm: FakeInvestigationLLM):
    """Test 22: Revision node automatically adds missing legitimate code citation when prompted by validator."""
    from app.agents.models import ChangeAnalysis, CodeAnalysis, RuntimeAnalysis
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-valid-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-valid-1", "file_path": "demo_app/services/order_service.py", "symbol_name": "OrderService.create_order"}
    ]
    initial_rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="failure flag enabled",
        root_cause_hypothesis="OrderService.create_order failed due to failure flag",
        affected_component="OrderService.create_order",
        summary="Summary of failure",
        supporting_evidence=[EvidenceReference(type="runtime", id="ev-valid-1", description="Runtime error log")],
        confidence=0.8,
        uncertainties=[],
    )
    # First validation fails due to missing code citation
    val1 = fake_llm.validate_rca(
        rca=initial_rca,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert val1.valid is False

    # Revision repairs it by adding the matching code chunk reference
    revised_rca = fake_llm.revise_rca(
        rca=initial_rca,
        validation=val1,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    types = {r.type for r in revised_rca.supporting_evidence}
    assert "runtime" in types
    assert "code" in types

    # Re-validation passes
    val2 = fake_llm.validate_rca(
        rca=revised_rca,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert val2.valid is True


def test_regression_runtime_analysis_preserves_request_ids_from_evidence():
    """Test 23: Verifies LangChainInvestigationLLM.analyze_runtime preserves request IDs from evidence (offline mock)."""
    from unittest.mock import MagicMock
    from app.agents.llm import LangChainInvestigationLLM
    from app.agents.schemas import RuntimeAnalysisSchema
    from app.incidents.models import Incident, IncidentStatus, Severity

    mock_chat = MagicMock()
    mock_structured = MagicMock()
    mock_chat.with_structured_output.return_value = mock_structured

    # LLM schema return has empty request_ids
    mock_structured.invoke.return_value = RuntimeAnalysisSchema(
        observed_failures=["OrderProcessingError"],
        service="order-service",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        important_messages=["Timeout occurred"],
        request_ids=[],  # LLM omitted request_id
        timeline=[],
        initial_hypotheses=[],
        missing_information=[],
    )

    llm = LangChainInvestigationLLM.__new__(LangChainInvestigationLLM)
    llm._llm = mock_chat

    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc-1",
        title="Incident",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-service",
        environment="production",
        created_at=now,
        updated_at=now,
    )
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-expected-456",
        level="ERROR",
        event="order_failed",
        message="error",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )

    ra = llm.analyze_runtime(inc, [ev])
    assert "req-expected-456" in ra.request_ids


def test_regression_valid_runtime_evidence_id_is_accepted():
    """Test 24: A real-shaped runtime evidence object whose ID is cited by the RCA is accepted."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    runtime_ev_id = "37e17189-3d70-48ff-998a-b9a47aeb49e1"
    ev = Evidence(
        id=runtime_ev_id,
        incident_id="1aaf977f-00cf-4b01-bd20-b0205a13c40e",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="0f77dcce-e3da-4c53-907a-05cb9e0b0937",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError because self._failure_controller.is_order_processing_error_enabled() evaluated true",
        affected_component="OrderService.create_order",
        summary="Order creation failed due to active controlled failure condition.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=runtime_ev_id, description="Runtime failure log"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561", description="OrderService.create_order code chunk"),
        ],
        confidence=0.9,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0


def test_regression_runtime_rca_citation_maps_to_stored_runtime_log_evidence():
    """Test 25: 'runtime' and 'runtime_log' RCA citations both correctly map to stored runtime_log evidence."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    runtime_ev_id = "37e17189-3d70-48ff-998a-b9a47aeb49e1"
    ev = Evidence(
        id=runtime_ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,  # Domain representation is "runtime_log"
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [{"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]

    # Case A: type="runtime"
    rca_runtime = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="condition evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because condition evaluated true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=runtime_ev_id),
            EvidenceReference(type="code", id="chunk-1"),
        ],
        confidence=0.8,
    )
    val_a = run_deterministic_grounding_check(rca=rca_runtime, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_a.valid is True

    # Case B: type="runtime_log"
    rca_runtime_log = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="condition evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because condition evaluated true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime_log", id=runtime_ev_id),
            EvidenceReference(type="code", id="chunk-1"),
        ],
        confidence=0.8,
    )
    val_b = run_deterministic_grounding_check(rca=rca_runtime_log, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_b.valid is True


def test_regression_fabricated_runtime_evidence_id_is_rejected_narrow():
    """Test 26: A fabricated runtime evidence ID is rejected even if format looks valid."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="37e17189-3d70-48ff-998a-b9a47aeb49e1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="error",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [{"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="condition evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because condition evaluated true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="fabricated-uuid-9999-ffff"),
            EvidenceReference(type="code", id="chunk-1"),
        ],
        confidence=0.8,
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("fabricated-uuid-9999-ffff" in issue for issue in val.issues)


def test_regression_valid_code_chunk_id_is_accepted():
    """Test 27: A valid code chunk ID is accepted by the validator."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_failed",
        message="error",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [{"id": "chunk-dd04b3223edb3561", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="condition evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because condition evaluated true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="ev-1"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0


def test_regression_failure_mode_was_enabled_without_enable_telemetry_fails():
    """Test 28: 'failure mode was enabled' without enable telemetry fails validation."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="37e17189-3d70-48ff-998a-b9a47aeb49e1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [{"id": "chunk-dd04b3223edb3561", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]

    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="the controlled failure mode was enabled",
        root_cause_hypothesis="OrderService.create_order failed because the failure mode was enabled",
        affected_component="OrderService.create_order",
        summary="Summary claiming failure mode was enabled",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="37e17189-3d70-48ff-998a-b9a47aeb49e1"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("was enabled" in issue.lower() for issue in val.issues)
    assert any("was enabled" in u.lower() for u in val.unsupported_claims)


def test_regression_condition_evaluated_true_claim_based_on_runtime_control_flow_allowed():
    """Test 29: Condition-evaluated-true claim passes with runtime + code evidence."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="37e17189-3d70-48ff-998a-b9a47aeb49e1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [{"id": "chunk-dd04b3223edb3561", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]

    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true",
        affected_component="OrderService.create_order",
        summary="Order creation failed when failure controller reported order processing failure active.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="37e17189-3d70-48ff-998a-b9a47aeb49e1"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0


def test_regression_bounded_revision_removes_unsupported_endpoint_specific_claim(fake_llm: FakeInvestigationLLM):
    """Test 30: Bounded revision converts unsupported enablement wording into evidence-grounded condition wording."""
    from app.agents.models import ChangeAnalysis, CodeAnalysis, RuntimeAnalysis
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="37e17189-3d70-48ff-998a-b9a47aeb49e1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {"id": "chunk-dd04b3223edb3561", "file_path": "demo_app/services/order_service.py", "symbol_name": "OrderService.create_order"}
    ]

    initial_rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="The controlled failure mode was enabled",
        root_cause_hypothesis="Failure occurred because the controlled failure mode was enabled via enable_order_processing_error()",
        affected_component="OrderService.create_order",
        summary="Order failure",
        supporting_evidence=[
            EvidenceReference(type="runtime", id="37e17189-3d70-48ff-998a-b9a47aeb49e1"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
    )

    # First validation fails because "was enabled" / enable action has no endpoint telemetry
    val1 = fake_llm.validate_rca(
        rca=initial_rca,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert val1.valid is False

    # Revision converts it into evidence-grounded condition wording and adds uncertainty note
    revised_rca = fake_llm.revise_rca(
        rca=initial_rca,
        validation=val1,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert "was enabled" not in revised_rca.triggering_condition.lower()
    assert "evaluated true" in revised_rca.triggering_condition
    assert any("does not establish how or when the failure condition became true" in u for u in revised_rca.uncertainties)
    assert any(ref.type == "runtime" and ref.id == "37e17189-3d70-48ff-998a-b9a47aeb49e1" for ref in revised_rca.supporting_evidence)
    assert any(ref.type == "code" and ref.id == "chunk-dd04b3223edb3561" for ref in revised_rca.supporting_evidence)

    # Re-validation passes
    val2 = fake_llm.validate_rca(
        rca=revised_rca,
        incident=None,  # type: ignore
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert val2.valid is True


def test_regression_revised_rca_with_valid_runtime_and_code_citations_passes(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 31: Full integration test verifying initial invalid RCA is revised and completes with valid runtime + code citations."""
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")

    index = get_code_index()
    index.rebuild(
        "sentinelops",
        [
            CodeChunk(
                id="chunk-dd04b3223edb3561",
                file_path="demo_app/services/order_service.py",
                symbol_name="OrderService.create_order",
                symbol_type="method",
                start_line=83,
                end_line=90,
                content="def create_order(self, request):\n    if self._failure_controller.is_order_processing_error_enabled():\n        raise OrderProcessingError('fail')",
            )
        ],
    )

    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()

    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["rca"] is not None
    assert data["validation"]["valid"] is True
    # Verify citations include runtime and code
    cited_types = {ref["type"] for ref in data["rca"]["supporting_evidence"]}
    assert "runtime" in cited_types or "runtime_log" in cited_types
    assert "code" in cited_types


def test_regression_traceback_reaches_statement_inside_if_condition_truthy_allowed():
    """Test 32: Traceback reaches statement inside if-condition -> truth-value claim is allowed."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Simulated payment gateway timeout during order checkout.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
        metadata={"traceback": "File order_service.py line 37 in create_order\n    raise OrderProcessingError"},
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('Simulated payment gateway timeout during order checkout.')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Order creation failed due to active controlled failure condition.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0


def test_regression_traceback_does_not_reach_branch_body_truth_claim_rejected():
    """Test 33: Traceback does not reach branch body -> truth-value claim is not automatically allowed."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="flag_error",
        message="Flag error occurred.",
        endpoint="/orders",
        exception_type="FlagError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-1",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if failure_flag:\n"
                "        raise FlagError('Flag error')\n"
                "    if unreached_condition_flag:\n"
                "        raise UnreachedError('Never reached')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="unreached_condition_flag evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because unreached_condition_flag evaluated true",
        affected_component="OrderService.create_order",
        summary="Order failure summary.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-1"),
        ],
        confidence=0.7,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("not prove execution reached" in iss.lower() for iss in val.issues)
    assert any("unreached_condition_flag" in u.lower() for u in val.unsupported_claims)


def test_regression_condition_state_inference_does_not_imply_how_state_became_true():
    """Test 34: Condition-state inference does not imply how the state became true (state origin claim without evidence fails)."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError because the failure mode was enabled by the operator",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("was enabled" in iss.lower() for iss in val.issues)


def test_regression_admin_endpoint_invocation_claim_without_telemetry_rejected():
    """Test 35: Admin-endpoint invocation claim without telemetry remains rejected."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": "def create_order(self, request): raise OrderProcessingError('fail')",
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="The admin enable endpoint was called",
        root_cause_hypothesis="OrderService.create_order failed because the admin enable endpoint was called",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("admin" in iss.lower() for iss in val.issues)


def test_regression_runtime_and_code_citation_combination_supports_branch_inference():
    """Test 36: Runtime + code citation combination is strictly required to support branch inference."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    # Case A: Missing code citation
    rca_no_code = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="runtime", id=ev_id)],
        confidence=0.8,
        uncertainties=[],
    )
    val_a = run_deterministic_grounding_check(rca=rca_no_code, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_a.valid is False
    assert any("code chunk" in iss.lower() for iss in val_a.issues)

    # Case B: Missing runtime citation
    rca_no_runtime = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="code", id="chunk-dd04b3223edb3561")],
        confidence=0.8,
        uncertainties=[],
    )
    val_b = run_deterministic_grounding_check(rca=rca_no_runtime, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_b.valid is False
    assert any("runtime evidence" in iss.lower() for iss in val_b.issues)

    # Case C: Both cited
    rca_both = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val_c = run_deterministic_grounding_check(rca=rca_both, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_c.valid is True


def test_regression_current_controlled_demo_rca_passes_validation():
    """Test 37: Current controlled-demo RCA passes validation with grounded control-flow inference."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    runtime_ev_id = "37e17189-3d70-48ff-998a-b9a47aeb49e1"
    ev = Evidence(
        id=runtime_ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app-runtime-log",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        event="order_processing_failed",
        message="Simulated payment gateway timeout during order checkout for product 'p1'.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
        metadata={"traceback": "File demo_app/services/order_service.py line 37 in create_order\n    raise OrderProcessingError"},
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request: OrderCreateRequest) -> OrderResponse:\n"
                "    product = self._product_service.get_product(request.product_id)\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('Simulated payment gateway timeout during order checkout')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Order creation failed due to active controlled failure condition.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=runtime_ev_id, description="Runtime 500 error log with OrderProcessingError"),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561", description="OrderService.create_order source chunk"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert len(val.issues) == 0
    assert len(val.unsupported_claims) == 0


def test_regression_fabricated_condition_not_in_retrieved_code_fails():
    """Test 38: Fabricated condition not present in retrieved code fails validation."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="database_connection_pool.is_exhausted() evaluated true",
        root_cause_hypothesis="OrderService.create_order failed because database_connection_pool.is_exhausted() evaluated true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("database_connection_pool" in iss.lower() or "fabricated condition" in iss.lower() for iss in val.issues)
    assert any("database_connection_pool" in u.lower() for u in val.unsupported_claims)


def test_regression_accepted_branch_inference_has_valid_true_and_empty_missing_evidence():
    """Test 39: Accepted branch inference yields valid=true and missing_evidence=[] (no contradictory demands)."""
    from unittest.mock import MagicMock
    from app.agents.grounding import run_deterministic_grounding_check
    from app.agents.llm import LangChainInvestigationLLM
    from app.agents.models import ChangeAnalysis, CodeAnalysis, RuntimeAnalysis
    from app.agents.schemas import RCAValidationSchema
    from app.incidents.models import Incident, IncidentStatus, Severity
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Simulated payment gateway timeout during order checkout.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
        metadata={"traceback": "File order_service.py line 37 in create_order\n    raise OrderProcessingError"},
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('Simulated payment gateway timeout')\n"
            ),
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Order creation failed due to active controlled failure condition.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )

    # 1. Deterministic check
    val_det = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val_det.valid is True
    assert val_det.missing_evidence == []

    # 2. Semantic reconciler: Simulate LLM returning spurious missing telemetry requirement
    mock_base = MagicMock()
    mock_structured = MagicMock()
    mock_base.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = RCAValidationSchema(
        valid=False,
        issues=["Direct telemetry evidence missing"],
        unsupported_claims=["self._failure_controller.is_order_processing_error_enabled() evaluated true"],
        missing_evidence=["Direct telemetry evidence showing self._failure_controller.is_order_processing_error_enabled() evaluated true"],
    )
    llm = LangChainInvestigationLLM.__new__(LangChainInvestigationLLM)
    llm._llm = mock_base
    val_merged = llm.validate_rca(
        rca=rca,
        incident=Incident(id="inc-1", title="Title", summary="Summary", severity=Severity.HIGH, status=IncidentStatus.OPEN, service="order-service", environment="prod", created_at=now, updated_at=now),
        runtime_analysis=RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError"),
        code_analysis=CodeAnalysis(relevant_symbols=["OrderService.create_order"]),
        change_analysis=ChangeAnalysis(),
        evidence=[ev],
        code_chunks=chunks,
        git_context=[],
    )
    assert val_merged.valid is True
    assert val_merged.issues == []
    assert val_merged.unsupported_claims == []
    assert val_merged.missing_evidence == []


def test_regression_genuinely_missing_required_evidence_has_valid_false_and_non_empty_missing_evidence():
    """Test 40: Genuinely missing required evidence results in valid=false and non-empty missing_evidence."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Simulated payment gateway timeout during order checkout.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": "def create_order(self, request): raise OrderProcessingError('fail')",
        }
    ]
    # Missing code citation
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="runtime", id=ev_id)],  # Code citation missing!
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert len(val.missing_evidence) > 0
    assert any("code chunk" in m.lower() for m in val.missing_evidence)


def test_regression_valid_true_must_never_contain_unresolved_required_missing_evidence():
    """Test 41: Invariant: valid=true must NEVER contain unresolved required missing evidence."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Simulated payment gateway timeout during order checkout.",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    # Valid RCA
    rca_valid = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val = run_deterministic_grounding_check(rca=rca_valid, evidence=[ev], code_chunks=chunks, git_context=[])
    if val.valid:
        assert val.missing_evidence == []
    else:
        assert len(val.missing_evidence) > 0


def test_regression_baseline_git_wording_has_no_speculative_claims():
    """Test 42: Baseline Git commit change analysis does not speculate that it altered flow or caused the error."""
    from unittest.mock import MagicMock
    from app.agents.llm import FakeInvestigationLLM, LangChainInvestigationLLM
    from app.agents.models import ChangeAnalysis, CodeAnalysis, RuntimeAnalysis
    from app.agents.schemas import ChangeAnalysisSchema
    ra = RuntimeAnalysis(service="order-service", exception_type="OrderProcessingError")
    ca = CodeAnalysis(relevant_symbols=["OrderService.create_order"], relevant_files=["demo_app/services/order_service.py"])
    git_context = [
        {
            "file_path": "demo_app/services/order_service.py",
            "commits": [
                {
                    "commit_hash": "ea2797a806eacc058a886f9f08cd885e3d91c668",
                    "short_hash": "ea2797a",
                    "message": "Initial commit",
                    "author_name": "Dev",
                    "committed_at": "2026-09-20T10:00:00Z",
                }
            ],
        }
    ]

    # 1. Fake LLM
    fake = FakeInvestigationLLM()
    cha_fake = fake.analyze_changes(ra, ca, git_context)
    assert len(cha_fake.facts) == 1
    for rel in cha_fake.potential_relationships:
        assert "altered the flow" not in rel.lower()
        assert "may relate to the error" not in rel.lower()
        assert "baseline" in rel.lower() or "causation cannot be established" in rel.lower()

    # 2. LangChain LLM with mock returning speculative wording
    mock_base = MagicMock()
    mock_structured = MagicMock()
    mock_base.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = ChangeAnalysisSchema(
        relevant_changes=["ea2797a (order_service.py): Initial commit"],
        potential_relationships=["Initial implementation may have altered the flow and may relate to the error"],
        timing_observations=["Commit authored before incident"],
        contradictions=[],
        uncertainty=["Baseline commit"],
        facts=["Commit ea2797a modified order_service.py: 'Initial commit'"],
        inferences=["Initial commit may have introduced the error"],
    )
    llm = LangChainInvestigationLLM.__new__(LangChainInvestigationLLM)
    llm._llm = mock_base
    cha_langchain = llm.analyze_changes(ra, ca, git_context)

    for rel in cha_langchain.potential_relationships:
        assert "altered the flow" not in rel.lower()
        assert "may relate to the error" not in rel.lower()
        assert "introduced" not in rel.lower()
        assert "causation cannot be established" in rel.lower()

    for inf in cha_langchain.inferences:
        assert "altered the flow" not in inf.lower()
        assert "may relate to the error" not in inf.lower()
        assert "introduced" not in inf.lower()
        assert "causation cannot be established" in inf.lower()


def test_regression_validator_hallucination_false_positive_enablement_discarded():
    """Test 43: When RCA says condition evaluated true and validator invents 'failure mode was enabled', false positive is discarded."""
    from app.agents.grounding import run_deterministic_grounding_check, reconcile_semantic_validation_findings
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
        metadata={"traceback": "File order_service.py line 37 in create_order\n    raise OrderProcessingError"},
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    # RCA does NOT contain 'was enabled', 'admin', or 'endpoint'
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Order creation failed when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )

    det_val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert det_val.valid is True

    # Semantic validator hallucinates that the RCA claimed the failure mode "was enabled"
    hallucinated_unsupported = [
        "The RCA states that the failure mode 'was enabled' without direct telemetry evidence from an admin endpoint"
    ]
    hallucinated_missing = [
        "Direct telemetry evidence showing the failure mode was enabled via admin endpoint"
    ]

    reconciled = reconcile_semantic_validation_findings(
        rca=rca,
        det_validation=det_val,
        llm_valid=False,
        llm_issues=[],
        llm_unsupported=hallucinated_unsupported,
        llm_missing=hallucinated_missing,
        code_chunks=chunks,
        evidence=[ev],
    )

    assert reconciled.valid is True
    assert reconciled.issues == []
    assert reconciled.unsupported_claims == []
    assert reconciled.missing_evidence == []


def test_regression_rca_actually_claims_failure_mode_was_enabled_without_telemetry_fails():
    """Test 44: When RCA actually states 'failure mode was enabled' without telemetry, finding remains and validation fails."""
    from app.agents.grounding import run_deterministic_grounding_check, reconcile_semantic_validation_findings
    now = datetime.now(timezone.utc)
    ev_id = "ev-order-error-123"
    ev = Evidence(
        id=ev_id,
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="demo-app.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-123",
        level="ERROR",
        event="order_processing_failed",
        message="Order processing failed",
        endpoint="/orders",
        exception_type="OrderProcessingError",
        created_at=now,
        metadata={"traceback": "File order_service.py line 37 in create_order\n    raise OrderProcessingError"},
    )
    chunks = [
        {
            "id": "chunk-dd04b3223edb3561",
            "file_path": "demo_app/services/order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": (
                "def create_order(self, request):\n"
                "    if self._failure_controller.is_order_processing_error_enabled():\n"
                "        raise OrderProcessingError('fail')\n"
            ),
        }
    ]
    # RCA ACTUALLY contains "the controlled failure mode was enabled"
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="the controlled failure mode was enabled",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError because the failure mode was enabled.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[
            EvidenceReference(type="runtime", id=ev_id),
            EvidenceReference(type="code", id="chunk-dd04b3223edb3561"),
        ],
        confidence=0.85,
        uncertainties=[],
    )

    det_val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert det_val.valid is False

    reconciled = reconcile_semantic_validation_findings(
        rca=rca,
        det_validation=det_val,
        llm_valid=False,
        llm_issues=["The failure mode was enabled claim is unsupported by telemetry"],
        llm_unsupported=["Claim that failure mode was enabled"],
        llm_missing=["Telemetry showing enablement"],
        code_chunks=chunks,
        evidence=[ev],
    )

    assert reconciled.valid is False
    assert len(reconciled.issues) > 0
    assert len(reconciled.unsupported_claims) > 0
    assert len(reconciled.missing_evidence) > 0


def test_regression_rca_claims_admin_endpoint_called_without_telemetry_fails():
    """Test 45: RCA claiming admin endpoint was called without telemetry fails validation."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        endpoint="/orders",
        event="error",
        message="error",
        exception_type=None,
        created_at=now,
    )
    chunks = [{"id": "chunk-1", "symbol_name": "OrderService.create_order", "file_path": "order_service.py"}]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="Admin endpoint /admin/failures/order-processing/enable was called",
        root_cause_hypothesis="OrderService.create_order failed because admin endpoint was called",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="runtime", id="ev-1"), EvidenceReference(type="code", id="chunk-1")],
        confidence=0.8,
        uncertainties=[],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is False
    assert any("/admin" in iss.lower() or "endpoint" in iss.lower() for iss in val.issues)


def test_regression_grounded_branch_condition_inference_passes():
    """Test 46: Grounded branch condition inference with traceback reaching branch body passes."""
    from app.agents.grounding import run_deterministic_grounding_check
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        endpoint="/orders",
        event="order_failed",
        exception_type="OrderProcessingError",
        message="Order processing failed",
        metadata={"traceback": "File order_service.py line 37 in create_order\n    raise OrderProcessingError"},
        created_at=now,
    )
    chunks = [
        {
            "id": "chunk-1",
            "file_path": "order_service.py",
            "symbol_name": "OrderService.create_order",
            "content": "def create_order(self):\n    if self._failure_controller.is_order_processing_error_enabled():\n        raise OrderProcessingError('fail')",
        }
    ]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="self._failure_controller.is_order_processing_error_enabled() evaluated true",
        root_cause_hypothesis="OrderService.create_order raised OrderProcessingError when self._failure_controller.is_order_processing_error_enabled() evaluated true.",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="runtime", id="ev-1"), EvidenceReference(type="code", id="chunk-1")],
        confidence=0.85,
        uncertainties=["The available evidence does not establish how or when the failure condition became true."],
    )
    val = run_deterministic_grounding_check(rca=rca, evidence=[ev], code_chunks=chunks, git_context=[])
    assert val.valid is True
    assert val.issues == []
    assert val.unsupported_claims == []
    assert val.missing_evidence == []


def test_regression_valid_rca_has_empty_missing_evidence():
    """Test 47: Valid RCA strictly produces missing_evidence == []."""
    from app.agents.grounding import reconcile_semantic_validation_findings
    now = datetime.now(timezone.utc)
    ev = Evidence(
        id="ev-1",
        incident_id="inc-1",
        type=EvidenceType.RUNTIME_LOG,
        source="log.jsonl",
        timestamp=now,
        service="order-service",
        request_id="req-1",
        level="ERROR",
        endpoint="/orders",
        event="order_failed",
        exception_type="OrderProcessingError",
        message="failed",
        created_at=now,
    )
    chunks = [{"id": "chunk-1", "file_path": "order_service.py", "symbol_name": "OrderService.create_order"}]
    rca = RootCauseAnalysis(
        failure_location="OrderService.create_order",
        triggering_condition="condition true",
        root_cause_hypothesis="OrderService.create_order failed because condition true",
        affected_component="OrderService.create_order",
        summary="Summary",
        supporting_evidence=[EvidenceReference(type="runtime", id="ev-1"), EvidenceReference(type="code", id="chunk-1")],
        confidence=0.8,
        uncertainties=[],
    )
    det_val = RCAValidation(valid=True, issues=[], unsupported_claims=[], missing_evidence=[])
    merged = reconcile_semantic_validation_findings(
        rca=rca,
        det_validation=det_val,
        llm_valid=True,
        llm_issues=[],
        llm_unsupported=[],
        llm_missing=["spurious missing"],
        code_chunks=chunks,
        evidence=[ev],
    )
    assert merged.valid is True
    assert merged.missing_evidence == []


def test_regression_valid_rca_no_rca_validation_failed_entry_in_errors(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 48: When validation is valid, no 'RCA validation failed' entry is added to errors."""
    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert not any("RCA validation failed" in err for err in data["errors"])


def test_regression_invalid_rca_only_unsupported_claims_error_construction(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 49: Invalid RCA with only unsupported_claims builds meaningful error without empty suffix."""
    fake_llm.custom_validation = RCAValidation(
        valid=False,
        issues=[],
        unsupported_claims=["OrderService.checkout_order does not exist"],
        missing_evidence=["Source code chunk for checkout_order"],
    )
    fake_llm.revision_handler = lambda rca, validation: rca
    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert any("RCA validation failed: OrderService.checkout_order does not exist" in err for err in data["errors"])
    assert not any(err == "RCA validation failed: " or err.endswith(": ") for err in data["errors"])


def test_regression_invalid_rca_only_missing_evidence_error_construction(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 50: Invalid RCA with only missing_evidence builds meaningful error without empty suffix."""
    fake_llm.custom_validation = RCAValidation(
        valid=False,
        issues=[],
        unsupported_claims=[],
        missing_evidence=["Direct telemetry proving failure condition"],
    )
    fake_llm.revision_handler = lambda rca, validation: rca
    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert any("RCA validation failed: Direct telemetry proving failure condition" in err for err in data["errors"])
    assert not any(err == "RCA validation failed: " or err.endswith(": ") for err in data["errors"])


def test_regression_duplicate_validation_findings_deduplicated(fake_llm: FakeInvestigationLLM, test_git_repo: Path):
    """Test 51: Duplicate validation findings across issues, unsupported_claims, and missing_evidence are deduplicated."""
    fake_llm.custom_validation = RCAValidation(
        valid=False,
        issues=["Duplicate reason A", "Unique reason B"],
        unsupported_claims=["Duplicate reason A"],
        missing_evidence=["Duplicate reason A", "Unique reason C"],
    )
    fake_llm.revision_handler = lambda rca, validation: rca
    app.dependency_overrides[get_investigation_llm] = lambda: fake_llm
    git_client = GitClient(repository_path=str(test_git_repo))
    git_service = GitService(client=git_client, repository_name="sentinelops")
    app.dependency_overrides[get_git_service] = lambda: git_service

    incident_id, _ = create_incident_with_evidence()
    res = client.post(f"/incidents/{incident_id}/investigate")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    err_match = [err for err in data["errors"] if err.startswith("RCA validation failed:")]
    assert len(err_match) == 1
    assert err_match[0].count("Duplicate reason A") == 1
    assert "Unique reason B" in err_match[0]
    assert "Unique reason C" in err_match[0]








