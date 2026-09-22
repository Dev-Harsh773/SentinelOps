"""Demo application API router aggregation."""

from fastapi import APIRouter
from demo_app.api.admin import router as admin_router
from demo_app.api.orders import router as orders_router
from demo_app.api.products import router as products_router

demo_api_router = APIRouter()
demo_api_router.include_router(products_router)
demo_api_router.include_router(orders_router)
demo_api_router.include_router(admin_router)
