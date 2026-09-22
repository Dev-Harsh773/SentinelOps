"""Pydantic schemas for demo application products, orders, and admin endpoints.

Note on currency:
All product prices and order totals are represented as integers in minor currency
units (cents / paise) to prevent floating-point inaccuracies. For example, 2499
represents 24.99.
"""

from pydantic import BaseModel, Field


class Product(BaseModel):
    """Product model in the catalog."""

    id: str = Field(..., description="Unique product identifier")
    name: str = Field(..., description="Human-readable product name")
    price: int = Field(..., description="Unit price stored as integer minor currency units")


class OrderCreateRequest(BaseModel):
    """Payload to place a new order."""

    product_id: str = Field(..., min_length=1, description="Identifier of the product to purchase")
    quantity: int = Field(..., gt=0, description="Number of items to purchase, must be greater than zero")


class OrderResponse(BaseModel):
    """Representation of an order after creation."""

    order_id: str = Field(..., description="Generated UUID for the order")
    product_id: str = Field(..., description="Purchased product identifier")
    quantity: int = Field(..., description="Quantity ordered")
    total: int = Field(..., description="Total price in integer minor currency units")
    status: str = Field(default="created", description="Order status")


class FailureStatusResponse(BaseModel):
    """Current state of controlled failure modes."""

    order_processing_error: bool = Field(..., description="Flag indicating if order processing failure is active")
