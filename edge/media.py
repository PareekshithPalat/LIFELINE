import os
import re
import uuid
import logging
from typing import Optional, Dict, Any
from edge.config import get_settings
from models.schemas import utc_now

logger = logging.getLogger("lifeline.media")

ALLOWED_TYPES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
    "audio/wav": ".wav", "application/pdf": ".pdf",
}
_MEDIA_ID = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{2,5}$")


class MediaError(ValueError):
    pass


def safe_display_name(filename: Optional[str]) -> str:
    """Keeps only a harmless base name for display; it is never used as a path."""
    base = os.path.basename((filename or "").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return base[:120] or "emergency_media"


class MediaManager:
    """
    Offline-first media storage. Files are stored under a server-generated name
    (uuid + extension derived from the validated content type), so a client-supplied
    filename can never influence the path. Optional Cloudinary upload when online.
    """

    def __init__(self, upload_dir: Optional[str] = None):
        s = get_settings()
        self.upload_dir = os.path.abspath(upload_dir or os.path.join(s.runtime_path, "media"))
        os.makedirs(self.upload_dir, exist_ok=True)
        self.max_bytes = s.max_upload_mb * 1024 * 1024
        self.cloud_enabled = bool(s.cloudinary_cloud_name and s.cloudinary_api_key and s.cloudinary_api_secret)
        if self.cloud_enabled:
            try:
                import cloudinary
                cloudinary.config(cloud_name=s.cloudinary_cloud_name, api_key=s.cloudinary_api_key,
                                  api_secret=s.cloudinary_api_secret, secure=True)
            except Exception as e:
                logger.warning("Cloudinary configuration failed: %s", e)
                self.cloud_enabled = False

    def resolve(self, media_id: str) -> Optional[str]:
        """Returns the on-disk path for a media id, or None for anything that is not one of ours."""
        if not _MEDIA_ID.match(media_id or ""):
            return None
        path = os.path.abspath(os.path.join(self.upload_dir, media_id))
        if os.path.dirname(path) != self.upload_dir or not os.path.isfile(path):
            return None
        return path

    def save_media(self, filename: Optional[str], file_bytes: bytes, content_type: Optional[str],
                   is_online: bool = False) -> Dict[str, Any]:
        if not file_bytes:
            raise MediaError("Uploaded file is empty.")
        if len(file_bytes) > self.max_bytes:
            raise MediaError(f"File exceeds the {self.max_bytes // (1024 * 1024)} MB limit.")
        ctype = (content_type or "").split(";")[0].strip().lower()
        if ctype not in ALLOWED_TYPES:
            raise MediaError(f"Unsupported media type '{ctype}'.")

        media_id = f"{uuid.uuid4().hex}{ALLOWED_TYPES[ctype]}"
        local_path = os.path.join(self.upload_dir, media_id)
        with open(local_path, "wb") as f:
            f.write(file_bytes)

        remote_url, status = None, "SAVED_LOCAL_OFFLINE"
        if is_online and self.cloud_enabled:
            try:
                import cloudinary.uploader
                res = cloudinary.uploader.upload(local_path, folder="lifeline_emergency_media", resource_type="auto")
                remote_url, status = res.get("secure_url"), "SYNCED_CLOUDINARY"
            except Exception as e:
                logger.warning("Cloudinary upload failed (%s); kept on device.", e)

        return {
            "media_id": media_id,
            "filename": safe_display_name(filename),
            "content_type": ctype,
            "local_url": f"/api/media/file/{media_id}",
            "remote_url": remote_url,
            "status": status,
            "size_bytes": len(file_bytes),
            "timestamp": utc_now(),
        }


_global_media_manager: Optional[MediaManager] = None


def get_media_manager() -> MediaManager:
    global _global_media_manager
    if _global_media_manager is None:
        _global_media_manager = MediaManager()
    return _global_media_manager


def reset_media_manager():
    global _global_media_manager
    _global_media_manager = None
