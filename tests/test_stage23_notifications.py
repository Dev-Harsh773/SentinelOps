"""Durability, fencing, restart, redaction and bounded retry regression gates."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import sqlite3
from unittest.mock import MagicMock

import httpx
import pytest

from app.incidents.models import Incident, IncidentStatus, Severity
from app.incidents.repository import SqliteIncidentRepository
from app.notifications.delivery import NotificationDeliveryRuntime
from app.notifications.models import Notification, NotificationChannel, NotificationType, DeliveryStatus
from app.notifications.service import NotificationService
from app.notifications.store import SqliteNotificationStore


def notification(nid="n", **overrides):
    now = datetime.now(timezone.utc)
    data = dict(notification_id=nid, project_id="p", incident_id="i",
        notification_type=NotificationType.INCIDENT_CREATED, severity=Severity.HIGH,
        title="Failure", message="Application failure", payload={}, channel=NotificationChannel.WEBHOOK,
        recipient="https://example.org/<redacted>", delivery_config={"url":"https://example.org/private-token"},
        delivery_status=DeliveryStatus.PENDING, created_at=now, updated_at=now, next_attempt_at=now)
    data.update(overrides)
    return Notification(**data)


@pytest.fixture
def store(tmp_path):
    s = SqliteNotificationStore(str(tmp_path / "delivery.db"))
    yield s
    s.close()


async def send(runtime, store, now=None):
    claimed = store.claim_due_notifications(1, now or datetime.now(timezone.utc))
    assert len(claimed) == 1
    await runtime._deliver_webhook(claimed[0])
    return store.get_notification(claimed[0].notification_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,category,retry", [(200,None,False),(401,"authentication",False),
    (403,"authentication",False),(404,"destination_rejected",False),(302,"destination_rejected",False),
    (408,"timeout",True),(429,"destination_unavailable",True),(503,"destination_unavailable",True)])
async def test_classification_and_safe_diagnostics(store, caplog, code, category, retry):
    caplog.set_level(logging.DEBUG)
    store.create_notification(notification(delivery_config={"url":"https://example.org/private-token?auth=query-token",
        "auth_secret":"signing-token", "headers":{"Authorization":"Bearer header-token"}}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(code, text="response-token"))) as client:
        runtime = NotificationDeliveryRuntime(store)
        runtime._http_client = client
        n = await send(runtime, store)
    assert n.failure_category == category
    assert n.delivery_status == (DeliveryStatus.PENDING if retry else DeliveryStatus.DELIVERED if code==200 else DeliveryStatus.FAILED)
    attempts = store.list_attempts("n")
    assert len(attempts)==1 and attempts[0].finished_at and attempts[0].response_status==code
    diagnostics = caplog.text + json.dumps([a.model_dump(mode="json") for a in attempts])
    for secret in ("private-token","query-token","signing-token","header-token","response-token"):
        assert secret not in diagnostics
    assert store.claim_due_notifications(1, datetime.now(timezone.utc)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,category", [(httpx.ConnectError,"network"),(httpx.ReadTimeout,"timeout")])
async def test_transport_failure_normalized(store, exception, category):
    def fail(request):
        raise exception("secret diagnostic URL")
    store.create_notification(notification())
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        runtime = NotificationDeliveryRuntime(store)
        runtime._http_client=client
        n=await send(runtime,store)
    assert n.failure_category==category and n.delivery_status==DeliveryStatus.PENDING
    assert "secret" not in n.failure_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("codes,expected", [([503,503,200],"delivered"),([503,503,503],"failed")])
async def test_bounded_backoff_history_and_restart(store, codes, expected):
    responses=iter(codes)
    store.create_notification(notification())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(next(responses)))) as client:
        runtime=NotificationDeliveryRuntime(store,base_backoff_seconds=2,retry_cap_seconds=3)
        runtime._http_client=client
        n=await send(runtime,store)
        for delay in (2,3):
            attempt=store.list_attempts("n")[-1]
            assert (n.next_attempt_at-attempt.finished_at).total_seconds()==delay
            assert not store.claim_due_notifications(1,n.next_attempt_at-timedelta(microseconds=1))
            # Close/reopen while the scheduled retry is pending.
            path=store.db_path
            store.close()
            store.__init__(path)
            assert store.get_notification("n").next_attempt_at==n.next_attempt_at
            n=await send(runtime,store,n.next_attempt_at)
    assert n.delivery_status==expected and n.attempt_count==3
    assert len(store.list_attempts("n"))==3
    assert not store.claim_due_notifications(1,datetime.now(timezone.utc)+timedelta(days=1))


def test_concurrent_independent_connections_claim_once(store):
    for index in range(20):
        store.create_notification(notification(str(index)))
    def claim(_):
        other=SqliteNotificationStore(store.db_path)
        try:
            return [n.notification_id for n in other.claim_due_notifications(20)]
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids=[nid for result in pool.map(claim,range(4)) for nid in result]
    assert len(ids)==len(set(ids))==20
    assert all(len(store.list_attempts(nid))==1 for nid in ids)


@pytest.mark.asyncio
async def test_duplicate_dispatch_same_claim_sends_once(store):
    store.create_notification(notification())
    n=store.claim_due_notifications(1)[0]
    calls=[]
    async def receiver(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        runtime=NotificationDeliveryRuntime(store)
        runtime._http_client=client
        await asyncio.gather(runtime._deliver_webhook(n),runtime._deliver_webhook(n))
    assert len(calls)==1
    assert store.get_notification("n").delivery_status==DeliveryStatus.DELIVERED


def test_active_lease_is_not_stolen_and_stale_completion_is_fenced(store):
    store.create_notification(notification())
    now=datetime.now(timezone.utc)
    old=store.claim_due_notifications(1,now,lease_seconds=10)[0]
    assert store.begin_dispatch("n",old.claim_token,now)
    path=store.db_path
    store.close(); store.__init__(path)
    assert store.recover_in_flight_on_startup(now+timedelta(seconds=9))==0
    assert store.recover_in_flight_on_startup(now+timedelta(seconds=11))==1
    new=store.claim_due_notifications(1,now+timedelta(seconds=11))[0]
    assert new.claim_token!=old.claim_token
    assert not store.begin_dispatch("n",old.claim_token,now)
    assert not store.update_delivery_outcome("n",DeliveryStatus.DELIVERED,claim_token=old.claim_token)
    assert store.get_notification("n").claim_token==new.claim_token
    assert store.list_attempts("n")[0].outcome=="interrupted"


def test_interrupted_last_attempt_becomes_terminal(store):
    store.create_notification(notification(max_attempts=1))
    now=datetime.now(timezone.utc)
    store.claim_due_notifications(1,now,lease_seconds=1)
    assert store.recover_in_flight_on_startup(now+timedelta(seconds=2))==1
    assert store.get_notification("n").delivery_status==DeliveryStatus.FAILED
    assert not store.claim_due_notifications(1,now+timedelta(days=1))


def test_manual_generation_preserves_history(store):
    store.create_notification(notification(max_attempts=1))
    claim=store.claim_due_notifications(1)[0]
    store.update_delivery_outcome("n",DeliveryStatus.FAILED,claim_token=claim.claim_token)
    ok,n,_=store.atomic_reset_failed_for_retry("n",datetime.now(timezone.utc))
    assert ok and n.attempt_count==0 and n.delivery_generation==1
    assert not store.atomic_reset_failed_for_retry("n",datetime.now(timezone.utc))[0]
    store.claim_due_notifications(1)
    assert [(a.delivery_generation,a.attempt_number) for a in store.list_attempts("n")]==[(0,1),(1,1)]


def test_outbox_survives_missing_callback_and_replay_is_idempotent(store):
    from app.projects.storage import SqliteProjectStore
    from app.projects.models import Project,ProjectStatus
    from app.notifications.models import SubscriptionCreateRequest
    now=datetime.now(timezone.utc)
    projects=SqliteProjectStore(store.db_path)
    projects.create_project(Project(project_id="p",name="Project",description="Test",workspace_path="/test",
        normalized_path="/test",is_git=False,status=ProjectStatus.READY,created_at=now,updated_at=now))
    service=NotificationService(store,projects)
    sub=service.create_subscription(SubscriptionCreateRequest(project_id="p",name="Webhook",
        channel="webhook",min_severity="high",destination_config={"url":"https://example.org/original"}))
    repo=SqliteIncidentRepository(store.db_path)
    incident=Incident("i","Failure","Application failed",Severity.HIGH,IncidentStatus.OPEN,"api","test",now,now,"p")
    repo.create(incident)
    assert not store.list_notifications()
    assert len(store.pending_intents())==1
    # Callback never ran. A new service replays after reopening the database.
    path=store.db_path
    store.close(); store.__init__(path)
    service=NotificationService(store,projects)
    service.process_pending_intents()
    service.on_incident_created(incident)
    repo.update(incident)
    service.process_pending_intents()
    rows=store.list_notifications(project_id="p",incident_id="i")
    assert len(rows)==1 and rows[0].delivery_status==DeliveryStatus.PENDING
    assert not store.list_notifications(project_id="other")
    assert not store.list_notifications(incident_id="other")
    assert rows[0].delivery_config["url"]=="https://example.org/original"
    assert not store.pending_intents()
    repo.close(); projects.close()


@pytest.mark.asyncio
async def test_worker_does_not_claim_more_than_free_capacity(store):
    for i in range(4):
        store.create_notification(notification(str(i)))
    entered=asyncio.Event(); release=asyncio.Event()
    async def receiver(request):
        entered.set()
        await release.wait()
        return httpx.Response(200)
    runtime=NotificationDeliveryRuntime(store,max_concurrency=1,poll_interval_seconds=.01)
    runtime._http_client=httpx.AsyncClient(transport=httpx.MockTransport(receiver))
    await runtime.start()
    try:
        await asyncio.wait_for(entered.wait(),2)
        await asyncio.sleep(.05)
        assert sum(n.attempt_count for n in store.list_notifications())==1
    finally:
        release.set()
        await runtime.stop()
    assert not runtime.is_running


def test_stage22_database_migration_preserves_existing_row(store):
    store.create_notification(notification(delivery_status=DeliveryStatus.DELIVERED))
    path=store.db_path
    store.close()
    with sqlite3.connect(path) as conn:
        for column in ("max_attempts","delivery_generation","claim_token","lease_expires_at","failure_category"):
            conn.execute(f"ALTER TABLE notifications DROP COLUMN {column}")
        conn.execute("DROP TABLE notification_attempts")
        conn.execute("DROP TABLE notification_outbox")
    store.__init__(path)
    n=store.get_notification("n")
    assert n.delivery_status==DeliveryStatus.DELIVERED and n.max_attempts==3
    assert store.list_attempts("n")==[]
    assert not store.claim_due_notifications(1)


@pytest.mark.asyncio
async def test_genuine_failure_safeaction_approval_and_delivery(store):
    from app.actions.models import ActionType,TargetType
    from app.actions.policy import ActionPolicyEngine
    from app.actions.store import SqliteActionStore
    from app.actions.service import ActionService,ActionExecutionError
    from app.actions.executors.registry import ActionExecutorRegistry
    from app.actions.executors.notification_retry import NotificationRetryExecutor
    from app.connectors.store import SqliteConnectorStore
    from app.incidents.service import IncidentService
    from app.incidents.schemas import IncidentCreateRequest
    from app.projects.storage import SqliteProjectStore
    from app.projects.models import Project,ProjectStatus
    from app.notifications.models import SubscriptionCreateRequest
    now=datetime.now(timezone.utc)
    projects=SqliteProjectStore(store.db_path)
    projects.create_project(Project(project_id="p",name="Test",workspace_path="/p",normalized_path="/p",
        is_git=False,status=ProjectStatus.READY,created_at=now,updated_at=now))
    service=NotificationService(store,projects)
    service.create_subscription(SubscriptionCreateRequest(project_id="p",name="Receiver",channel="webhook",
        min_severity="high",destination_config={"url":"https://example.org/webhook"}))
    repo=SqliteIncidentRepository(store.db_path)
    incidents=IncidentService(repository=repo)
    incidents.add_listener(service)
    incident=incidents.create_incident(IncidentCreateRequest(project_id="p",title="Failure",summary="App failed",
        severity="high",service="api",environment="test"))
    status=503
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status))) as client:
        runtime=NotificationDeliveryRuntime(store,base_backoff_seconds=.001)
        runtime._http_client=client
        n=store.list_notifications()[0]
        for _ in range(n.max_attempts):
            n=await send(runtime,store,n.next_attempt_at)
        assert n.delivery_status==DeliveryStatus.FAILED
        actions_store=SqliteActionStore(store.db_path)
        connectors=SqliteConnectorStore(store.db_path)
        policy=ActionPolicyEngine(actions_store,connectors,store,incidents)
        registry=ActionExecutorRegistry()
        registry.register(NotificationRetryExecutor(service))
        actions=ActionService(actions_store,policy,registry)
        action=actions.propose_action(project_id="p",incident_id=incident.id,action_type=ActionType.RETRY_NOTIFICATION,
            target_type=TargetType.NOTIFICATION,target_id=n.notification_id,parameters={},operator_claim="test-proposer")
        assert action.policy_status.value=="allowed"
        with pytest.raises(ActionExecutionError,match="not approved"):
            await actions.execute_action(action.action_id)
        assert store.get_notification(n.notification_id).delivery_status==DeliveryStatus.FAILED
        actions.approve_action(action.action_id,"explicit-test-approver")
        status=200
        result=await actions.execute_action(action.action_id)
        assert result.execution_status.value=="succeeded"
        n=await send(runtime,store)
        assert n.delivery_status==DeliveryStatus.DELIVERED and n.delivery_generation==1
        assert [a.response_status for a in store.list_attempts(n.notification_id)]==[503,503,503,200]
        events=[a.event_type for a in actions.list_audits(action.action_id)]
        assert events==["PROPOSED","POLICY_EVALUATED","APPROVED","EXECUTION_STARTED","EXECUTION_COMPLETED"]
        with pytest.raises(ActionExecutionError):
            await actions.execute_action(action.action_id)
        actions_store.close();connectors.close()
    repo.close();projects.close()


@pytest.mark.parametrize("changes", [{"notification_max_attempts":0},{"notification_max_attempts":21},
    {"notification_retry_base_seconds":0},{"notification_poll_interval_seconds":float("nan")},
    {"notification_lease_seconds":64},{"notification_retry_cap_seconds":-1}])
def test_invalid_worker_configuration(changes):
    from dataclasses import replace
    from app.common.config import config
    with pytest.raises(ValueError):
        replace(config,**changes)


def test_incident_intent_transaction_rolls_back_on_failure(tmp_path,monkeypatch):
    import app.incidents.repository as repository
    repo=SqliteIncidentRepository(str(tmp_path/"incidents-first.db"))
    now=datetime.now(timezone.utc)
    incident=Incident("i","Failure","App failed",Severity.HIGH,IncidentStatus.OPEN,"api","test",now,now,"p")
    def broken(*args):
        raise RuntimeError("outbox write failed")
    monkeypatch.setattr(repository,"record_intent",broken)
    with pytest.raises(RuntimeError):
        repo.create(incident)
    assert repo.get_by_id("i") is None
    repo.close()


@pytest.mark.asyncio
async def test_disabled_worker_preserves_pending(store):
    store.create_notification(notification())
    runtime=NotificationDeliveryRuntime(store,enabled=False)
    await runtime.start()
    assert not runtime.is_running
    assert store.get_notification("n").attempt_count==0
    await runtime.stop()


@pytest.mark.parametrize("state",[DeliveryStatus.PENDING,DeliveryStatus.DELIVERED,DeliveryStatus.FAILED])
def test_restart_preserves_states_and_unowned_completion_is_rejected(store,state):
    store.create_notification(notification(delivery_status=state))
    path=store.db_path
    store.close();store.__init__(path)
    assert store.recover_in_flight_on_startup(datetime.now(timezone.utc))==0
    assert store.get_notification("n").delivery_status==state
    assert not store.update_delivery_outcome("n",DeliveryStatus.DELIVERED)
    assert store.get_notification("n").delivery_status==state


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://", "ftp://example.org", "https://user:password@example.org", "https://example.org:bad"])
async def test_invalid_destination_terminal_without_send(store,url):
    store.create_notification(notification(delivery_config={"url":url}))
    calls=[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:(calls.append(r),httpx.Response(200))[1])) as client:
        runtime=NotificationDeliveryRuntime(store);runtime._http_client=client
        n=await send(runtime,store)
    assert n.delivery_status==DeliveryStatus.FAILED and n.failure_category=="invalid_configuration"
    assert not calls
