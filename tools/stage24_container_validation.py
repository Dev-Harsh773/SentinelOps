"""Exercise the production image using disposable names and a preserved test volume.

Run: python -m tools.stage24_container_validation
Tokens remain in process memory and Docker's local container environment only.
The container is removed afterward; the uniquely named evidence volume remains.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid
import httpx


def docker(*args, **kwargs):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Never echo arguments/environment; those can contain credentials.
        raise RuntimeError("Docker operation failed: " + result.stderr[-1500:])
    return result.stdout.strip()


def main():
    suffix = uuid.uuid4().hex[:10]
    name = "sentinelops-stage24-" + suffix
    volume = name + "-data"
    token = secrets.token_urlsafe(40)
    connector_secret = secrets.token_urlsafe(40)
    env = dict(os.environ, SENTINELOPS_OPERATOR_TOKEN=token)
    result = {"container": name, "volume": volume, "checks": []}
    def passed(label):
        result["checks"].append(label)
        print("PASS", label, flush=True)
    docker("volume", "create", volume)
    def start():
        docker("run", "-d", "--name", name, "-p", "127.0.0.1:8024:8000",
               "--health-interval", "2s",
               "-e", "SENTINELOPS_OPERATOR_TOKEN", "-e", "MAX_REQUEST_BODY_SIZE=65536",
               "-e", "ALLOWED_INTERNAL_HOSTS=127.0.0.1",
               "-v", volume + ":/var/lib/sentinelops", "sentinelops:stage24", env=env)
    def ready(client):
        for _ in range(60):
            try:
                if client.get("/ready").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        raise AssertionError("Container did not become ready")
    try:
        start()
        with httpx.Client(base_url="http://127.0.0.1:8024", timeout=60) as public, \
             httpx.Client(base_url="http://127.0.0.1:8024", timeout=60,
                          headers={"Authorization": "Bearer " + token}) as client:
            ready(public)
            assert public.get("/live").status_code == 200
            assert docker("exec", name, "id", "-u") == "10001"
            for _ in range(20):
                health = docker("inspect", "--format", "{{.State.Health.Status}}", name)
                if health == "healthy":
                    break
                time.sleep(0.25)
            assert health == "healthy"
            passed("Non-root production startup, liveness and readiness")
            assert public.get("/projects").status_code == 401
            for invalid in ("invalid", connector_secret):
                assert public.get("/projects", headers={"Authorization": "Bearer " + invalid}).status_code == 401
            assert client.get("/projects").status_code == 200
            passed("Missing/invalid/connector token rejected by operator APIs; operator token accepted")
            docker("exec", name, "mkdir", "-p", "/var/lib/sentinelops/workspaces/validation")
            source = 'def create_order(order):\n    """Process an order."""\n    raise RuntimeError("controlled failure")\n'
            docker("exec", name, "python", "-c",
                   "from pathlib import Path; Path('/var/lib/sentinelops/workspaces/validation/main.py').write_text(" + repr(source) + ")")
            payload = {"project_id": "stage24-container", "name": "Stage 24 container",
                       "workspace_path": "/var/lib/sentinelops/workspaces/validation"}
            response = client.post("/projects", json=payload)
            assert response.status_code == 201, response.text
            receiver = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    count = 0
    def log_message(self, *args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        Handler.count += 1
        self.send_response(503 if Handler.count == 1 else 200)
        self.end_headers()
HTTPServer(('127.0.0.1', 9024), Handler).serve_forever()
'''
            docker("exec", "-d", name, "python", "-c", receiver)
            docker("exec", name, "python", "-c", "import socket,time\nfor attempt in range(50):\n try:\n  socket.create_connection(('127.0.0.1',9024),timeout=0.2).close(); break\n except OSError: time.sleep(0.1)\nelse: raise RuntimeError('Validation receiver not ready')")
            response = client.post("/notifications/subscriptions", json={
                "project_id": "stage24-container", "name": "controlled retry receiver", "channel": "webhook",
                "destination_config": {"url": "http://127.0.0.1:9024/private-validation-path"}})
            assert response.status_code == 201, response.text
            response = client.post("/connectors", json={"connector_id": "stage24-hook",
                "project_id": "stage24-container", "name": "container hook", "connector_type": "webhook",
                "config": {"auth_secret": connector_secret, "token_header": "x-sentinel-secret"}})
            assert response.status_code == 201, response.text
            event = {"external_event_id": "stage24-event", "signal_type": "log", "level": "ERROR", "event_type": "exception",
                "message": "create_order failed", "request_id": "stage24-request", "endpoint": "/orders",
                "status_code": 500, "exception_type": "RuntimeError", "traceback": "RuntimeError: controlled failure"}
            path = "/connectors/stage24-hook/ingest"
            assert client.post(path, json=event).status_code == 401
            assert public.post(path, json=event).status_code == 401
            response = public.post(path, json=event, headers={"x-sentinel-secret": connector_secret})
            assert response.status_code == 200, response.text
            passed("Connector ingress authenticates independently and persists telemetry")
            assert client.post(path, content=b"x" * 65537).status_code == 413
            assert public.post(path, content=b"{", headers={"x-sentinel-secret": connector_secret}).status_code == 422
            passed("Oversized and malformed telemetry rejected")
            before = client.get("/incidents?project_id=stage24-container").json()
            assert before, "Expected deterministic incident from error telemetry"
            passed("Telemetry creates an incident")
            incident_id = before[0]["id"]
            assert before[0]["severity"] == "high"
            investigation = client.post(f"/incidents/{incident_id}/investigate")
            assert investigation.status_code == 200, investigation.text
            assert "create_order" in investigation.text
            remediation = client.post(f"/incidents/{incident_id}/remediation")
            assert remediation.status_code == 200, remediation.text
            assert "create_order" in remediation.text
            action = client.post("/actions/propose", json={"project_id": "stage24-container",
                "incident_id": incident_id, "action_type": "test_connector", "target_type": "connector",
                "target_id": "stage24-hook", "operator_claim": "stage24-validation"})
            assert action.status_code == 201, action.text
            action_id = action.json()["action_id"]
            assert action.json()["approval_status"] == "pending"
            for _ in range(40):
                notifications = client.get("/notifications?project_id=stage24-container").json()
                if notifications and notifications[0]["delivery_status"] == "delivered":
                    break
                time.sleep(0.25)
            assert notifications and notifications[0]["delivery_status"] == "delivered"
            notification_id = notifications[0]["notification_id"]
            attempts_path = f"/notifications/{notification_id}/attempts"
            attempts = client.get(attempts_path).json()
            assert len(attempts) == 2, attempts
            passed("Durable notification retries controlled HTTP 503 and delivers on second attempt")
            paths = ["/projects/stage24-container", "/connectors/stage24-hook",
                f"/incidents/{incident_id}/evidence", f"/incidents/{incident_id}/investigation",
                f"/incidents/{incident_id}/remediation", f"/actions/{action_id}", f"/actions/{action_id}/audit",
                f"/memory/{incident_id}", "/notifications?project_id=stage24-container", attempts_path]
            for path in paths:
                assert client.get(path).status_code == 200, path
            records = {path: client.get(path).json() for path in paths}
            assert records[f"/incidents/{incident_id}/evidence"]
            from desktop.api.client import SentinelOpsClient
            desktop = SentinelOpsClient("http://127.0.0.1:8024", operator_token=token)
            try:
                for path, record in records.items():
                    assert desktop._request("GET", path) == record
            finally:
                desktop.close()
            passed("Desktop HTTP client reads authenticated production-container records")
            passed("Source-grounded investigation, remediation, evidence and pending SafeAction audit created")
            docker("restart", name)
            ready(public)
            assert client.get("/projects/stage24-container").status_code == 200
            assert client.get("/connectors/stage24-hook").status_code == 200
            assert client.get("/incidents?project_id=stage24-container").json() == before
            for path, record in records.items():
                assert client.get(path).json() == record, path
            passed("Restart preserves project/source, connector, incident, evidence, investigation, memory, remediation, notification/attempts and SafeAction/audit")
            docker("exec", name, "python", "-m", "app.backup", "backup",
                "/var/lib/sentinelops/sentinelops.db", "/var/lib/sentinelops/validation-backup.db")
            docker("exec", name, "python", "-m", "app.backup", "restore",
                "/var/lib/sentinelops/validation-backup.db", "/var/lib/sentinelops/validation-restored.db")
            check = """import sqlite3
source=sqlite3.connect('/var/lib/sentinelops/sentinelops.db')
restored=sqlite3.connect('/var/lib/sentinelops/validation-restored.db')
assert restored.execute('PRAGMA integrity_check').fetchone()==('ok',)
tables=[r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for table in tables:
 query='SELECT count(*) FROM "'+table.replace('"','""')+'"'
 assert source.execute(query).fetchone()==restored.execute(query).fetchone(), table
assert restored.execute('SELECT count(*) FROM incidents').fetchone()[0]>0
print('ok')"""
            assert docker("exec", name, "python", "-c", check) == "ok"
            passed("Live SQLite backup and isolated restore retain incident records")
            docker("stop", name)
            docker("rm", name)
            start()
            ready(public)
            assert client.get("/incidents?project_id=stage24-container").json() == before
            for path, record in records.items():
                assert client.get(path).json() == record, path
            passed("Replacement container preserves attached-volume state")
            logs = docker("logs", name)
            assert token not in logs and connector_secret not in logs
            assert "private-validation-path" not in logs
            passed("Credentials absent from container stdout")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        Path("runtime").mkdir(exist_ok=True)
        Path("runtime/stage24-container-results.json").write_text(json.dumps(result, indent=2))
    print("Evidence volume:", volume)


if __name__ == "__main__":
    main()
