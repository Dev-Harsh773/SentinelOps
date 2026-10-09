"""Stage 21 tests for End-to-End Application Onboarding, Concurrency Safety, and Readiness."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import threading
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.common.config import AppConfig
from app.common.security import (
    GitArgumentSecurityError,
    GitURLSecurityError,
    GitURLValidator,
    get_managed_workspaces_root,
)
from app.connectors.dependencies import reset_connector_state, set_custom_connector_db_path
from app.main import create_app
from app.projects.dependencies import reset_project_state, set_custom_project_db_path
from app.projects.schemas import GitHubProjectRegisterRequest
from app.projects.service import ProjectOnboardingError
from app.watcher.dependencies import reset_watcher_state


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    from dataclasses import replace
    from app.common import config as config_module

    db_file = str(tmp_path / "stage21_onboarding.db")
    workspaces_root = str(tmp_path / "workspaces")
    Path(workspaces_root).mkdir(parents=True, exist_ok=True)

    new_cfg = replace(
        config_module.config,
        watcher_db_path=db_file,
        project_db_path=db_file,
        sentinel_workspaces_root=workspaces_root,
        telemetry_recency_window_seconds=900,
    )
    monkeypatch.setattr(config_module, "config", new_cfg)

    from app.knowledge.dependencies import reset_knowledge_state
    from app.watcher.dependencies import set_custom_watcher_db_path

    set_custom_project_db_path(db_file)
    set_custom_connector_db_path(db_file)
    set_custom_watcher_db_path(db_file)
    reset_project_state()
    reset_connector_state()
    reset_knowledge_state()
    reset_watcher_state()

    app = create_app()
    with TestClient(app) as client:
        yield client, tmp_path, Path(workspaces_root)

    reset_connector_state()
    reset_project_state()
    reset_knowledge_state()
    reset_watcher_state()
    set_custom_project_db_path(None)
    set_custom_connector_db_path(None)
    set_custom_watcher_db_path(None)


# -----------------------------------------------------------------------------
# 1. Automatic Project-ID Generation Policy
# -----------------------------------------------------------------------------
def test_automatic_slug_generation_and_deterministic_collision_resolution(test_env):
    client, tmp_path, _ = test_env

    # First: "Order Service" -> "order-service"
    ws1 = tmp_path / "ws1"
    ws1.mkdir()
    r1 = client.post("/projects", json={"name": "Order Service", "workspace_path": str(ws1)})
    assert r1.status_code == 201
    assert r1.json()["project_id"] == "order-service"

    # Second duplicate: "Order Service" -> "order-service-2"
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    r2 = client.post("/projects", json={"name": "Order Service", "workspace_path": str(ws2)})
    assert r2.status_code == 201
    assert r2.json()["project_id"] == "order-service-2"

    # Third duplicate: "Order Service" -> "order-service-3"
    ws3 = tmp_path / "ws3"
    ws3.mkdir()
    r3 = client.post("/projects", json={"name": "Order Service", "workspace_path": str(ws3)})
    assert r3.status_code == 201
    assert r3.json()["project_id"] == "order-service-3"


# -----------------------------------------------------------------------------
# 2. Public GitHub URL and Branch Validation
# -----------------------------------------------------------------------------
def test_github_url_validation_strictness():
    # Valid
    assert GitURLValidator.validate_github_https_url("https://github.com/octocat/Hello-World") == "https://github.com/octocat/Hello-World"
    assert GitURLValidator.validate_github_https_url("https://github.com/octocat/Hello-World.git") == "https://github.com/octocat/Hello-World.git"

    # Invalid: embedded credentials
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("https://user:token@github.com/octocat/Hello-World")

    # Invalid: non-HTTPS
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("git@github.com:octocat/Hello-World.git")
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("http://github.com/octocat/Hello-World")
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("file:///etc/passwd")

    # Invalid: non-github.com host
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("https://gitlab.com/octocat/Hello-World")

    # Invalid: extra path segments or invalid format
    with pytest.raises(GitURLSecurityError):
        GitURLValidator.validate_github_https_url("https://github.com/octocat/Hello-World/tree/main")


def test_github_onboarding_rejects_malicious_branch(test_env):
    client, _, _ = test_env
    # Leading hyphen in branch is forbidden (option injection attempt)
    resp = client.post(
        "/projects/github",
        json={
            "name": "Injection Test",
            "repo_url": "https://github.com/octocat/Hello-World",
            "branch": "--orphan",
        },
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# 3. Hardened Git Clone Grammar & Argv Verification
# -----------------------------------------------------------------------------
def test_git_clone_exact_argv_including_double_dash_boundary(test_env):
    client, _, _ = test_env

    clone_cmd = []

    def mock_run(cmd, **kwargs):
        nonlocal clone_cmd
        if "clone" in cmd:
            clone_cmd = list(cmd)
            target_path = Path(cmd[-1])
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / "main.py").write_text("print('hello')", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        resp = client.post(
            "/projects/github",
            json={
                "name": "Grammar Test",
                "repo_url": "https://github.com/octocat/Hello-World",
                "branch": "main",
            },
        )
        assert resp.status_code == 201

    assert clone_cmd[:4] == ["git", "clone", "--depth", "1"]
    assert "--single-branch" in clone_cmd
    assert "--branch" in clone_cmd
    assert "main" in clone_cmd
    # Assert explicit '--' argument boundary precedes the repository URL
    url_idx = clone_cmd.index("https://github.com/octocat/Hello-World")
    assert clone_cmd[url_idx - 1] == "--"


# -----------------------------------------------------------------------------
# 4. Clone Failure and Indexing Failure Rollback Semantics
# -----------------------------------------------------------------------------
def test_clone_failure_cleans_staging_and_leaves_no_database_record(test_env):
    client, _, workspaces_root = test_env

    def mock_failed_run(cmd, **kwargs):
        if "clone" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=128, stdout="", stderr="fatal: repository not found"
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_failed_run):
        resp = client.post(
            "/projects/github",
            json={
                "name": "Failing Repo",
                "repo_url": "https://github.com/octocat/NonExistent",
            },
        )
        assert resp.status_code == 400

    # Ensure no project in database
    get_resp = client.get("/projects/failing-repo")
    assert get_resp.status_code == 404

    # Ensure no staging directory left behind
    staging_dir = workspaces_root / ".staging"
    if staging_dir.exists():
        assert len(list(staging_dir.iterdir())) == 0


def test_indexing_failure_rolls_back_database_record_and_reserved_directory(test_env):
    client, _, workspaces_root = test_env

    def mock_run(cmd, **kwargs):
        if "clone" in cmd:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_run), \
         patch("app.knowledge.service.ProjectKnowledgeService.index_project_initial", side_effect=RuntimeError("Indexing crash")):
        resp = client.post(
            "/projects/github",
            json={
                "name": "Indexing Crash Project",
                "repo_url": "https://github.com/octocat/Hello-World",
            },
        )
        assert resp.status_code == 400

    # Assert DB record deleted
    assert client.get("/projects/indexing-crash-project").status_code == 404

    # Assert final directory removed
    final_dir = workspaces_root / "indexing-crash-project"
    assert not final_dir.exists()


# -----------------------------------------------------------------------------
# 5. Concurrency Safety Invariants
# -----------------------------------------------------------------------------
def test_concurrent_same_name_onboarding_allocates_unique_ids_and_workspaces(test_env):
    client, _, workspaces_root = test_env

    def mock_run(cmd, **kwargs):
        if "clone" in cmd:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "app.py").write_text("print('order')", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    results = []

    def onboard_task():
        with patch("subprocess.run", side_effect=mock_run):
            r = client.post(
                "/projects/github",
                json={
                    "name": "Order Service",
                    "repo_url": "https://github.com/octocat/Hello-World",
                },
            )
            results.append(r)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(onboard_task)
        f2 = executor.submit(onboard_task)
        f1.result()
        f2.result()

    assert len(results) == 2
    assert results[0].status_code == 201
    assert results[1].status_code == 201

    ids = {results[0].json()["project_id"], results[1].json()["project_id"]}
    assert ids == {"order-service", "order-service-2"}

    # Both workspaces must exist and be distinct
    ws1 = workspaces_root / "order-service"
    ws2 = workspaces_root / "order-service-2"
    assert ws1.is_dir()
    assert ws2.is_dir()
    assert ws1 != ws2


def test_losing_onboarding_rollback_does_not_delete_winner_workspace(test_env):
    client, _, workspaces_root = test_env

    # 1. Onboard winner project cleanly
    def mock_success_run(cmd, **kwargs):
        if "clone" in cmd:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "winner.txt").write_text("winner", encoding="utf-8")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_success_run):
        r1 = client.post(
            "/projects/github",
            json={"name": "Worker Service", "repo_url": "https://github.com/octocat/Hello-World"},
        )
        assert r1.status_code == 201
        assert r1.json()["project_id"] == "worker-service"

    winner_ws = workspaces_root / "worker-service"
    assert (winner_ws / "winner.txt").exists()

    # 2. Onboard second project that fails during clone
    def mock_fail_run(cmd, **kwargs):
        if "clone" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="network error")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_fail_run):
        r2 = client.post(
            "/projects/github",
            json={"name": "Worker Service", "repo_url": "https://github.com/octocat/Hello-World"},
        )
        assert r2.status_code == 400

    # Assert winner workspace is untouched!
    assert winner_ws.is_dir()
    assert (winner_ws / "winner.txt").read_text(encoding="utf-8") == "winner"
    assert client.get("/projects/worker-service").status_code == 200


def test_staging_clone_failure_only_cleans_caller_owned_staging_directory(test_env):
    client, _, workspaces_root = test_env

    staging_root = workspaces_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)

    # Pre-create an independent peer staging folder
    peer_staging = staging_root / "peer-active-op"
    peer_staging.mkdir()
    (peer_staging / "active.tmp").write_text("in-progress", encoding="utf-8")

    def mock_failing_run(cmd, **kwargs):
        if "clone" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="clone failure")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main", stderr="")

    with patch("subprocess.run", side_effect=mock_failing_run):
        resp = client.post(
            "/projects/github",
            json={"name": "Failing Job", "repo_url": "https://github.com/octocat/Hello-World"},
        )
        assert resp.status_code == 400

    # Assert peer staging directory is strictly preserved
    assert peer_staging.exists()
    assert (peer_staging / "active.tmp").exists()


# -----------------------------------------------------------------------------
# 6. Readiness Recency and Telemetry Evaluation
# -----------------------------------------------------------------------------
def test_readiness_endpoint_evaluates_source_and_connectors_and_telemetry(test_env, monkeypatch):
    client, tmp_path, _ = test_env

    # 1. Register project
    ws = tmp_path / "readiness_ws"
    ws.mkdir()
    (ws / "app.py").write_text("print('test')", encoding="utf-8")
    reg = client.post("/projects", json={"name": "Observability Service", "workspace_path": str(ws)})
    assert reg.status_code == 201
    project_id = reg.json()["project_id"]

    # 2. Initial readiness: No connectors, no telemetry
    r0 = client.get(f"/projects/{project_id}/readiness")
    assert r0.status_code == 200
    readiness0 = r0.json()
    assert readiness0["project_id"] == project_id
    assert readiness0["is_indexed"] is True
    assert readiness0["source_connected"] is True
    assert readiness0["connectors_count"] == 0
    assert readiness0["telemetry_receiving"] is False
    assert readiness0["last_telemetry_at"] is None

    # 3. Add poller connector
    poller_resp = client.post(
        "/connectors",
        json={
            "project_id": project_id,
            "name": "Health Poller",
            "connector_type": "http_poller",
            "config": {"url": "http://127.0.0.1:8000/health", "poll_interval_seconds": 60},
        },
    )
    assert poller_resp.status_code == 201

    r1 = client.get(f"/projects/{project_id}/readiness").json()
    assert r1["connectors_count"] == 1
    assert r1["active_connectors_count"] == 1

    # 4. Add webhook connector
    wb_resp = client.post(
        "/connectors",
        json={
            "project_id": project_id,
            "name": "Ingress Webhook",
            "connector_type": "webhook",
            "generate_secret": True,
            "config": {"token_header": "X-Sentinel-Secret"},
        },
    )
    assert wb_resp.status_code == 201
    raw_secret = wb_resp.json()["raw_auth_secret"]
    conn_id = wb_resp.json()["connector_id"]

    from dataclasses import replace
    from app.common import config as config_module

    # Without PUBLIC_INGRESS_URL, external_webhook_ready should be False
    monkeypatch.setattr(config_module, "config", replace(config_module.config, public_ingress_url=None))
    r2 = client.get(f"/projects/{project_id}/readiness").json()
    assert r2["connectors_count"] == 2
    assert r2["external_webhook_ready"] is False

    # With PUBLIC_INGRESS_URL configured, external_webhook_ready is True
    monkeypatch.setattr(config_module, "config", replace(config_module.config, public_ingress_url="https://sentinel.example.com"))
    r3 = client.get(f"/projects/{project_id}/readiness").json()
    assert r3["external_webhook_ready"] is True

    # 5. Send telemetry event via webhook -> recency evaluates to True
    client.post(
        f"/connectors/{conn_id}/ingest",
        json={"event_type": "deploy.done", "message": "done"},
        headers={"X-Sentinel-Secret": raw_secret},
    )

    r4 = client.get(f"/projects/{project_id}/readiness").json()
    assert r4["last_telemetry_at"] is not None
    assert r4["telemetry_receiving"] is True


def test_telemetry_recency_window_expires_when_older_than_window(test_env, monkeypatch):
    client, tmp_path, _ = test_env
    from dataclasses import replace
    from app.common import config as config_module

    ws = tmp_path / "recency_ws"
    ws.mkdir()
    reg = client.post("/projects", json={"name": "Window Service", "workspace_path": str(ws)})
    project_id = reg.json()["project_id"]

    # Configure short 5 second recency window
    monkeypatch.setattr(config_module, "config", replace(config_module.config, telemetry_recency_window_seconds=5))

    from app.watcher.dependencies import get_watcher_storage
    from app.watcher.models import SignalType, TelemetryEvent

    storage = get_watcher_storage()
    # Insert an event timestamped 10 minutes ago
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    event = TelemetryEvent(
        event_id="old-evt-001",
        project_id=project_id,
        service="window-service",
        environment="prod",
        signal_type=SignalType.LOG,
        source="connector",
        timestamp=old_time,
        ingested_at=old_time,
        level="INFO",
        event_type="test.old",
        message="Stale event",
    )
    storage.save(event)

    readiness = client.get(f"/projects/{project_id}/readiness").json()
    assert readiness["last_telemetry_at"] is not None
    # Must evaluate to False because 10 minutes > 5 seconds
    assert readiness["telemetry_receiving"] is False


# -----------------------------------------------------------------------------
# 7. Desktop API Client Integration
# -----------------------------------------------------------------------------
def test_desktop_client_methods_call_correct_endpoints(test_env):
    client, tmp_path, _ = test_env
    from desktop.api.client import SentinelOpsClient

    desktop_client = SentinelOpsClient(base_url="http://testserver", transport=client._transport)

    ws = tmp_path / "desktop_client_ws"
    ws.mkdir()

    # 1. register_project
    proj = desktop_client.register_project(name="Desktop Test", workspace_path=str(ws))
    assert proj.project_id == "desktop-test"

    # 2. create_connector (captures one-time secret)
    conn = desktop_client.create_connector({
        "project_id": proj.project_id,
        "name": "Desktop Webhook",
        "connector_type": "webhook",
        "generate_secret": True,
        "config": {"token_header": "X-Sentinel-Secret"},
    })
    assert conn.raw_auth_secret is not None
    assert conn.raw_auth_secret.startswith("sk-sec-")

    # 3. get_project_readiness
    readiness = desktop_client.get_project_readiness(proj.project_id)
    assert readiness.project_id == proj.project_id
    assert readiness.source_connected is True
