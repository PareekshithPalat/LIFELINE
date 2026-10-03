from fastapi import APIRouter, Body, Query
from models.schemas import SyncPushRequest
from edge.sync.controller import get_sync_controller

router = APIRouter(prefix="/sync", tags=["Synchronization & Conflict Resolution"])


@router.get("/status")
def get_sync_status():
    return get_sync_controller().get_status()


@router.post("/trigger")
def trigger_synchronization():
    return get_sync_controller().trigger_sync()


@router.post("/toggle-network")
def toggle_network(online: bool = Body(..., embed=True)):
    sync = get_sync_controller()
    sync.set_online_status(online)
    return {"is_online": sync.is_online, "message": f"Network mode set to {'ONLINE' if online else 'OFFLINE'}"}


@router.get("/pending")
def get_pending_sync_items():
    pending = get_sync_controller().get_pending_sync()
    return {"pending_count": len(pending), "items": [p.model_dump(mode="json") for p in pending]}


# ---- Hub endpoints: other Lifeline nodes (e.g. the mobile app) replicate through these.
@router.post("/hub/push")
def hub_push(req: SyncPushRequest):
    return get_sync_controller().hub_receive(req.node_id, req.entries)


@router.get("/hub/pull")
def hub_pull(node_id: str = Query(...), since: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)):
    return get_sync_controller().hub_entries_since(node_id, since, limit)
