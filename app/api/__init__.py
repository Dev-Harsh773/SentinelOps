"""API router aggregation.

Collects sub-routers so future SentinelOps modules can register endpoints
without turning main.py into a large, tightly coupled file.
"""

from fastapi import APIRouter
from app.api.health import router as health_router
from app.incidents.routes import router as incidents_router
from app.retrieval.routes import router as repository_router
from app.telemetry.routes import router as telemetry_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(incidents_router)
api_router.include_router(telemetry_router)
api_router.include_router(repository_router)
