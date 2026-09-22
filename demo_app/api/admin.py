"""Development-only administration endpoints for toggling controlled failure modes."""

from typing import Dict
from fastapi import APIRouter, Depends, Request, status

from demo_app.common.event_logger import event_logger
from demo_app.common.logging import demo_logger
from demo_app.failure_modes.controller import FailureModeController, get_failure_controller
from demo_app.models.schemas import FailureStatusResponse

router = APIRouter(prefix="/admin/failures", tags=["Admin Failure Controls"])


@router.get("", response_model=FailureStatusResponse, status_code=status.HTTP_200_OK)
def get_failure_status(
    controller: FailureModeController = Depends(get_failure_controller),
) -> FailureStatusResponse:
    """Check the current state of controlled failure modes."""
    return FailureStatusResponse(**controller.get_status())


@router.post("/order-processing/enable", response_model=Dict[str, object], status_code=status.HTTP_200_OK)
def enable_order_processing_failure(
    request: Request,
    controller: FailureModeController = Depends(get_failure_controller),
) -> Dict[str, object]:
    """Enable the controlled order-processing failure mode."""
    controller.enable_order_processing_error()
    demo_logger.warning("Controlled failure mode ENABLED: order_processing_error")
    request_id = getattr(request.state, "request_id", None)
    event_logger.emit_event(
        level="WARNING",
        service="demo-app",
        request_id=request_id,
        method="POST",
        endpoint="/admin/failures/order-processing/enable",
        event="failure_mode_enabled",
        message="Controlled order processing failure mode enabled.",
        status_code=status.HTTP_200_OK,
        metadata={"failure_mode": "order_processing_error"},
    )
    return {
        "order_processing_error": True,
        "message": "Order processing failure mode enabled.",
    }


@router.post("/order-processing/disable", response_model=Dict[str, object], status_code=status.HTTP_200_OK)
def disable_order_processing_failure(
    request: Request,
    controller: FailureModeController = Depends(get_failure_controller),
) -> Dict[str, object]:
    """Disable the controlled order-processing failure mode."""
    controller.disable_order_processing_error()
    demo_logger.info("Controlled failure mode DISABLED: order_processing_error")
    request_id = getattr(request.state, "request_id", None)
    event_logger.emit_event(
        level="INFO",
        service="demo-app",
        request_id=request_id,
        method="POST",
        endpoint="/admin/failures/order-processing/disable",
        event="failure_mode_disabled",
        message="Controlled order processing failure mode disabled.",
        status_code=status.HTTP_200_OK,
        metadata={"failure_mode": "order_processing_error"},
    )
    return {
        "order_processing_error": False,
        "message": "Order processing failure mode disabled.",
    }
