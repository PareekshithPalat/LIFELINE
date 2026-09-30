from fastapi import APIRouter, Body
from typing import Dict, Any
from edge.sync.controller import get_sync_controller

router = APIRouter(prefix="/sync", tags=["Synchronization & Conflict Resolution"])

@router.get("/status")
async def get_sync_status():
    sync = get_sync_controller()
    return sync.get_status()

@router.post("/trigger")
async def trigger_synchronization():
    sync = get_sync_controller()
    return sync.trigger_sync()

@router.post("/toggle-network")
async def toggle_network(online: bool = Body(..., embed=True)):
    sync = get_sync_controller()
    sync.set_online_status(online)
    return {"is_online": sync.is_online, "message": f"Network mode toggled to {'ONLINE' if online else 'OFFLINE'}"}

@router.get("/pending")
async def get_pending_sync_items():
    sync = get_sync_controller()
    pending = sync.get_pending_sync()
    return {"pending_count": len(pending), "items": [p.model_dump() for p in pending]}
