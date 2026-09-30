import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from edge.media import get_media_manager
from edge.sync.controller import get_sync_controller

router = APIRouter(prefix="/media", tags=["Media Integration"])

@router.post("/upload")
async def upload_emergency_media(file: UploadFile = File(...)):
    media_mgr = get_media_manager()
    sync = get_sync_controller()

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    meta = media_mgr.save_media(
        filename=file.filename or "emergency_media.jpg",
        file_bytes=content,
        content_type=file.content_type or "image/jpeg",
        is_online=sync.is_online
    )

    # Log media sync mutation
    sync.record_mutation(
        entity_type="media",
        entity_id=meta["media_id"],
        operation="UPLOAD",
        payload=meta
    )

    return meta

@router.get("/file/{filename}")
async def serve_local_media_file(filename: str):
    media_mgr = get_media_manager()
    filepath = os.path.abspath(os.path.join(media_mgr.upload_dir, filename))
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Media file not found on edge storage.")
    return FileResponse(filepath)
