"""Health check endpoint for service liveness verification."""

from typing import Dict
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=Dict[str, str], status_code=200)
async def get_health() -> Dict[str, str]:
    """Return service health status and identifier."""
    return {
        "status": "ok",
        "service": "sentinelops",
    }
