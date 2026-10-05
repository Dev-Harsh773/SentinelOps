"""Comprehensive tests for Stage 19 SQLite persistence, restart durability, and hard clear guards."""

from datetime import datetime, timezone
import pytest

from app.actions.dependencies import close_action_store, get_action_store, set_custom_action_db_path
from app.actions.models import (
    ActionAuditRecord,
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
)
from app.agents.dependencies import (
    close_investigation_repository,
    get_investigation_repository,
    set_custom_investigation_db_path,
)
from app.agents.models import EvidenceReference, Investigation, InvestigationStatus, RootCauseAnalysis
from app.agents.repository import SqliteInvestigationRepository
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_repository,
    set_custom_incident_db_path,
)
from app.incidents.models import Incident, IncidentStatus, Severity
from app.memory.dependencies import (
    close_memory_repository,
    get_memory_repository,
    set_custom_memory_db_path,
)
from app.memory.models import IncidentMemory
from app.memory.repository import SqliteIncidentMemoryRepository
from app.notifications.dependencies import (
    close_notification_store,
    get_notification_store,
    set_custom_notification_db_path,
)
from app.remediation.branch_repository import SqliteRemediationBranchRepository
from app.remediation.dependencies import (
    close_remediation_repositories,
    get_branch_repository,
    get_remediation_repository,
    get_review_repository,
    set_custom_remediation_db_path,
)
from app.remediation.models import (
    RemediationBranch,
    RemediationProposal,
    RemediationReview,
    RemediationStatus,
    ReviewDecision,
)
from app.remediation.repository import SqliteRemediationRepository
from app.remediation.review_repository import SqliteRemediationReviewRepository
from app.reports.dependencies import get_report_service
from app.telemetry.dependencies import (
    close_evidence_repository,
    get_evidence_repository,
    set_custom_evidence_db_path,
)
from app.telemetry.models import Evidence, EvidenceType
from app.telemetry.repository import SqliteEvidenceRepository


def test_production_db_clear_guards_raise_runtime_error():
    """Verify that every new SQLite repository refuses to clear runtime/sentinelops.db."""
    # 1. SqliteEvidenceRepository
    ev_repo = SqliteEvidenceRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            ev_repo.clear()
    finally:
        ev_repo.close()

    # 2. SqliteInvestigationRepository
    inv_repo = SqliteInvestigationRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            inv_repo.clear()
    finally:
        inv_repo.close()

    # 3. SqliteRemediationRepository
    rem_repo = SqliteRemediationRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            rem_repo.clear()
    finally:
        rem_repo.close()

    # 4. SqliteRemediationReviewRepository
    rev_repo = SqliteRemediationReviewRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            rev_repo.clear()
    finally:
        rev_repo.close()

    # 5. SqliteRemediationBranchRepository
    branch_repo = SqliteRemediationBranchRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            branch_repo.clear()
    finally:
        branch_repo.close()

    # 6. SqliteIncidentMemoryRepository
    mem_repo = SqliteIncidentMemoryRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match=r"Refusing to clear production"):
            mem_repo.clear()
    finally:
        mem_repo.close()


def test_custom_tmp_path_clear_allowed(tmp_path):
    """Verify that custom tmp_path databases allow clean clearing without error."""
    test_db = str(tmp_path / "test_clear.db")

    ev_repo = SqliteEvidenceRepository(db_path=test_db)
    inv_repo = SqliteInvestigationRepository(db_path=test_db)
    rem_repo = SqliteRemediationRepository(db_path=test_db)
    rev_repo = SqliteRemediationReviewRepository(db_path=test_db)
    branch_repo = SqliteRemediationBranchRepository(db_path=test_db)
    mem_repo = SqliteIncidentMemoryRepository(db_path=test_db)

    try:
        # Seed test items
        now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        ev_repo.create(
            Evidence(
                id="ev-1",
                incident_id="inc-1",
                type=EvidenceType.RUNTIME_LOG,
                source="test",
                timestamp=now,
                service="order-svc",
                level="INFO",
                event="created",
                message="Order created",
                endpoint="/orders",
                exception_type=None,
                created_at=now,
            )
        )
        assert len(ev_repo.list_for_incident("inc-1")) == 1

        inv_repo.save(
            Investigation(
                investigation_id="inv-1",
                incident_id="inc-1",
                status=InvestigationStatus.RUNNING,
                created_at=now,
            )
        )
        assert inv_repo.get_by_incident_id("inc-1") is not None

        # Clearing should succeed on custom tmp_path
        ev_repo.clear()
        assert len(ev_repo.list_for_incident("inc-1")) == 0

        inv_repo.clear()
        assert inv_repo.get_by_incident_id("inc-1") is None

        rem_repo.clear()
        rev_repo.clear()
        branch_repo.clear()
        mem_repo.clear()
    finally:
        ev_repo.close()
        inv_repo.close()
        rem_repo.close()
        rev_repo.close()
        branch_repo.close()
        mem_repo.close()


def test_sqlite_repository_semantic_parity(tmp_path):
    """Verify full CRUD semantic parity on all 6 SQLite repositories."""
    test_db = str(tmp_path / "test_parity.db")
    now = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)

    # 1. Evidence
    ev_repo = SqliteEvidenceRepository(db_path=test_db)
    try:
        ev = Evidence(
            id="ev-parity-1",
            incident_id="inc-parity-1",
            type=EvidenceType.HEALTH_CHECK,
            source="cpu_monitor",
            timestamp=now,
            service="worker-svc",
            level="ERROR",
            event="health_unhealthy",
            message="CPU spike",
            endpoint="/health",
            exception_type="TimeoutError",
            created_at=now,
        )
        saved_ev = ev_repo.create(ev)
        assert saved_ev.id == "ev-parity-1"
        assert ev_repo.get_by_id("ev-parity-1").message == "CPU spike"
        assert len(ev_repo.list_for_incident("inc-parity-1")) == 1
        assert len(ev_repo.list_for_incident("inc-none")) == 0
    finally:
        ev_repo.close()

    # 2. Investigation
    inv_repo = SqliteInvestigationRepository(db_path=test_db)
    try:
        inv = Investigation(
            investigation_id="inv-parity-1",
            incident_id="inc-parity-1",
            status=InvestigationStatus.COMPLETED,
            created_at=now,
            completed_at=now,
            rca=RootCauseAnalysis(
                failure_location="worker.py:42",
                triggering_condition="queue backpressure",
                root_cause_hypothesis="Worker lock contention",
                confidence=0.88,
            ),
        )
        inv_repo.save(inv)
        fetched_inv = inv_repo.get_by_incident_id("inc-parity-1")
        assert fetched_inv is not None
        assert fetched_inv.rca.confidence == 0.88
        assert fetched_inv.status == InvestigationStatus.COMPLETED
    finally:
        inv_repo.close()

    # 3. Remediation & Reviews & Branch
    rem_repo = SqliteRemediationRepository(db_path=test_db)
    rev_repo = SqliteRemediationReviewRepository(db_path=test_db)
    branch_repo = SqliteRemediationBranchRepository(db_path=test_db)
    try:
        rem = RemediationProposal(
            remediation_id="rem-parity-1",
            incident_id="inc-parity-1",
            investigation_id="inv-parity-1",
            status=RemediationStatus.APPROVED,
            summary="Optimize batch processing",
            target_files=["worker.py"],
            target_symbols=["process_batch"],
            proposed_changes=[],
            rationale="Batch size tuning",
            risks=[],
            validation_steps=[],
            evidence_references=[],
            confidence=0.9,
            created_at=now,
            updated_at=now,
        )
        rem_repo.save(rem)
        fetched_rem = rem_repo.get_by_incident_id("inc-parity-1")
        assert fetched_rem is not None
        assert fetched_rem.summary == "Optimize batch processing"

        rev = RemediationReview(
            review_id="rev-parity-1",
            incident_id="inc-parity-1",
            remediation_id="rem-parity-1",
            investigation_id="inv-parity-1",
            decision=ReviewDecision.APPROVED,
            reviewer="lead-engineer",
            comment="Looks good",
            created_at=now,
        )
        rev_repo.save(rev)
        assert rev_repo.get_by_id("rev-parity-1") is not None
        assert len(rev_repo.list_for_incident("inc-parity-1")) == 1

        branch = RemediationBranch(
            branch_id="br-parity-1",
            incident_id="inc-parity-1",
            remediation_id="rem-parity-1",
            approval_id="appr-1",
            branch_name="remediate-worker",
            base_branch="main",
            base_commit="abc1234",
            created_at=now,
        )
        branch_repo.save(branch)
        fetched_branch = branch_repo.get_by_incident_id("inc-parity-1")
        assert fetched_branch is not None
        assert fetched_branch.branch_name == "remediate-worker"
    finally:
        rem_repo.close()
        rev_repo.close()
        branch_repo.close()

    # 4. Incident Memory
    mem_repo = SqliteIncidentMemoryRepository(db_path=test_db)
    try:
        mem = IncidentMemory(
            incident_id="inc-parity-1",
            service="worker-svc",
            environment="prod",
            title="Worker Contention",
            failure_location="worker.py:42",
            triggering_condition="queue backpressure",
            root_cause_hypothesis="Worker lock contention",
            summary="Worker contention resolved via batching",
            relevant_symbols=["process_batch"],
            relevant_files=["worker.py"],
            resolution_notes="Tune batch size to 50",
            created_at=now,
        )
        mem_repo.save(mem)
        fetched_mem = mem_repo.get_by_incident_id("inc-parity-1")
        assert fetched_mem is not None
        assert fetched_mem.relevant_symbols == ["process_batch"]
        assert len(mem_repo.list_all()) == 1
    finally:
        mem_repo.close()


def test_report_factual_content_identical_across_backend_restart(tmp_path):
    """Verify that incident report content is completely durable across full backend restart.

    Ensures that restart does not cause evidence, investigation, remediation, reviews,
    actions, or memory to disappear or mutate.
    """
    test_db = str(tmp_path / "test_restart_durability.db")
    t0 = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 4, 8, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 4, 8, 15, tzinfo=timezone.utc)

    # 1. Configure all subsystems to use test_db
    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    # Seed project for foreign keys
    act_store = get_action_store()
    with act_store._lock:
        cursor = act_store._conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
            ) VALUES ('proj-durable', 'Durable Project', '/work', '/work', 1, 'ready', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        act_store._conn.commit()

    # Populate full incident ecosystem
    inc = Incident(
        id="inc-durable-1",
        title="Durable Persistence Verification",
        summary="Verifying Stage 19 report survival across restart",
        severity=Severity.HIGH,
        status=IncidentStatus.RESOLVED,
        service="payment-gateway",
        environment="prod",
        created_at=t0,
        updated_at=t2,
        project_id="proj-durable",
    )
    get_incident_repository().create(inc)

    ev = Evidence(
        id="ev-dur-1",
        incident_id="inc-durable-1",
        type=EvidenceType.RUNTIME_LOG,
        source="gateway.log",
        timestamp=t0,
        service="payment-gateway",
        level="ERROR",
        event="gateway_disconnect",
        message="Socket hang up during settlement",
        endpoint="/settle",
        exception_type="ConnectionResetError",
        created_at=t0,
    )
    get_evidence_repository().create(ev)

    inv = Investigation(
        investigation_id="inv-dur-1",
        incident_id="inc-durable-1",
        status=InvestigationStatus.COMPLETED,
        created_at=t0,
        completed_at=t1,
        rca=RootCauseAnalysis(
            failure_location="services/settlement.py:88",
            triggering_condition="TCP timeout threshold 5s",
            root_cause_hypothesis="Upstream bank settlement endpoint unreachable",
            confidence=0.95,
        ),
    )
    get_investigation_repository().save(inv)

    rem = RemediationProposal(
        remediation_id="rem-dur-1",
        incident_id="inc-durable-1",
        investigation_id="inv-dur-1",
        status=RemediationStatus.APPROVED,
        summary="Implement exponential backoff retry for bank settlement",
        target_files=["services/settlement.py"],
        target_symbols=["settle_transaction"],
        proposed_changes=[],
        rationale="Prevents sudden drops on momentary blips",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        confidence=0.92,
        created_at=t1,
        updated_at=t1,
    )
    get_remediation_repository().save(rem)

    rev = RemediationReview(
        review_id="rev-dur-1",
        incident_id="inc-durable-1",
        remediation_id="rem-dur-1",
        investigation_id="inv-dur-1",
        decision=ReviewDecision.APPROVED,
        reviewer="principal-architect",
        comment="Robust retry policy approved",
        created_at=t1,
    )
    get_review_repository().save(rev)

    branch = RemediationBranch(
        branch_id="br-dur-1",
        incident_id="inc-durable-1",
        remediation_id="rem-dur-1",
        approval_id="appr-dur-1",
        branch_name="remediate-settlement-retry",
        base_branch="main",
        base_commit="git-base-1",
        created_at=t1,
    )
    get_branch_repository().save(branch)

    action = SafeAction(
        action_id="act-dur-1",
        project_id="proj-durable",
        incident_id="inc-durable-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-bank",
        parameters={"url": "https://bank.example/health"},
        fingerprint="fp-dur",
        requested_by_claim="lead-dev",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.APPROVED,
        execution_status=ExecutionStatus.SUCCEEDED,
        created_at=t1,
        updated_at=t2,
        approved_by_claim="lead-dev",
        approved_at=t1,
        approved_fingerprint="fp-dur",
        executed_at=t1,
        completed_at=t2,
        execution_result={"latency_ms": 42},
    )
    get_action_store().create_action(
        action,
        [
            ActionAuditRecord(
                audit_id="aud-dur-1",
                action_id="act-dur-1",
                event_type="PROPOSED",
                actor_claim="lead-dev",
                previous_state={},
                new_state={},
                message="Probe bank connector",
                created_at=t1,
            ),
            ActionAuditRecord(
                audit_id="aud-dur-2",
                action_id="act-dur-1",
                event_type="APPROVED",
                actor_claim="lead-dev",
                previous_state={},
                new_state={},
                message="Approved bank test",
                created_at=t1,
            ),
            ActionAuditRecord(
                audit_id="aud-dur-3",
                action_id="act-dur-1",
                event_type="EXECUTION_COMPLETED",
                actor_claim="system",
                previous_state={},
                new_state={},
                message="Probe succeeded",
                created_at=t2,
            ),
        ],
    )

    mem = IncidentMemory(
        incident_id="inc-durable-1",
        service="payment-gateway",
        environment="prod",
        title="Bank Settlement Disconnection",
        failure_location="services/settlement.py:88",
        triggering_condition="TCP timeout threshold 5s",
        root_cause_hypothesis="Upstream bank settlement endpoint unreachable",
        summary="Bank settlement transient disconnection addressed by backoff retry.",
        resolution_notes="Always use exponential jitter on banking endpoints",
        created_at=t2,
    )
    get_memory_repository().save(mem)

    # Generate pre-restart report
    report_service_pre = get_report_service()
    report_pre = report_service_pre.generate_report("inc-durable-1", project_id="proj-durable")

    # =========================================================================
    # RESTART SIMULATION: Close all repositories and stores, clear caches
    # =========================================================================
    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    # Re-wire with same test_db
    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    # Generate post-restart report
    report_service_post = get_report_service()
    report_post = report_service_post.generate_report("inc-durable-1", project_id="proj-durable")

    # Verify report is 100% durable and identical (excluding generated_at)
    assert report_post.incident.incident_id == report_pre.incident.incident_id
    assert report_post.incident.project_id == report_pre.incident.project_id
    assert report_post.incident.title == report_pre.incident.title
    assert report_post.incident.severity == report_pre.incident.severity
    assert report_post.incident.status == report_pre.incident.status
    assert report_post.incident.summary == report_pre.incident.summary
    assert report_post.incident.service == report_pre.incident.service
    assert report_post.incident.environment == report_pre.incident.environment

    # Detection and Evidence
    assert report_post.detection_and_evidence.total_evidence_count == 1
    assert len(report_post.detection_and_evidence.items) == 1
    assert report_post.detection_and_evidence.items[0].id == "ev-dur-1"
    assert report_post.detection_and_evidence.items[0].message == "Socket hang up during settlement"

    # Investigation
    assert report_post.investigation is not None
    assert report_post.investigation.root_cause_hypothesis == "Upstream bank settlement endpoint unreachable"
    assert report_post.investigation.failure_location == "services/settlement.py:88"
    assert report_post.investigation.confidence == 0.95

    # Remediation
    assert report_post.remediation is not None
    assert report_post.remediation.remediation_id == "rem-dur-1"
    assert report_post.remediation.summary == "Implement exponential backoff retry for bank settlement"
    assert report_post.remediation.branch_name == "remediate-settlement-retry"

    # Human Decisions
    assert len(report_post.human_decisions) == len(report_pre.human_decisions) == 2
    assert report_post.human_decisions[0].actor == "principal-architect"
    assert report_post.human_decisions[1].actor == "lead-dev"

    # Actions Summary
    assert len(report_post.safe_actions) == 1
    assert report_post.safe_actions[0].action_id == "act-dur-1"
    assert report_post.safe_actions[0].execution_status == ExecutionStatus.SUCCEEDED

    # Timeline matches identically
    assert len(report_post.timeline) == len(report_pre.timeline)
    for t_post, t_pre in zip(report_post.timeline, report_pre.timeline):
        assert t_post.event_type == t_pre.event_type
        assert t_post.timestamp == t_pre.timestamp
        assert t_post.description == t_pre.description

    # Second restart cycle: ensure no "closed database" errors occur on subsequent operations
    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    report_service_cycle2 = get_report_service()
    report_cycle2 = report_service_cycle2.generate_report("inc-durable-1", project_id="proj-durable")
    assert report_cycle2.investigation.root_cause_hypothesis == "Upstream bank settlement endpoint unreachable"

    # Cleanup
    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    set_custom_incident_db_path(None)
    set_custom_evidence_db_path(None)
    set_custom_investigation_db_path(None)
    set_custom_remediation_db_path(None)
    set_custom_action_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_memory_db_path(None)
