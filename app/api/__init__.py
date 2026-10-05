"""API router aggregation.

Collects sub-routers so future SentinelOps modules can register endpoints
without turning main.py into a large, tightly coupled file.
"""

from fastapi import APIRouter
from app.actions.routes import router as actions_router
from app.agents.routes import router as investigation_router
from app.api.health import router as health_router
from app.connectors.routes import router as connectors_router
from app.incidents.routes import router as incidents_router
from app.memory.routes import router as memory_router
from app.notifications.routes import router as notifications_router
from app.projects.routes import router as projects_router
from app.remediation.routes import router as remediation_router
from app.reports.routes import router as reports_router
from app.repository.routes import router as git_router
from app.retrieval.routes import router as repository_router
from app.telemetry.routes import router as telemetry_router
from app.watcher.routes import router as watcher_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(actions_router)
api_router.include_router(connectors_router)
api_router.include_router(notifications_router)
api_router.include_router(incidents_router)
api_router.include_router(reports_router)
api_router.include_router(projects_router)
api_router.include_router(telemetry_router)
api_router.include_router(repository_router)
api_router.include_router(git_router)
api_router.include_router(investigation_router)
api_router.include_router(memory_router)
api_router.include_router(remediation_router)
api_router.include_router(watcher_router)
