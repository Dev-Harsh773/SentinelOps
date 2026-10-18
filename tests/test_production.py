"""Stage 24 boundaries and operational tooling, isolated from real runtime data."""
from dataclasses import replace
import logging
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.backup import copy_database
from app.common.access import OperatorAccessMiddleware, WindowLimiter
from app.common.config import config
from app.common.logging import SafeJsonFormatter
from app.projects.schemas import ProjectRegisterRequest


def production(tmp_path, **changes):
    values = dict(app_env="production", runtime_dir=str(tmp_path),
                  watcher_db_path=str(tmp_path / "sentinelops.db"), project_db_path=None,
                  sentinel_workspaces_root=str(tmp_path / "workspaces"), operator_token="x" * 40)
    values.update(changes)
    return replace(config, **values)


def test_production_storage_path(tmp_path):
    assert production(tmp_path).database_path == str(tmp_path / "sentinelops.db")


@pytest.mark.parametrize("changes", [
    {"operator_token": None}, {"operator_token": "short"}, {"runtime_dir": "relative"},
    {"watcher_db_path": "different.db"}, {"cors_origins": ("*",)},
    {"public_ingress_url": "http://example.com"}, {"rate_limit_keys": 0},
    {"max_request_body_size": 0}, {"notifications_enabled": False},
])
def test_invalid_production_config(tmp_path, changes):
    with pytest.raises(ValueError):
        production(tmp_path, **changes)


@pytest.mark.parametrize("project_id", [".", "..", "../escape", "a/b", "a\\b"])
def test_project_path_traversal(project_id):
    with pytest.raises(ValueError):
        ProjectRegisterRequest(project_id=project_id, name="test", workspace_path=".")


def test_backup_restore_wal_and_no_overwrite(tmp_path):
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records (value TEXT)")
        db.execute("INSERT INTO records VALUES ('durable')")
        db.commit()
        backup = tmp_path / "backup.db"
        copy_database(source, backup)
        restored = tmp_path / "restored.db"
        copy_database(backup, restored)
        with sqlite3.connect(restored) as restored_db:
            assert restored_db.execute("SELECT value FROM records").fetchone() == ("durable",)
        with pytest.raises(FileExistsError):
            copy_database(backup, source)
        assert db.execute("SELECT count(*) FROM records").fetchone() == (1,)


def test_backup_missing_or_corrupt_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        copy_database(tmp_path / "missing", tmp_path / "out")
    corrupt = tmp_path / "corrupt"
    corrupt.write_text("not SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        copy_database(corrupt, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_rate_limit_bounded_and_expires():
    now = [0]
    limiter = WindowLimiter(max_keys=2, clock=lambda: now[0])
    assert limiter.allow("a", 1)
    assert not limiter.allow("a", 1)
    assert limiter.allow("b", 1)
    assert not limiter.allow("c", 1)
    assert len(limiter.entries) == 2
    now[0] = 61
    assert limiter.allow("c", 1)
    assert len(limiter.entries) == 1


def test_operator_route_boundaries(tmp_path):
    app = FastAPI()
    app.add_middleware(OperatorAccessMiddleware, settings=production(tmp_path))
    @app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
    def route(path):
        return {"ok": True}
    with TestClient(app) as client:
        for path in ("/health", "/live", "/ready"):
            assert client.get(path).status_code == 200
        for path in ("/projects", "/notifications", "/actions", "/docs", "/connectors/id"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer " + "x" * 40}).status_code == 200
        assert client.post("/connectors/id/ingest").status_code == 200
        assert client.get("/connectors/id/ingest").status_code == 401
        assert client.post("/connectors/id/ingest/extra").status_code == 401


def test_safe_log_redaction():
    record = logging.LogRecord("test", logging.ERROR, "", 1,
        "project_id=example Bearer private-token https://hook.example/secret secret=hidden", (), None)
    result = SafeJsonFormatter().format(record)
    assert "example" in result
    for secret in ("private-token", "hook.example", "hidden"):
        assert secret not in result


def test_single_instance_lock(tmp_path):
    from app.common.instance_lock import InstanceLock
    first = InstanceLock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="Another"):
            InstanceLock(tmp_path)
    finally:
        first.close()
    InstanceLock(tmp_path).close()


def test_clean_existing_repeated_production_lifecycle(tmp_path):
    import os
    import subprocess
    import sys
    code = '''
from fastapi.testclient import TestClient
from app.main import create_app
from app.common.config import config
import sqlite3
for cycle in range(2):
    app = create_app()
    with TestClient(app) as client:
        assert client.get('/live').status_code == 200
        assert client.get('/ready').status_code == 200
        assert app.state.notification_runtime.is_running
        with sqlite3.connect(config.database_path) as db:
            assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {'incidents', 'notifications', 'projects', 'connectors'} <= tables
        # Availability changes are reflected without depending on monitored targets.
        object.__setattr__(config, 'runtime_dir', config.runtime_dir + '/missing')
        assert client.get('/ready').status_code == 503
        object.__setattr__(config, 'runtime_dir', config.runtime_dir[:-8])
        assert client.get('/ready').status_code == 200
    assert not app.state.ready
    assert not app.state.notification_runtime.is_running
'''
    env = dict(os.environ, APP_ENV="production", RUNTIME_DIR=str(tmp_path),
               WATCHER_DB_PATH=str(tmp_path / "sentinelops.db"), PROJECT_DB_PATH="",
               SENTINEL_WORKSPACES_ROOT=str(tmp_path / "workspaces"), WATCHER_ENABLED="false",
               SENTINELOPS_OPERATOR_TOKEN="test-only-operator-value-" * 2)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_configured_cors(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "config", replace(config, cors_origins=("https://console.example",)))
    client = TestClient(main.create_app())
    headers = {"Origin": "https://console.example", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "Authorization,Content-Type"}
    response = client.options("/projects", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example"
    headers["Origin"] = "https://attacker.example"
    response = client.options("/projects", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_chunked_body_limit_before_downstream(monkeypatch):
    import asyncio
    import app.common.middleware as middleware
    monkeypatch.setattr(middleware, "config", replace(config, max_request_body_size=10))
    reached = []
    sent = []
    chunks = iter([{"type": "http.request", "body": b"123456", "more_body": True},
                   {"type": "http.request", "body": b"789012", "more_body": True}])
    async def downstream(scope, receive, send):
        reached.append(True)
    async def receive():
        return next(chunks)
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "method": "POST", "path": "/connectors/a/ingest", "headers": []}
    asyncio.run(middleware.ContentLengthAndStreamLimitMiddleware(downstream)(scope, receive, send))
    assert not reached
    assert sent[0]["status"] == 413
