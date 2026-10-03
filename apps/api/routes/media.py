from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from edge.media import get_media_manager, MediaError
from edge.sync.controller import get_sync_controller

router = APIRouter(prefix="/media", tags=["Media Integration"])


@router.post("/upload")
async def upload_emergency_media(file: UploadFile = File(...)):
    media = get_media_manager()
    content = await file.read(media.max_bytes + 1)
    try:
        meta = media.save_media(file.filename, content, file.content_type, is_online=get_sync_controller().is_online)
    except MediaError as e:
        raise HTTPException(400, str(e))
    get_sync_controller().record_mutation("media", meta["media_id"], "UPLOAD", meta)
    return meta


@router.get("/file/{media_id}")
def serve_local_media_file(media_id: str):
    path = get_media_manager().resolve(media_id)
    if path is None:
        raise HTTPException(404, "Media file not found on edge storage.")
    return FileResponse(path)
