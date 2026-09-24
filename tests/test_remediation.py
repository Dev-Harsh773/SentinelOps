"""Comprehensive tests for Stage 8 Remediation Proposal generation, grounding, and validation."""

import datetime
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional
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
from app.memory.dependencies import reset_memory_repository
from app.remediation.dependencies import (
    get_remediation_llm,
    get_remediation_repository,
    get_remediation_service,
    reset_remediation_repository,
)
from app.remediation.llm import FakeRemediationLLM
from app.remediation.models import (
    ChangeType,
    ProposedChange,
    RemediationProposal,
    RemediationStatus,
    RemediationValidation,
)
from app.remediation.validator import RemediationValidator
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import Evidence, EvidenceType


# =====================================================================
# Fixtures & Setup Helpers
# =====================================================================


@pytest.fixture(autouse=True)
def clean_repositories():
    """Ensure in-memory repositories are cleared before and after each test."""
    reset_memory_repository()
    reset_remediation_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()
    yield
    reset_memory_repository()
    reset_remediation_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def setup_verified_incident_and_investigation(
    incident_id: str = "inc-rem-1",
    investigation_id: str = "inv-rem-1",
    service: str = "order-service",
    target_file: str = "app/orders/service.py",
    symbol_name: str = "OrderService.create_order",
    status: InvestigationStatus = InvestigationStatus.COMPLETED,
    valid_rca: bool = True,
    has_rca: bool = True,
) -> tuple[Incident, Investigation, Evidence]:
    """Helper setting up an incident, attached runtime evidence, and an investigation entity."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Incident
    incident = Incident(
        id=incident_id,
        title=f"Failure in {service}",
        service=service,
        environment="production",
        severity=Severity.HIGH,
        status=IncidentStatus.INVESTIGATING,
        summary=f"Orders failing in {service}",
        created_at=now,
        updated_at=now,
    )
    get_incident_repository().create(incident)

    # 2. Runtime Evidence
    evidence_id = str(uuid.uuid4())
    evidence = Evidence(
        id=evidence_id,
        incident_id=incident_id,
        type=EvidenceType.RUNTIME_LOG,
        source="demo_app.jsonl",
        timestamp=now,
        service=service,
        request_id="req-rem-123",
        level="ERROR",
        event="order_creation_failed",
        message="OrderProcessingError: payment timeout",
        endpoint="/api/v1/orders",
        exception_type="OrderProcessingError",
        created_at=now,
    )
    get_evidence_repository().create(evidence)

    # 3. Investigation
    rca = None
    if has_rca:
        rca = RootCauseAnalysis(
            failure_location=symbol_name,
            triggering_condition="is_order_processing_error_enabled() evaluated true",
            root_cause_hypothesis=f"{symbol_name} raised OrderProcessingError",
            affected_component=symbol_name,
            summary="Controlled failure mode triggered error",
            supporting_evidence=[
                EvidenceReference(type="runtime", id=evidence_id, description="Observed error log"),
                EvidenceReference(type="code", id="chunk-rem-1", description="Source code chunk"),
            ],
            confidence=0.85,
        )

    validation = RCAValidation(
        valid=valid_rca,
        issues=[] if valid_rca else ["Ungrounded causal claim"],
        unsupported_claims=[] if valid_rca else ["Ungrounded claim"],
        missing_evidence=[],
    )

    investigation = Investigation(
        investigation_id=investigation_id,
        incident_id=incident_id,
        status=status,
        created_at=now,
        completed_at=now,
        runtime_analysis=RuntimeAnalysis(
            service=service,
            endpoint="/api/v1/orders",
            exception_type="OrderProcessingError",
            important_messages=["Payment timeout"],
            observed_failures=["OrderProcessingError raised"],
        ),
        code_results=[
            {
                "id": "chunk-rem-1",
                "file_path": target_file,
                "symbol_name": symbol_name,
                "symbol_type": "method",
                "start_line": 10,
                "end_line": 25,
                "content": f"class OrderService:\n    def create_order(): raise OrderProcessingError()",
                "score": 0.95,
            }
        ],
        code_analysis=CodeAnalysis(
            relevant_symbols=[symbol_name],
            relevant_files=[target_file],
        ),
        git_context=[
            {
                "file_path": target_file,
                "commits": [
                    {
                        "commit_hash": "a1b2c3d4e5f67890",
                        "short_hash": "a1b2c3d",
                        "author_name": "Developer",
                        "committed_at": now.isoformat(),
                        "message": "Initial implementation of OrderService",
                    }
                ],
            }
        ],
        rca=rca,
        validation=validation,
    )
    get_investigation_repository().save(investigation)

    return incident, investigation, evidence


# =====================================================================
# Unit Tests: Eligibility Enforcement
# =====================================================================


def test_remediation_eligible_completed_investigation(client: TestClient):
    """Valid completed investigation successfully generates a validated remediation proposal."""
    setup_verified_incident_and_investigation("inc-elig-1")

    resp = client.post("/incidents/inc-elig-1/remediation")
    assert resp.status_code == 200
    data = resp.json()

    assert data["incident_id"] == "inc-elig-1"
    assert data["status"] == "validated"
    assert len(data["proposed_changes"]) >= 1
    assert data["target_files"] == ["app/orders/service.py"]
    assert data["target_symbols"] == ["OrderService.create_order"]
    assert len(data["rationale"]) >= 20
    assert len(data["risks"]) >= 1
    assert len(data["validation_steps"]) >= 1
    assert len(data["evidence_references"]) >= 1
    assert data["validation"]["valid"] is True


def test_remediation_rejected_for_failed_investigation(client: TestClient):
    """Investigation with status FAILED cannot produce a remediation proposal (HTTP 409)."""
    setup_verified_incident_and_investigation(
        "inc-fail-1",
        status=InvestigationStatus.FAILED,
        valid_rca=False,
    )

    resp = client.post("/incidents/inc-fail-1/remediation")
    assert resp.status_code == 409
    assert "status is 'failed'" in resp.json()["detail"]


def test_remediation_rejected_for_invalid_rca(client: TestClient):
    """Investigation with valid=False RCA validation cannot produce a remediation proposal (HTTP 409)."""
    setup_verified_incident_and_investigation(
        "inc-inval-1",
        status=InvestigationStatus.COMPLETED,
        valid_rca=False,
    )

    resp = client.post("/incidents/inc-inval-1/remediation")
    assert resp.status_code == 409
    assert "evidence grounding validation" in resp.json()["detail"]


def test_remediation_rejected_for_missing_rca(client: TestClient):
    """Investigation with rca=None cannot produce a remediation proposal (HTTP 409)."""
    setup_verified_incident_and_investigation(
        "inc-norca-1",
        has_rca=False,
        valid_rca=False,
    )

    resp = client.post("/incidents/inc-norca-1/remediation")
    assert resp.status_code == 409
    assert "no synthesized Root Cause Analysis" in resp.json()["detail"]


def test_remediation_not_found_for_uninvestigated_incident(client: TestClient):
    """Incident without an investigation returns HTTP 404."""
    inc = Incident(
        id="inc-uninv-1",
        title="Uninvestigated",
        service="order-service",
        environment="prod",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        summary="No investigation",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    get_incident_repository().create(inc)

    resp = client.post("/incidents/inc-uninv-1/remediation")
    assert resp.status_code == 404


def test_remediation_not_found_for_nonexistent_incident(client: TestClient):
    """Non-existent incident returns HTTP 404."""
    resp = client.post("/incidents/inc-does-not-exist/remediation")
    assert resp.status_code == 404


# =====================================================================
# Unit Tests: Grounding & Evidence Provenance Validator
# =====================================================================


def test_validator_rejects_unretrieved_repository_file():
    """A real file that was never retrieved in the current investigation fails grounding."""
    validator = RemediationValidator()
    _, inv, ev = setup_verified_incident_and_investigation()

    proposal = RemediationProposal(
        remediation_id="rem-test",
        incident_id="inc-rem-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Fix unrelated file",
        target_files=["app/unrelated/worker.py"],  # Never retrieved!
        target_symbols=[],
        proposed_changes=[
            ProposedChange(
                file_path="app/unrelated/worker.py",
                change_type=ChangeType.MODIFY,
                description="Modify unretrieved file",
                reason="Unrelated change",
            )
        ],
        rationale="Substantive causal explanation for the proposal.",
        risks=["Low risk."],
        validation_steps=["Run test suite."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Runtime error"),
            EvidenceReference(type="code", id="chunk-rem-1", description="Chunk"),
        ],
    )

    report = validator.validate(
        proposal=proposal,
        investigation=inv,
        runtime_evidence=[ev],
        code_chunks=inv.code_results,
        git_context=inv.git_context,
    )

    assert report.valid is False
    assert "app/unrelated/worker.py" in report.unsupported_files
    assert any("not retrieved in the current investigation" in i for i in report.issues)


def test_validator_allows_configuration_proposal_without_symbol():
    """A configuration-style proposal targeting a retrieved file may legitimately omit symbol."""
    validator = RemediationValidator()
    _, inv, ev = setup_verified_incident_and_investigation()

    proposal = RemediationProposal(
        remediation_id="rem-config",
        incident_id="inc-rem-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Toggle configuration flag in service",
        target_files=["app/orders/service.py"],
        target_symbols=[],  # No symbol
        proposed_changes=[
            ProposedChange(
                file_path="app/orders/service.py",
                change_type=ChangeType.CONFIGURATION,
                description="Disable faulty flag in configuration block",
                reason="Prevents triggering condition from evaluating true",
                symbol=None,  # Legitimate omission
            )
        ],
        rationale="Toggling configuration flag prevents exception branch from executing.",
        risks=["Minimal operational impact."],
        validation_steps=["Verify service configuration on startup."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Runtime error"),
            EvidenceReference(type="code", id="chunk-rem-1", description="Chunk"),
        ],
    )

    report = validator.validate(
        proposal=proposal,
        investigation=inv,
        runtime_evidence=[ev],
        code_chunks=inv.code_results,
        git_context=inv.git_context,
    )

    assert report.valid is True
    assert len(report.unsupported_symbols) == 0
    assert len(report.issues) == 0


def test_validator_rejects_historical_incident_ids_in_evidence_references():
    """Historical incident IDs (e.g. inc-past-123) cannot masquerade as current grounding evidence."""
    validator = RemediationValidator()
    _, inv, ev = setup_verified_incident_and_investigation()

    proposal = RemediationProposal(
        remediation_id="rem-hist-leak",
        incident_id="inc-rem-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Proposal citing historical incident ID",
        target_files=["app/orders/service.py"],
        target_symbols=["OrderService.create_order"],
        proposed_changes=[
            ProposedChange(
                file_path="app/orders/service.py",
                change_type=ChangeType.MODIFY,
                description="Modify logic",
                reason="Fix error",
                symbol="OrderService.create_order",
            )
        ],
        rationale="Substantive causal explanation for the proposal.",
        risks=["Low risk."],
        validation_steps=["Run unit tests."],
        evidence_references=[
            EvidenceReference(type="runtime", id="inc-past-999", description="Past incident cited as evidence"),
        ],
    )

    report = validator.validate(
        proposal=proposal,
        investigation=inv,
        runtime_evidence=[ev],
        code_chunks=inv.code_results,
        git_context=inv.git_context,
    )

    assert report.valid is False
    assert any("refers to historical incident data" in i for i in report.issues)


# =====================================================================
# Unit Tests: Idempotency Across Re-Investigation
# =====================================================================


def test_idempotency_same_investigation_returns_existing_proposal(client: TestClient):
    """Calling POST repeatedly with the same investigation_id and regenerate=False returns identical proposal."""
    setup_verified_incident_and_investigation("inc-idem-1", "inv-idem-1")

    resp1 = client.post("/incidents/inc-idem-1/remediation")
    assert resp1.status_code == 200
    data1 = resp1.json()

    resp2 = client.post("/incidents/inc-idem-1/remediation")
    assert resp2.status_code == 200
    data2 = resp2.json()

    # Identical proposal returned idempotently
    assert data1["remediation_id"] == data2["remediation_id"]
    assert data1["created_at"] == data2["created_at"]
    assert data1["updated_at"] == data2["updated_at"]


def test_idempotency_regenerate_true_refreshes_in_place(client: TestClient):
    """Calling POST with same investigation_id and regenerate=True preserves remediation_id and created_at while refreshing updated_at."""
    setup_verified_incident_and_investigation("inc-regen-1", "inv-regen-1")

    resp1 = client.post("/incidents/inc-regen-1/remediation")
    assert resp1.status_code == 200
    data1 = resp1.json()

    resp2 = client.post("/incidents/inc-regen-1/remediation?regenerate=true")
    assert resp2.status_code == 200
    data2 = resp2.json()

    assert data1["remediation_id"] == data2["remediation_id"]
    assert data1["created_at"] == data2["created_at"]
    # updated_at refreshed
    assert data2["updated_at"] >= data1["updated_at"]


def test_newer_investigation_automatically_generates_fresh_remediation(client: TestClient):
    """When an incident is re-investigated (newer investigation_id), POST generates a fresh proposal even if regenerate=False."""
    # Investigation A
    setup_verified_incident_and_investigation("inc-reinv-1", "inv-original-A")
    resp_A = client.post("/incidents/inc-reinv-1/remediation")
    assert resp_A.status_code == 200
    data_A = resp_A.json()
    assert data_A["investigation_id"] == "inv-original-A"

    # Re-investigation B on same incident produces newer investigation
    setup_verified_incident_and_investigation("inc-reinv-1", "inv-newer-B")

    resp_B = client.post("/incidents/inc-reinv-1/remediation")
    assert resp_B.status_code == 200
    data_B = resp_B.json()

    # Must NOT return stale remediation from Investigation A
    assert data_B["investigation_id"] == "inv-newer-B"
    assert data_B["remediation_id"] != data_A["remediation_id"]


# =====================================================================
# Unit Tests: Validation Failure Details & Bounded Revision
# =====================================================================


def test_validation_failure_details_are_persisted_and_api_visible(client: TestClient):
    """When validation fails after revision, proposal is persisted as FAILED_VALIDATION with full validation details."""
    setup_verified_incident_and_investigation("inc-valfail-1")

    # Override FakeRemediationLLM to deliberately return ungrounded target files
    fake_llm = FakeRemediationLLM()

    invalid_proposal = RemediationProposal(
        remediation_id=str(uuid.uuid4()),
        incident_id="inc-valfail-1",
        investigation_id="inv-rem-1",
        status=RemediationStatus.DRAFT,
        summary="Ungrounded proposal",
        target_files=["nonexistent/ghost_file.py"],
        target_symbols=["GhostSymbol"],
        proposed_changes=[
            ProposedChange(
                file_path="nonexistent/ghost_file.py",
                change_type=ChangeType.MODIFY,
                description="Change ghost file",
                reason="Fix ghost issue",
                symbol="GhostSymbol",
            )
        ],
        rationale="Substantive causal explanation for the proposal.",
        risks=["Unknown risks."],
        validation_steps=["Test everything."],
        evidence_references=[],
    )

    fake_llm.custom_proposal = invalid_proposal
    fake_llm.custom_revision = invalid_proposal  # Revision also fails
    app.dependency_overrides[get_remediation_llm] = lambda: fake_llm

    try:
        resp = client.post("/incidents/inc-valfail-1/remediation")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "failed_validation"
        assert data["validation"] is not None
        assert data["validation"]["valid"] is False
        assert "nonexistent/ghost_file.py" in data["validation"]["unsupported_files"]
        assert "GhostSymbol" in data["validation"]["unsupported_symbols"]
        assert len(data["validation"]["issues"]) > 0
    finally:
        app.dependency_overrides.pop(get_remediation_llm, None)


def test_bounded_revision_recovers_from_initial_validation_failure(client: TestClient):
    """Proposal failing initial validation triggers 1 bounded revision and passes if revised successfully."""
    _, inv, ev = setup_verified_incident_and_investigation("inc-recov-1")

    fake_llm = FakeRemediationLLM()

    # Initial proposal has unretrieved file
    bad_proposal = RemediationProposal(
        remediation_id="rem-initial-bad",
        incident_id="inc-recov-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Bad proposal",
        target_files=["unretrieved_file.py"],
        target_symbols=[],
        proposed_changes=[
            ProposedChange(
                file_path="unretrieved_file.py",
                change_type=ChangeType.MODIFY,
                description="Change unretrieved",
                reason="Causal reason",
            )
        ],
        rationale="Substantive causal explanation for the proposal.",
        risks=["Low risk."],
        validation_steps=["Run tests."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Runtime log"),
        ],
    )
    fake_llm.custom_proposal = bad_proposal

    # Revision handler fixes the target file to the valid retrieved chunk file
    def revision_fix(**kwargs):
        return RemediationProposal(
            remediation_id="rem-initial-bad",
            incident_id="inc-recov-1",
            investigation_id=inv.investigation_id,
            status=RemediationStatus.VALIDATED,
            summary="Clean proposal",
            target_files=["app/orders/service.py"],
            target_symbols=["OrderService.create_order"],
            proposed_changes=[
                ProposedChange(
                    file_path="app/orders/service.py",
                    change_type=ChangeType.MODIFY,
                    description="Defensive check",
                    reason="Fixes triggering condition",
                    symbol="OrderService.create_order",
                )
            ],
            rationale="Substantive causal explanation for the proposal.",
            risks=["Low risk."],
            validation_steps=["Run test suite."],
            evidence_references=[
                EvidenceReference(type="runtime", id=ev.id, description="Runtime log"),
                EvidenceReference(type="code", id="chunk-rem-1", description="Chunk"),
            ],
        )

    fake_llm.revision_handler = revision_fix
    app.dependency_overrides[get_remediation_llm] = lambda: fake_llm

    try:
        resp = client.post("/incidents/inc-recov-1/remediation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "validated"
        assert data["target_files"] == ["app/orders/service.py"]
        assert data["validation"]["valid"] is True
    finally:
        app.dependency_overrides.pop(get_remediation_llm, None)


# =====================================================================
# Unit Tests: Non-Mutation Invariant & Pre-Existing Dirty Working Tree
# =====================================================================


def test_remediation_generation_causes_zero_repository_mutations(client: TestClient):
    """Proposal-only safety invariant: generating remediation causes NO file writes, NO branch creations, NO commits."""
    setup_verified_incident_and_investigation("inc-mut-1")

    # Snapshot git status before
    status_before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout

    resp = client.post("/incidents/inc-mut-1/remediation")
    assert resp.status_code == 200

    # Snapshot git status after
    status_after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout

    # The working tree delta must be exactly identical (zero mutation)
    assert status_after == status_before


def test_preexisting_dirty_working_tree_does_not_invalidate_remediation(client: TestClient):
    """Remediation validation succeeds even if the Git repository already has unrelated pre-existing uncommitted changes."""
    setup_verified_incident_and_investigation("inc-dirty-1")

    resp = client.post("/incidents/inc-dirty-1/remediation")
    assert resp.status_code == 200
    assert resp.json()["status"] == "validated"


# =====================================================================
# Unit Tests: API Endpoints (GET /incidents/{incident_id}/remediation)
# =====================================================================


def test_get_remediation_endpoint(client: TestClient):
    setup_verified_incident_and_investigation("inc-get-1")

    # Before generation -> 404
    get_before = client.get("/incidents/inc-get-1/remediation")
    assert get_before.status_code == 404

    # Generate
    client.post("/incidents/inc-get-1/remediation")

    # After generation -> 200 with proposal
    get_after = client.get("/incidents/inc-get-1/remediation")
    assert get_after.status_code == 200
    assert get_after.json()["incident_id"] == "inc-get-1"
    assert get_after.json()["status"] == "validated"


# =====================================================================
# Regression Tests: Redundant Modify on Controls vs Operational Mitigation
# =====================================================================


def test_validator_rejects_redundant_modify_proposal_on_existing_disable_control():
    """A remediation targeting disable_order_processing_failure with a proposal to add disabling behavior
    must not be accepted as a valid source-code modification."""
    validator = RemediationValidator()
    _, inv, ev = setup_verified_incident_and_investigation()

    admin_chunk = {
        "id": "chunk-admin-disable",
        "file_path": "demo_app/api/admin.py",
        "symbol_name": "disable_order_processing_failure",
        "symbol_type": "function",
        "start_line": 49,
        "end_line": 71,
        "content": (
            "def disable_order_processing_failure(request: Request, controller: FailureModeController = Depends(get_failure_controller)):\n"
            "    controller.disable_order_processing_error()\n"
            "    event_logger.emit_event(level='INFO', event='failure_mode_disabled')\n"
            "    return {'order_processing_error': False}\n"
        ),
    }
    all_chunks = inv.code_results + [admin_chunk]

    proposal = RemediationProposal(
        remediation_id="rem-bad-admin-mod",
        incident_id="inc-rem-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Redundant modify proposal on admin endpoint",
        target_files=["demo_app/api/admin.py"],
        target_symbols=["disable_order_processing_failure"],
        proposed_changes=[
            ProposedChange(
                file_path="demo_app/api/admin.py",
                change_type=ChangeType.MODIFY,
                description="Add a call to disable the order processing error mode before creating an order.",
                reason="Disables the failure mode.",
                symbol="disable_order_processing_failure",
            )
        ],
        rationale="Calling disable prevents the failure condition from triggering.",
        risks=["Low risk."],
        validation_steps=["Verify admin endpoint."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Observed error log"),
            EvidenceReference(type="code", id="chunk-admin-disable", description="Admin disable chunk"),
        ],
    )

    report = validator.validate(
        proposal=proposal,
        investigation=inv,
        runtime_evidence=[ev],
        code_chunks=all_chunks,
        git_context=inv.git_context,
    )

    assert report.valid is False
    assert "disable_order_processing_failure" in report.unsupported_symbols
    assert any("already implements disabling behavior" in i for i in report.issues)


def test_validator_allows_grounded_operational_configuration_mitigation_on_existing_control():
    """A properly represented configuration/operational mitigation using the existing disable control
    should be allowed if grounded."""
    validator = RemediationValidator()
    _, inv, ev = setup_verified_incident_and_investigation()

    admin_chunk = {
        "id": "chunk-admin-disable",
        "file_path": "demo_app/api/admin.py",
        "symbol_name": "disable_order_processing_failure",
        "symbol_type": "function",
        "start_line": 49,
        "end_line": 71,
        "content": (
            "def disable_order_processing_failure(request: Request, controller: FailureModeController = Depends(get_failure_controller)):\n"
            "    controller.disable_order_processing_error()\n"
            "    event_logger.emit_event(level='INFO', event='failure_mode_disabled')\n"
            "    return {'order_processing_error': False}\n"
        ),
    }
    all_chunks = inv.code_results + [admin_chunk]

    proposal = RemediationProposal(
        remediation_id="rem-good-admin-config",
        incident_id="inc-rem-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Operational mitigation via existing disable control",
        target_files=["demo_app/api/admin.py"],
        target_symbols=["disable_order_processing_failure"],
        proposed_changes=[
            ProposedChange(
                file_path="demo_app/api/admin.py",
                change_type=ChangeType.CONFIGURATION,
                description="Invoke the existing admin endpoint /admin/failures/order-processing/disable to deactivate the active failure mode.",
                reason="Deactivates the active failure toggle causing OrderProcessingError.",
                symbol="disable_order_processing_failure",
            )
        ],
        rationale="Invoking the existing administrative disable endpoint safely turns off the simulated fault condition.",
        risks=["Operational impact: failure mode is turned off for the environment."],
        validation_steps=["Issue POST /admin/failures/order-processing/disable and verify HTTP 200 response."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Observed error log"),
            EvidenceReference(type="code", id="chunk-admin-disable", description="Admin disable chunk"),
        ],
    )

    report = validator.validate(
        proposal=proposal,
        investigation=inv,
        runtime_evidence=[ev],
        code_chunks=all_chunks,
        git_context=inv.git_context,
    )

    assert report.valid is True
    assert len(report.issues) == 0
    assert len(report.unsupported_symbols) == 0


def test_bounded_revision_recovers_redundant_admin_modify_to_valid_configuration_mitigation(client: TestClient):
    """When an initial proposal incorrectly attempts a MODIFY on an existing disable control,
    bounded revision successfully recovers it to a valid CONFIGURATION change."""
    _, inv, ev = setup_verified_incident_and_investigation("inc-rev-admin-1")

    admin_chunk = {
        "id": "chunk-admin-disable",
        "file_path": "demo_app/api/admin.py",
        "symbol_name": "disable_order_processing_failure",
        "symbol_type": "function",
        "start_line": 49,
        "end_line": 71,
        "content": (
            "def disable_order_processing_failure(request: Request, controller: FailureModeController = Depends(get_failure_controller)):\n"
            "    controller.disable_order_processing_error()\n"
            "    event_logger.emit_event(level='INFO', event='failure_mode_disabled')\n"
            "    return {'order_processing_error': False}\n"
        ),
    }
    inv.code_results.append(admin_chunk)
    inv.code_analysis.relevant_files.append("demo_app/api/admin.py")
    inv.code_analysis.relevant_symbols.append("disable_order_processing_failure")
    get_investigation_repository().save(inv)

    fake_llm = FakeRemediationLLM()

    bad_proposal = RemediationProposal(
        remediation_id="rem-initial-redundant",
        incident_id="inc-rev-admin-1",
        investigation_id=inv.investigation_id,
        status=RemediationStatus.DRAFT,
        summary="Redundant modify proposal",
        target_files=["demo_app/api/admin.py"],
        target_symbols=["disable_order_processing_failure"],
        proposed_changes=[
            ProposedChange(
                file_path="demo_app/api/admin.py",
                change_type=ChangeType.MODIFY,
                description="Add a call to disable the order processing error mode before creating an order.",
                reason="Disables the failure mode.",
                symbol="disable_order_processing_failure",
            )
        ],
        rationale="Substantive causal explanation for the proposal.",
        risks=["Low risk."],
        validation_steps=["Run test suite."],
        evidence_references=[
            EvidenceReference(type="runtime", id=ev.id, description="Runtime log"),
            EvidenceReference(type="code", id="chunk-admin-disable", description="Admin chunk"),
        ],
    )
    fake_llm.custom_proposal = bad_proposal

    app.dependency_overrides[get_remediation_llm] = lambda: fake_llm

    try:
        resp = client.post("/incidents/inc-rev-admin-1/remediation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "validated"
        assert data["proposed_changes"][0]["change_type"] == "configuration"
        assert data["validation"]["valid"] is True
    finally:
        app.dependency_overrides.pop(get_remediation_llm, None)

