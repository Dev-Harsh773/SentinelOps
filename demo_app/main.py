"""Main entry point for the demo application."""

from contextlib import asynccontextmanager
import time
from typing import Dict
import uuid

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from demo_app.api import demo_api_router
from demo_app.common.config import demo_config
from demo_app.common.logging import demo_logger
from demo_app.services.exceptions import OrderProcessingError


import traceback
from demo_app.common.event_logger import event_logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for demo application startup and shutdown."""
    demo_logger.info("Starting %s on port %d", demo_config.app_name, demo_config.port)
    yield
    demo_logger.info("Shutting down %s", demo_config.app_name)


def create_demo_app() -> FastAPI:
    """Application factory for the controlled demo application."""
    application = FastAPI(
        title="SentinelOps Controlled Demo Application",
        description="Independent e-commerce demonstration target service with controlled failure modes.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ---------------------------------------------------------
    # Middleware: Request Correlation & Structured Logging
    # ---------------------------------------------------------
    @application.middleware("http")
    async def request_correlation_middleware(request: Request, call_next):
        # Generate or capture correlation request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Emit request_received lifecycle event to JSONL
        event_logger.emit_event(
            level="INFO",
            service=demo_config.app_name,
            request_id=request_id,
            method=request.method,
            endpoint=request.url.path,
            event="request_received",
            message=f"Received {request.method} {request.url.path}",
        )

        start_time = time.perf_counter()
        demo_logger.info(
            "Incoming request [request_id=%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        # Emit request_completed lifecycle event to JSONL observing actual status code
        event_logger.emit_event(
            level="INFO",
            service=demo_config.app_name,
            request_id=request_id,
            method=request.method,
            endpoint=request.url.path,
            event="request_completed",
            message=f"Completed {request.method} {request.url.path} with status {response.status_code}",
            status_code=response.status_code,
            metadata={"duration_ms": round(duration_ms, 2)},
        )

        demo_logger.info(
            "Completed request [request_id=%s] %s %s -> status %d (%.2fms)",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # ---------------------------------------------------------
    # Global Exception Handler for Controlled OrderProcessingError
    # ---------------------------------------------------------
    @application.exception_handler(OrderProcessingError)
    async def order_processing_error_handler(request: Request, exc: OrderProcessingError):
        request_id = getattr(request.state, "request_id", "unknown")
        tb_str = traceback.format_exc()

        # Log the real failure traceback with correlation ID exactly once to console
        demo_logger.error(
            "Order processing failure [request_id=%s] endpoint=%s: %s",
            request_id,
            request.url.path,
            exc.message,
            exc_info=True,
        )

        # Emit structured failure event to JSONL for SentinelOps evidence collection
        event_logger.emit_event(
            level="ERROR",
            service=demo_config.app_name,
            request_id=request_id,
            method=request.method,
            endpoint=request.url.path,
            event="order_processing_failed",
            message=exc.message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            exception_type="OrderProcessingError",
            metadata={"traceback": tb_str},
        )

        # Return a safe HTTP 500 response without leaking code internals or tracebacks
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Order processing failed."},
            headers={"X-Request-ID": request_id},
        )

    # ---------------------------------------------------------
    # Health Endpoint
    # ---------------------------------------------------------
    @application.get("/health", response_model=Dict[str, str], tags=["Health"])
    def get_health() -> Dict[str, str]:
        """Service health check. Remains healthy even when order processing failure is active."""
        return {
            "status": "ok",
            "service": "demo-app",
        }

    # Register API routers
    application.include_router(demo_api_router)

    return application


app = create_demo_app()
