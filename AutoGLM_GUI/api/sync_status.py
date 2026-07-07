from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/sync/status")
async def get_sync_status():
    """Get current sync subsystem status."""
    from AutoGLM_GUI.sync.manager import sync_manager

    return sync_manager.get_status()
