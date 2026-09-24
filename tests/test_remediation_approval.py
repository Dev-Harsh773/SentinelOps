"""Comprehensive tests for Stage 9 Human Approval and Isolated Git Branch creation."""

import datetime
from pathlib import Path
import subprocess
from typing import Tuple
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents.dependencies import get_investigation_repository
from app.agents.models import (
    CodeAnalysis,
    EvidenceReference,
    Investigation,
    InvestigationStatus,
    RCAValidation,
    RootCauseAnalysis,
    RuntimeAnalysis,
)
from app.common.config import config
from app.incidents.dependencies import get_incident_repository
from app.incidents.models import Incident, IncidentStatus, Severity
from app.main import app
from app.memory.dependencies import reset_memory_repository
from app.remediation.dependencies import (
    get_git_branch_manager,
    get_remediation_repository,
    reset_branch_repository,
    reset_remediation_repository,
    reset_review_repository,
)
from app.remediation.models import (
    ChangeType,
    ProposedChange,
    RemediationIneligibleError,
    RemediationNotFoundError,
    RemediationProposal,
    RemediationReviewCreateSchema,
    RemediationReviewError,
    RemediationStatus,
    RemediationValidation,
    ReviewDecision,
)
from app.remediation.repository import InMemoryRemediationRepository
from app.repository.branch_manager import GitBranchManager
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import Evidence, EvidenceType


# =====================================================================
# Fixtures & Helpers
# =====================================================================


@pytest.fixture(autouse=True)
def clean_repositories():
    """Ensure all in-memory repositories are cleared before and after each test."""
    reset_memory_repository()
    reset_remediation_repository()
    reset_review_repository()
    reset_branch_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()
    yield
    reset_memory_repository()
    reset_remediation_repository()
    reset_review_repository()
    reset_branch_repository()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_investigation_repository().clear()


@pytest.fixture(autouse=True)
def cleanup_dependency_overrides():
    """Ensure FastAPI dependency overrides are cleared after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Tuple[Path, GitBranchManager]:
    """Creates a temporary, fully initialized Git repository on 'main' branch."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)

    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_dir, check=True, capture_output=True)

    manager = GitBranchManager(repository_path=str(repo_dir), base_branch="main")
    return repo_dir, manager


def setup_verified_incident_and_investigation(
    incident_id: str = "inc-appr-1",
    investigation_id: str = "inv-appr-1",
    service: str = "order-service",
    target_file: str = "demo_app/api/orders.py",
    symbol_name: str = "create_order",
    status: InvestigationStatus = InvestigationStatus.COMPLETED,
    valid_rca: bool = True,
    has_rca: bool = True,
) -> Tuple[Incident, Investigation, Evidence]:
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
        request_id="req-appr-123",
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
                EvidenceReference(type="code", id="chunk-appr-1", description="Source code chunk"),
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
                "id": "chunk-appr-1",
                "file_path": target_file,
                "symbol_name": symbol_name,
                "symbol_type": "function",
                "start_line": 10,
                "end_line": 25,
                "content": "def create_order(): raise OrderProcessingError()",
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
                        "message": "Implement order creation logic",
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
# Stage 9 Tests
# =====================================================================


def test_remediation_repository_preserves_historical_proposals_by_id_across_regeneration():
    """InMemoryRemediationRepository must preserve previous proposals by remediation_id when active proposal updates."""
    repo = InMemoryRemediationRepository()
    now = datetime.datetime.now(datetime.timezone.utc)

    prop_a = RemediationProposal(
        remediation_id="rem-prop-a",
        incident_id="inc-1",
        investigation_id="inv-1",
        status=RemediationStatus.REJECTED,
        summary="Proposal A summary",
        target_files=["demo_app/api/orders.py"],
        target_symbols=["create_order"],
        proposed_changes=[],
        rationale="Rationale A",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        created_at=now,
        updated_at=now,
    )
    repo.save(prop_a)

    prop_b = RemediationProposal(
        remediation_id="rem-prop-b",
        incident_id="inc-1",
        investigation_id="inv-1",
        status=RemediationStatus.VALIDATED,
        summary="Proposal B summary",
        target_files=["demo_app/api/orders.py"],
        target_symbols=["create_order"],
        proposed_changes=[],
        rationale="Rationale B",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        created_at=now + datetime.timedelta(seconds=1),
        updated_at=now + datetime.timedelta(seconds=1),
    )
    repo.save(prop_b)

    # Active lookup returns latest proposal B
    active = repo.get_by_incident_id("inc-1")
    assert active is not None
    assert active.remediation_id == "rem-prop-b"

    # Direct ID lookup preserves both proposals
    assert repo.get_by_id("rem-prop-a") is not None
    assert repo.get_by_id("rem-prop-a").summary == "Proposal A summary"
    assert repo.get_by_id("rem-prop-b") is not None
    assert repo.get_by_id("rem-prop-b").summary == "Proposal B summary"

    # Incident listing contains both (newest first)
    all_proposals = repo.list_for_incident("inc-1")
    assert len(all_proposals) == 2
    assert [p.remediation_id for p in all_proposals] == ["rem-prop-b", "rem-prop-a"]


def test_validated_remediation_regenerate_preserves_remediation_id(client: TestClient):
    """Regenerating a VALIDATED remediation proposal preserves the same remediation_id (in-place refresh)."""
    setup_verified_incident_and_investigation(incident_id="inc-val-1")

    # Initial generation
    res1 = client.post("/incidents/inc-val-1/remediation")
    assert res1.status_code == 200
    rem_id_1 = res1.json()["remediation_id"]
    assert res1.json()["status"] == "validated"

    # Regeneration while VALIDATED preserves same remediation_id
    res2 = client.post("/incidents/inc-val-1/remediation?regenerate=true")
    assert res2.status_code == 200
    rem_id_2 = res2.json()["remediation_id"]
    assert rem_id_1 == rem_id_2


def test_rejected_remediation_regenerate_creates_new_remediation_id(client: TestClient):
    """Regenerating a REJECTED remediation proposal generates a brand-new remediation_id."""
    setup_verified_incident_and_investigation(incident_id="inc-rej-1")

    # Initial generation
    res1 = client.post("/incidents/inc-rej-1/remediation")
    assert res1.status_code == 200
    rem_id_1 = res1.json()["remediation_id"]

    # Human review: REJECTED
    rev = client.post(
        "/incidents/inc-rej-1/remediation/reviews",
        json={"decision": "rejected", "reviewer": "sec-team", "comment": "Too risky"},
    )
    assert rev.status_code == 201

    # Check active status is rejected
    res_get = client.get("/incidents/inc-rej-1/remediation")
    assert res_get.json()["status"] == "rejected"

    # Regeneration generates new remediation_id
    res2 = client.post("/incidents/inc-rej-1/remediation?regenerate=true")
    assert res2.status_code == 200
    rem_id_2 = res2.json()["remediation_id"]
    assert rem_id_2 != rem_id_1
    assert res2.json()["status"] == "validated"

    # Verify old proposal is still accessible by ID in repo
    repo = get_remediation_repository()
    assert repo.get_by_id(rem_id_1) is not None
    assert repo.get_by_id(rem_id_1).status == RemediationStatus.REJECTED


def test_revision_requested_remediation_regenerate_creates_new_remediation_id(client: TestClient):
    """Regenerating a REVISION_REQUESTED remediation proposal generates a brand-new remediation_id."""
    setup_verified_incident_and_investigation(incident_id="inc-rev-1")

    # Initial generation
    res1 = client.post("/incidents/inc-rev-1/remediation")
    assert res1.status_code == 200
    rem_id_1 = res1.json()["remediation_id"]

    # Human review: REVISION_REQUESTED
    rev = client.post(
        "/incidents/inc-rev-1/remediation/reviews",
        json={"decision": "revision_requested", "reviewer": "qa-lead", "comment": "Add rollback tests"},
    )
    assert rev.status_code == 201

    # Regeneration generates new remediation_id
    res2 = client.post("/incidents/inc-rev-1/remediation?regenerate=true")
    assert res2.status_code == 200
    rem_id_2 = res2.json()["remediation_id"]
    assert rem_id_2 != rem_id_1
    assert res2.json()["status"] == "validated"


def test_approved_remediation_regeneration_refused_with_conflict(client: TestClient):
    """Regenerating an APPROVED remediation proposal must fail with 409 Conflict."""
    setup_verified_incident_and_investigation(incident_id="inc-appr-blk")

    client.post("/incidents/inc-appr-blk/remediation")
    client.post(
        "/incidents/inc-appr-blk/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead-eng", "comment": "Approved for implementation"},
    )

    res = client.post("/incidents/inc-appr-blk/remediation?regenerate=true")
    assert res.status_code == 409
    assert "already approved" in res.json()["detail"].lower()


def test_approve_validated_remediation_succeeds(client: TestClient):
    """Valid human review with 'approved' transitions proposal to APPROVED."""
    setup_verified_incident_and_investigation(incident_id="inc-appr-ok")

    client.post("/incidents/inc-appr-ok/remediation")

    res = client.post(
        "/incidents/inc-appr-ok/remediation/reviews",
        json={"decision": "approved", "reviewer": "oncall-eng", "comment": "Approved"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["decision"] == "approved"
    assert data["reviewer"] == "oncall-eng"
    assert data["incident_id"] == "inc-appr-ok"

    # Status of remediation proposal is updated
    rem_res = client.get("/incidents/inc-appr-ok/remediation")
    assert rem_res.json()["status"] == "approved"


def test_reject_validated_remediation_succeeds(client: TestClient):
    """Valid human review with 'rejected' transitions proposal to REJECTED."""
    setup_verified_incident_and_investigation(incident_id="inc-rej-ok")

    client.post("/incidents/inc-rej-ok/remediation")

    res = client.post(
        "/incidents/inc-rej-ok/remediation/reviews",
        json={"decision": "rejected", "reviewer": "security", "comment": "Violates safety policy"},
    )
    assert res.status_code == 201
    assert res.json()["decision"] == "rejected"

    rem_res = client.get("/incidents/inc-rej-ok/remediation")
    assert rem_res.json()["status"] == "rejected"


def test_rejected_remediation_cannot_later_be_approved(client: TestClient):
    """A REJECTED proposal cannot later be approved directly; must be regenerated."""
    setup_verified_incident_and_investigation(incident_id="inc-term-rej")

    client.post("/incidents/inc-term-rej/remediation")
    client.post(
        "/incidents/inc-term-rej/remediation/reviews",
        json={"decision": "rejected", "reviewer": "alice", "comment": "Nope"},
    )

    res = client.post(
        "/incidents/inc-term-rej/remediation/reviews",
        json={"decision": "approved", "reviewer": "bob", "comment": "I changed my mind"},
    )
    assert res.status_code == 409
    assert "rejected and cannot be approved" in res.json()["detail"].lower()


def test_revision_requested_cannot_later_be_approved_without_regeneration(client: TestClient):
    """A REVISION_REQUESTED proposal cannot later be approved directly without regeneration."""
    setup_verified_incident_and_investigation(incident_id="inc-term-rev")

    client.post("/incidents/inc-term-rev/remediation")
    client.post(
        "/incidents/inc-term-rev/remediation/reviews",
        json={"decision": "revision_requested", "reviewer": "alice", "comment": "Fix typos"},
    )

    res = client.post(
        "/incidents/inc-term-rev/remediation/reviews",
        json={"decision": "approved", "reviewer": "alice", "comment": "Approving anyway"},
    )
    assert res.status_code == 409
    assert "revisions requested" in res.json()["detail"].lower()


def test_regenerated_remediation_receives_fresh_approval(client: TestClient):
    """After rejection, regenerating creates a fresh proposal that can be approved."""
    setup_verified_incident_and_investigation(incident_id="inc-fresh-appr")

    # Proposal A rejected
    client.post("/incidents/inc-fresh-appr/remediation")
    client.post(
        "/incidents/inc-fresh-appr/remediation/reviews",
        json={"decision": "rejected", "reviewer": "alice", "comment": "Too disruptive"},
    )

    # Regenerate Proposal B
    regen_res = client.post("/incidents/inc-fresh-appr/remediation?regenerate=true")
    assert regen_res.status_code == 200
    assert regen_res.json()["status"] == "validated"

    # Proposal B approved
    appr_res = client.post(
        "/incidents/inc-fresh-appr/remediation/reviews",
        json={"decision": "approved", "reviewer": "alice", "comment": "Better approach"},
    )
    assert appr_res.status_code == 201
    assert appr_res.json()["decision"] == "approved"

    rem_res = client.get("/incidents/inc-fresh-appr/remediation")
    assert rem_res.json()["status"] == "approved"


def test_review_history_preserved_across_regeneration(client: TestClient):
    """Full review audit trail is retained across proposal generations."""
    setup_verified_incident_and_investigation(incident_id="inc-hist-1")

    # 1. Proposal A reviewed: revision requested
    res_a = client.post("/incidents/inc-hist-1/remediation")
    rem_id_a = res_a.json()["remediation_id"]
    client.post(
        "/incidents/inc-hist-1/remediation/reviews",
        json={"decision": "revision_requested", "reviewer": "alice", "comment": "Revise step 2"},
    )

    # 2. Proposal B generated and approved
    res_b = client.post("/incidents/inc-hist-1/remediation?regenerate=true")
    rem_id_b = res_b.json()["remediation_id"]
    client.post(
        "/incidents/inc-hist-1/remediation/reviews",
        json={"decision": "approved", "reviewer": "bob", "comment": "Approved step 2"},
    )

    # 3. Retrieve audit trail
    audit_res = client.get("/incidents/inc-hist-1/remediation/reviews")
    assert audit_res.status_code == 200
    reviews = audit_res.json()
    assert len(reviews) == 2

    # Newest first
    assert reviews[0]["decision"] == "approved"
    assert reviews[0]["remediation_id"] == rem_id_b
    assert reviews[0]["reviewer"] == "bob"

    assert reviews[1]["decision"] == "revision_requested"
    assert reviews[1]["remediation_id"] == rem_id_a
    assert reviews[1]["reviewer"] == "alice"


def test_approval_belonging_to_old_remediation_cannot_authorize_new_remediation(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """An approval for Proposal A must never authorize branch creation for Proposal B."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-old-appr")

    # Create Proposal A and approve it
    client.post("/incidents/inc-old-appr/remediation")
    client.post(
        "/incidents/inc-old-appr/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Good"},
    )

    # Suppose a new proposal is somehow in place without approval (e.g. manually saved or refreshed)
    # Let's verify branch creation checks latest review for the ACTIVE proposal
    repo = get_remediation_repository()
    active = repo.get_by_incident_id("inc-old-appr")
    assert active is not None

    # Manually craft Proposal B in VALIDATED status as active
    now = datetime.datetime.now(datetime.timezone.utc)
    prop_b = RemediationProposal(
        remediation_id="rem-b-unapproved",
        incident_id="inc-old-appr",
        investigation_id="inv-appr-1",
        status=RemediationStatus.VALIDATED,
        summary="Proposal B",
        target_files=["demo_app/api/orders.py"],
        target_symbols=["create_order"],
        proposed_changes=[],
        rationale="Rationale",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        created_at=now,
        updated_at=now,
    )
    repo.save(prop_b)

    # Attempt branch creation for inc-old-appr (whose active proposal is now B, which has no review)
    res = client.post("/incidents/inc-old-appr/remediation/branch")
    assert res.status_code == 409
    assert "status is 'validated', expected 'approved'" in res.json()["detail"].lower()


def test_repeated_identical_review_does_not_add_duplicate_audit_record(client: TestClient):
    """Submitting exact identical review payload returns existing review idempotently without new audit record."""
    setup_verified_incident_and_investigation(incident_id="inc-idemp-rev")

    client.post("/incidents/inc-idemp-rev/remediation")

    rev_payload = {
        "decision": "approved",
        "reviewer": "staff-eng",
        "comment": "Approved identical",
    }

    # 1. First submission
    res1 = client.post("/incidents/inc-idemp-rev/remediation/reviews", json=rev_payload)
    assert res1.status_code == 201
    rev1 = res1.json()

    # 2. Exact identical second submission (must be handled BEFORE approved lifecycle check)
    res2 = client.post("/incidents/inc-idemp-rev/remediation/reviews", json=rev_payload)
    assert res2.status_code == 201
    rev2 = res2.json()

    assert rev1["review_id"] == rev2["review_id"]

    # 3. Verify audit trail has only 1 entry
    audit = client.get("/incidents/inc-idemp-rev/remediation/reviews").json()
    assert len(audit) == 1

    # 4. A DIFFERENT review submission now conflicts with APPROVED status
    diff_payload = {
        "decision": "approved",
        "reviewer": "other-eng",
        "comment": "Also approved",
    }
    res3 = client.post("/incidents/inc-idemp-rev/remediation/reviews", json=diff_payload)
    assert res3.status_code == 409


def test_review_rejected_for_failed_validation_proposal(client: TestClient):
    """A proposal that failed validation cannot be reviewed."""
    setup_verified_incident_and_investigation(incident_id="inc-fail-val")

    # Manually seed a proposal in FAILED_VALIDATION
    repo = get_remediation_repository()
    now = datetime.datetime.now(datetime.timezone.utc)
    proposal = RemediationProposal(
        remediation_id="rem-failed",
        incident_id="inc-fail-val",
        investigation_id="inv-appr-1",
        status=RemediationStatus.FAILED_VALIDATION,
        summary="Failed summary",
        target_files=["demo_app/api/orders.py"],
        target_symbols=["create_order"],
        proposed_changes=[],
        rationale="Rationale",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        validation=RemediationValidation(
            valid=False,
            issues=["Ungrounded file"],
            unsupported_files=["demo_app/api/orders.py"],
            unsupported_symbols=[],
            missing_elements=[],
        ),
        created_at=now,
        updated_at=now,
    )
    repo.save(proposal)

    res = client.post(
        "/incidents/inc-fail-val/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approved"},
    )
    assert res.status_code == 409
    assert "failed evidence grounding validation" in res.json()["detail"].lower()


def test_review_rejected_for_stale_remediation_after_new_investigation(client: TestClient):
    """If an incident receives a new investigation after remediation proposal generation, review is rejected."""
    _, inv1, _ = setup_verified_incident_and_investigation(incident_id="inc-stale-rev", investigation_id="inv-1")

    # Generate remediation for inv-1
    client.post("/incidents/inc-stale-rev/remediation")

    # Now create inv-2 for the same incident
    now = datetime.datetime.now(datetime.timezone.utc)
    inv2 = Investigation(
        investigation_id="inv-2",
        incident_id="inc-stale-rev",
        status=InvestigationStatus.COMPLETED,
        created_at=now,
        completed_at=now,
        runtime_analysis=inv1.runtime_analysis,
        code_results=inv1.code_results,
        code_analysis=inv1.code_analysis,
        git_context=inv1.git_context,
        rca=inv1.rca,
        validation=inv1.validation,
    )
    get_investigation_repository().save(inv2)

    res = client.post(
        "/incidents/inc-stale-rev/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approved"},
    )
    assert res.status_code == 409
    assert "stale" in res.json()["detail"].lower()


def test_branch_creation_refuses_when_current_branch_is_not_configured_base_branch(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must be rejected if current Git branch is not configured GIT_BASE_BRANCH."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-base-chk")
    client.post("/incidents/inc-base-chk/remediation")
    client.post(
        "/incidents/inc-base-chk/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approved"},
    )

    # Switch repository away from 'main' to a custom feature branch
    subprocess.run(["git", "checkout", "-b", "feature/other-work"], cwd=repo_dir, check=True, capture_output=True)

    res = client.post("/incidents/inc-base-chk/remediation/branch")
    assert res.status_code == 409
    assert "must be created from configured base branch 'main'" in res.json()["detail"].lower()


def test_branch_creation_rejected_without_prior_approval(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must be rejected if the remediation proposal is not approved."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-no-appr")
    client.post("/incidents/inc-no-appr/remediation")

    res = client.post("/incidents/inc-no-appr/remediation/branch")
    assert res.status_code == 409
    assert "expected 'approved'" in res.json()["detail"].lower()


def test_branch_creation_rejected_if_decision_is_rejected(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must be rejected if proposal was rejected."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-rej-br")
    client.post("/incidents/inc-rej-br/remediation")
    client.post(
        "/incidents/inc-rej-br/remediation/reviews",
        json={"decision": "rejected", "reviewer": "sec", "comment": "No"},
    )

    res = client.post("/incidents/inc-rej-br/remediation/branch")
    assert res.status_code == 409
    assert "expected 'approved'" in res.json()["detail"].lower()


def test_branch_creation_rejected_if_decision_is_revision_requested(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must be rejected if proposal has revisions requested."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-rev-br")
    client.post("/incidents/inc-rev-br/remediation")
    client.post(
        "/incidents/inc-rev-br/remediation/reviews",
        json={"decision": "revision_requested", "reviewer": "eng", "comment": "Revise"},
    )

    res = client.post("/incidents/inc-rev-br/remediation/branch")
    assert res.status_code == 409
    assert "expected 'approved'" in res.json()["detail"].lower()


def test_approved_remediation_creates_and_switches_to_isolated_branch(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Approved remediation creates isolated branch sentinel/incident-<id>-fix and switches to it."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-good-br")
    client.post("/incidents/inc-good-br/remediation")
    rev_res = client.post(
        "/incidents/inc-good-br/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Good to branch"},
    )
    approval_id = rev_res.json()["review_id"]

    res = client.post("/incidents/inc-good-br/remediation/branch")
    assert res.status_code == 201
    branch = res.json()

    expected_branch_name = "sentinel/incident-inc-good-br-fix"
    assert branch["branch_name"] == expected_branch_name
    assert branch["incident_id"] == "inc-good-br"
    assert branch["approval_id"] == approval_id
    assert branch["base_branch"] == "main"
    assert len(branch["base_commit"]) == 40

    # Verify repository is now on the new branch
    assert manager.get_current_branch() == expected_branch_name


def test_branch_naming_is_deterministic_and_sanitized(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch names are sanitized to alphanumeric/hyphens and bounded to 100 characters."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    incident_id = "INC_2026-PROD_Issue.42@Critical"
    setup_verified_incident_and_investigation(incident_id=incident_id)
    client.post(f"/incidents/{incident_id}/remediation")
    client.post(
        f"/incidents/{incident_id}/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve sanitized"},
    )

    res = client.post(f"/incidents/{incident_id}/remediation/branch")
    assert res.status_code == 201
    branch_name = res.json()["branch_name"]

    assert branch_name == "sentinel/incident-inc_2026-prod_issue-42-critical-fix"
    assert len(branch_name) <= 100
    assert "/" not in branch_name[9:]  # only the sentinel/ prefix has a slash


def test_branch_base_sha_equals_configured_base_branch_head(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """The base_commit recorded in the branch entity must match HEAD SHA of main."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    expected_sha = manager.get_head_commit()

    setup_verified_incident_and_investigation(incident_id="inc-sha-chk")
    client.post("/incidents/inc-sha-chk/remediation")
    client.post(
        "/incidents/inc-sha-chk/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve SHA"},
    )

    res = client.post("/incidents/inc-sha-chk/remediation/branch")
    assert res.status_code == 201
    assert res.json()["base_commit"] == expected_sha


def test_repeated_branch_post_returns_existing_record_without_another_checkout(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Repeated branch POST returns existing record idempotently without invoking another git checkout."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-idemp-br")
    client.post("/incidents/inc-idemp-br/remediation")
    client.post(
        "/incidents/inc-idemp-br/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve idemp"},
    )

    # First branch call creates branch and checks it out
    res1 = client.post("/incidents/inc-idemp-br/remediation/branch")
    assert res1.status_code == 201
    branch1 = res1.json()

    # User manually switches back to main
    subprocess.run(["git", "checkout", "main"], cwd=repo_dir, check=True, capture_output=True)
    assert manager.get_current_branch() == "main"

    # Second branch call returns existing record WITHOUT checking out again
    res2 = client.post("/incidents/inc-idemp-br/remediation/branch")
    assert res2.status_code == 201
    branch2 = res2.json()

    assert branch1["branch_id"] == branch2["branch_id"]
    # Working tree stayed on 'main' because no redundant checkout occurred
    assert manager.get_current_branch() == "main"


def test_dirty_working_tree_blocks_branch_creation(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Uncommitted modifications in tracked files block branch creation with 409 Conflict."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-dirty-br")
    client.post("/incidents/inc-dirty-br/remediation")
    client.post(
        "/incidents/inc-dirty-br/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve dirty"},
    )

    # Dirty the tracked file README.md
    readme = repo_dir / "README.md"
    readme.write_text("Uncommitted modification by engineer\n", encoding="utf-8")

    res = client.post("/incidents/inc-dirty-br/remediation/branch")
    assert res.status_code == 409
    assert "uncommitted modifications in tracked files" in res.json()["detail"].lower()


def test_user_uncommitted_changes_are_never_stashed_or_discarded(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """User changes must remain completely intact if branch creation is blocked."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-user-work")
    client.post("/incidents/inc-user-work/remediation")
    client.post(
        "/incidents/inc-user-work/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve"},
    )

    # Dirty tracked file
    readme = repo_dir / "README.md"
    original_work = "CRITICAL UNSAVED WORK THAT MUST NEVER BE LOST\n"
    readme.write_text(original_work, encoding="utf-8")

    client.post("/incidents/inc-user-work/remediation/branch")

    # Content must be 100% preserved
    assert readme.read_text(encoding="utf-8") == original_work


def test_no_source_files_are_modified_during_branch_creation(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must make ZERO file modifications or additions."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-no-modify")
    client.post("/incidents/inc-no-modify/remediation")
    client.post(
        "/incidents/inc-no-modify/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve"},
    )

    # Snapshot directory tree
    files_before = {str(p.relative_to(repo_dir)): p.read_bytes() for p in repo_dir.rglob("*") if p.is_file() and not str(p).startswith(str(repo_dir / ".git"))}

    client.post("/incidents/inc-no-modify/remediation/branch")

    files_after = {str(p.relative_to(repo_dir)): p.read_bytes() for p in repo_dir.rglob("*") if p.is_file() and not str(p).startswith(str(repo_dir / ".git"))}
    assert files_before == files_after


def test_no_git_commits_or_merges_occur_during_branch_creation(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Branch creation must create branch from base commit without adding new commits."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    # Count commits before
    log_before = subprocess.run(["git", "log", "--oneline"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip().splitlines()
    assert len(log_before) == 1

    setup_verified_incident_and_investigation(incident_id="inc-no-commit")
    client.post("/incidents/inc-no-commit/remediation")
    client.post(
        "/incidents/inc-no-commit/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approve"},
    )

    client.post("/incidents/inc-no-commit/remediation/branch")

    # Count commits on new branch
    log_after = subprocess.run(["git", "log", "--oneline"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip().splitlines()
    assert len(log_after) == 1
    assert log_before == log_after


def test_cannot_alter_approval_after_branch_has_been_created(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """Once an isolated branch has been created, attempting to submit a new review decision returns 409 Conflict."""
    repo_dir, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-lock-appr")
    client.post("/incidents/inc-lock-appr/remediation")
    client.post(
        "/incidents/inc-lock-appr/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approved"},
    )
    client.post("/incidents/inc-lock-appr/remediation/branch")

    # Attempting to submit a different review now fails with 409
    res = client.post(
        "/incidents/inc-lock-appr/remediation/reviews",
        json={"decision": "rejected", "reviewer": "another", "comment": "Changed my mind"},
    )
    assert res.status_code == 409
    assert "already been branched; approval cannot be altered" in res.json()["detail"].lower()


def test_get_branch_endpoint_lifecycle(
    client: TestClient, temp_git_repo: Tuple[Path, GitBranchManager]
):
    """GET /incidents/{incident_id}/remediation/branch returns 404 before creation, and 200 after."""
    _, manager = temp_git_repo
    app.dependency_overrides[get_git_branch_manager] = lambda: manager

    setup_verified_incident_and_investigation(incident_id="inc-lifecycle-br")
    client.post("/incidents/inc-lifecycle-br/remediation")

    # 404 before branch exists
    res_before = client.get("/incidents/inc-lifecycle-br/remediation/branch")
    assert res_before.status_code == 404

    # Approve and create branch
    client.post(
        "/incidents/inc-lifecycle-br/remediation/reviews",
        json={"decision": "approved", "reviewer": "lead", "comment": "Approved"},
    )
    client.post("/incidents/inc-lifecycle-br/remediation/branch")

    # 200 after branch exists
    res_after = client.get("/incidents/inc-lifecycle-br/remediation/branch")
    assert res_after.status_code == 200
    assert res_after.json()["branch_name"] == "sentinel/incident-inc-lifecycle-br-fix"


def test_readonly_git_intelligence_uses_git_repository_path_while_branch_manager_uses_git_branch_repository_path():
    """Verify clean separation between GIT_REPOSITORY_PATH (Stage 5) and GIT_BRANCH_REPOSITORY_PATH (Stage 9)."""
    assert hasattr(config, "git_repository_path")
    assert hasattr(config, "git_branch_repository_path")
    assert hasattr(config, "git_base_branch")

    # Stage 5 GitService uses git_repository_path
    from app.repository.dependencies import get_git_service
    git_srv = get_git_service()
    assert git_srv._client.repository_path == Path(config.git_repository_path).resolve()

    # Stage 9 GitBranchManager uses git_branch_repository_path
    from app.remediation.dependencies import get_git_branch_manager
    manager = get_git_branch_manager()
    assert Path(manager.repository_path).resolve() == Path(config.git_branch_repository_path).resolve()
    assert manager.base_branch == config.git_base_branch
