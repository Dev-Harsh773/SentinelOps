"""Health check endpoint for service liveness verification."""

from typing import Dict
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import sqlite3
from pathlib import Path
from app.common import config as config_module

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=Dict[str, str], status_code=200)
@router.get("/live", response_model=Dict[str, str], status_code=200)
async def get_health() -> Dict[str, str]:
    """Return service health status and identifier."""
    return {
        "status": "ok",
        "service": "sentinelops",
    }


@router.get("/ready")
def get_readiness(request: Request):
    """Readiness concerns SentinelOps storage/workers, never monitored targets."""
    if not getattr(request.app.state, "ready", False):
        return JSONResponse({"status": "not_ready"}, status_code=503)
    worker = getattr(request.app.state, "notification_runtime", None)
    if config_module.config.notifications_enabled and (worker is None or not worker.is_running):
        return JSONResponse({"status": "not_ready"}, status_code=503)
    try:
        path = Path(config_module.config.database_path).resolve()
        with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            conn.rollback()
    except (sqlite3.Error, OSError):
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}
