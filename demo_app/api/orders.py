"""Order management endpoints for the demo application."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from demo_app.common.event_logger import event_logger
from demo_app.models.schemas import OrderCreateRequest, OrderResponse
from demo_app.services.exceptions import ProductNotFoundError
from demo_app.services.order_service import OrderService, get_order_service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreateRequest,
    request: Request,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Create a new order.

    OrderProcessingError is intentionally not caught here, allowing the global
    exception handler to process the controlled failure, log the traceback with
    the correlation request ID, and emit HTTP 500.
    """
    try:
        order = service.create_order(payload)
        request_id = getattr(request.state, "request_id", None)
        event_logger.emit_event(
            level="INFO",
            service="demo-app",
            request_id=request_id,
            method="POST",
            endpoint="/orders",
            event="order_created",
            message=f"Order created successfully for product '{order.product_id}'",
            status_code=status.HTTP_201_CREATED,
            metadata={"order_id": order.order_id, "product_id": order.product_id, "quantity": order.quantity, "total": order.total},
        )
        return order
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
