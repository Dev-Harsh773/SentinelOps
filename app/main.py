"""Main entry point for SentinelOps backend application."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api import api_router
from app.common.config import config
from app.common.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle events."""
    logger.info("Starting %s in %s environment", config.app_name, config.app_env)
    yield
    logger.info("Shutting down %s", config.app_name)


def create_app() -> FastAPI:
    """Application factory for configuring and assembling FastAPI components."""
    application = FastAPI(
        title="SentinelOps",
        description="AI-assisted software reliability and incident-response platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register aggregated API routes
    application.include_router(api_router)

    from fastapi.responses import JSONResponse
    from app.agents.models import InvestigationLLMError

    @application.exception_handler(InvestigationLLMError)
    async def investigation_llm_exception_handler(request, exc: InvestigationLLMError):
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc)},
        )

    return application


app = create_app()
