"""Order processing service managing order placement and failure triggers."""

from typing import List
import uuid

from demo_app.failure_modes.controller import FailureModeController, get_failure_controller
from demo_app.models.schemas import OrderCreateRequest, OrderResponse
from demo_app.services.exceptions import OrderProcessingError
from demo_app.services.product_service import ProductService, get_product_service


class OrderService:
    """Manages order creation with integrated failure mode observation."""

    def __init__(
        self,
        product_service: ProductService,
        failure_controller: FailureModeController,
    ) -> None:
        self._product_service = product_service
        self._failure_controller = failure_controller
        self._orders: List[OrderResponse] = []

    def create_order(self, request: OrderCreateRequest) -> OrderResponse:
        """Process an incoming order.

        Validation sequence:
        1. Find product in catalog (raises ProductNotFoundError if missing).
        2. Check controlled failure mode: if enabled, raise OrderProcessingError.
        3. Create order and calculate total in minor currency units.
        """
        # Step 1: Validate product exists before evaluating failure modes
        product = self._product_service.get_product(request.product_id)

        # Step 2: Check controlled failure mode in the order-processing path
        if self._failure_controller.is_order_processing_error_enabled():
            raise OrderProcessingError(
                f"Simulated payment gateway timeout during order checkout for product '{product.id}'."
            )

        # Step 3: Compute total and generate order
        total = product.price * request.quantity
        order = OrderResponse(
            order_id=str(uuid.uuid4()),
            product_id=product.id,
            quantity=request.quantity,
            total=total,
            status="created",
        )
        self._orders.append(order)
        return order

    def list_orders(self) -> List[OrderResponse]:
        """Return all placed orders."""
        return list(self._orders)


# Shared singleton instance
order_service = OrderService(
    product_service=get_product_service(),
    failure_controller=get_failure_controller(),
)


def get_order_service() -> OrderService:
    """Dependency provider for OrderService."""
    return order_service
