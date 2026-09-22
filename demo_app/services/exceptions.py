"""Domain exceptions for the demo application services.

Single source of truth for all business exceptions in demo_app.
"""


class ProductNotFoundError(Exception):
    """Raised when a requested product ID is not present in the catalog."""

    def __init__(self, product_id: str) -> None:
        super().__init__(f"Product with ID '{product_id}' not found.")
        self.product_id = product_id


class OrderProcessingError(Exception):
    """Raised when an order fails processing (used by the controlled failure mode)."""

    def __init__(self, message: str = "Simulated payment gateway timeout during order checkout.") -> None:
        super().__init__(message)
        self.message = message
