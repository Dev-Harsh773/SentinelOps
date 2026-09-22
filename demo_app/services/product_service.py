"""Product catalog service managing in-memory demo items."""

from typing import Dict, List
from demo_app.models.schemas import Product
from demo_app.services.exceptions import ProductNotFoundError


class ProductService:
    """Manages the in-memory product catalog."""

    def __init__(self) -> None:
        # Pre-populated static catalog using integer minor currency units
        self._products: Dict[str, Product] = {
            "p1": Product(id="p1", name="Keyboard", price=2499),
            "p2": Product(id="p2", name="Mouse", price=999),
            "p3": Product(id="p3", name="Monitor", price=19999),
        }

    def list_products(self) -> List[Product]:
        """Return all available products."""
        return list(self._products.values())

    def get_product(self, product_id: str) -> Product:
        """Retrieve a product by its ID or raise ProductNotFoundError."""
        product = self._products.get(product_id)
        if not product:
            raise ProductNotFoundError(product_id)
        return product


# Shared singleton instance
product_service = ProductService()


def get_product_service() -> ProductService:
    """Dependency provider for ProductService."""
    return product_service
