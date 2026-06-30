"""
API Router — main router for all API endpoints
"""

from fastapi import APIRouter

from src.api import routes
from src.api.workflows import router as workflows_router
from src.api.nodes import router as nodes_router
from src.api.prompts import router as prompts_router
from src.api.auth import router as auth_router
from src.api.profile import router as profile_router

# Main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(workflows_router)
api_router.include_router(nodes_router)
api_router.include_router(prompts_router)
api_router.include_router(auth_router)
api_router.include_router(profile_router)

# Legacy routes (existing)
api_router.include_router(routes.api_router)

__all__ = ["api_router"]
