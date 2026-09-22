"""Product catalog endpoints for the demo application."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from demo_app.models.schemas import Product
from demo_app.services.exceptions import ProductNotFoundError
from demo_app.services.product_service import ProductService, get_product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=List[Product], status_code=status.HTTP_200_OK)
def list_products(service: ProductService = Depends(get_product_service)) -> List[Product]:
    """Retrieve all products in the catalog."""
    return service.list_products()


@router.get("/{product_id}", response_model=Product, status_code=status.HTTP_200_OK)
def get_product(product_id: str, service: ProductService = Depends(get_product_service)) -> Product:
    """Retrieve a single product by ID."""
    try:
        return service.get_product(product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
