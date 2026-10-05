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
    # Reconcile orphaned SafeAction execution claims across backend restart
    from app.actions.dependencies import reconcile_interrupted_actions
    reconciled_actions = reconcile_interrupted_actions()
    if reconciled_actions:
        logger.warning(
            "Reconciled %d orphaned SafeAction execution(s) across backend restart to ABORTED: %s",
            len(reconciled_actions),
            [a.action_id for a in reconciled_actions],
        )
    watcher_service = None
    if config.watcher_enabled:
        from app.watcher.dependencies import get_watcher_service
        watcher_service = get_watcher_service()
        await watcher_service.start()
    from app.connectors.dependencies import get_connector_runtime
    connector_runtime = get_connector_runtime()
    await connector_runtime.start()
    from app.notifications.dependencies import get_notification_runtime, get_notification_service
    from app.incidents.dependencies import get_incident_service
    notification_runtime = get_notification_runtime()
    await notification_runtime.start()
    incident_service = get_incident_service()
    notification_service = get_notification_service()
    incident_service.add_listener(notification_service)
    try:
        yield
    finally:
        if notification_runtime:
            await notification_runtime.stop()
        if connector_runtime:
            await connector_runtime.stop()
        if watcher_service:
            await watcher_service.stop()
        from app.watcher.dependencies import reset_watcher_state
        reset_watcher_state()
        from app.remediation.dependencies import close_remediation_repositories
        close_remediation_repositories()
        from app.agents.dependencies import close_investigation_repository
        close_investigation_repository()
        from app.telemetry.dependencies import close_evidence_repository
        close_evidence_repository()
        from app.memory.dependencies import close_memory_repository
        close_memory_repository()
        from app.actions.dependencies import close_action_store
        close_action_store()
        from app.notifications.dependencies import close_notification_store
        close_notification_store()
        from app.connectors.dependencies import close_connector_store
        close_connector_store()
        from app.projects.dependencies import close_project_store
        close_project_store()
        from app.incidents.dependencies import close_incident_repository
        close_incident_repository()
        logger.info("Shutting down %s", config.app_name)




def create_app() -> FastAPI:
    """Application factory for configuring and assembling FastAPI components."""
    import uuid
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.exceptions import RequestValidationError
    from app.common.middleware import SecurityHeadersMiddleware, ContentLengthAndStreamLimitMiddleware

    application = FastAPI(
        title="SentinelOps",
        description="AI-assisted software reliability and incident-response platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register security middleware
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(ContentLengthAndStreamLimitMiddleware)

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

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc: Exception):
        # Allow Starlette/FastAPI HTTPExceptions and validation errors to follow their normal handlers
        if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
            raise exc

        trace_id = str(uuid.uuid4())
        logger.exception("Unhandled server exception [trace_id=%s]: %s", trace_id, exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected internal server error occurred.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "trace_id": trace_id,
            },
        )

    return application


app = create_app()
