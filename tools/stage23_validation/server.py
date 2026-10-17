"""Isolated Stage 23 servers. Never opens the operator runtime database.

Run from repository root:
  python -m tools.stage23_validation.server provider
  python -m tools.stage23_validation.server backend
Provider state/status codes are controlled via runtime/stage23-provider-state.json.
All listeners bind loopback; the provider records IDs and codes, never headers.
"""
import argparse
import importlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DB=ROOT/"runtime/stage23-validation.db"
STATE=ROOT/"runtime/stage23-provider-state.json"
RECEIPTS=ROOT/"runtime/stage23-provider-receipts.jsonl"


def backend():
    os.environ["WATCHER_ENABLED"]="false"
    os.environ["APP_ENV"]="development"
    os.environ["NOTIFICATION_POLL_INTERVAL_SECONDS"]="0.2"
    os.environ["NOTIFICATION_RETRY_BASE_SECONDS"]="5"
    os.environ["NOTIFICATION_RETRY_CAP_SECONDS"]="10"
    os.environ["WATCHER_DB_PATH"]=str(DB)
    for module,name in [("projects","project"),("connectors","connector"),("incidents","incident"),
        ("notifications","notification"),("actions","action"),("agents","investigation"),
        ("telemetry","evidence"),("memory","memory"),("remediation","remediation"),("watcher","watcher")]:
        dependencies=importlib.import_module(f"app.{module}.dependencies")
        getattr(dependencies,f"set_custom_{name}_db_path")(str(DB))
    import uvicorn
    uvicorn.run("app.main:app",host="127.0.0.1",port=8023,log_level="info")


def provider():
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from datetime import datetime,timezone
    import threading
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            state=json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            code=int(state.get(self.path,200))
            receipt={"notification_id":payload.get("notification_id"),"path":self.path,"code":code,
                "at":datetime.now(timezone.utc).isoformat(),"attempt":self.headers.get("X-SentinelOps-Delivery-Attempt")}
            with lock,RECEIPTS.open("a",encoding="utf-8") as output:
                output.write(json.dumps(receipt)+"\n")
            self.send_response(code);self.end_headers();self.wfile.write(b"controlled validation receiver")
    ThreadingHTTPServer(("127.0.0.1",9023),Handler).serve_forever()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("role",choices=("backend","provider"))
    args=parser.parse_args()
    (backend if args.role=="backend" else provider)()
