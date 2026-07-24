"""Simulation API routes."""

from fastapi import APIRouter

from .runs import router as runs_router
from .show import router as show_router

router = APIRouter()
router.include_router(runs_router)
router.include_router(show_router)

__all__ = ["router"]
