import os
import shutil
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger("lifeline.media")

class MediaManager:
    """
    Offline-first media management.
    Saves media directly to local edge device disk.
    If online and Cloudinary credentials configured, syncs upstream.
    """
    def __init__(self, upload_dir: str = "./media/uploads"):
        self.upload_dir = upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)
        self.cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
        self.api_key = os.getenv("CLOUDINARY_API_KEY")
        self.api_secret = os.getenv("CLOUDINARY_API_SECRET")
        self._init_cloudinary()

    def _init_cloudinary(self):
        if self.cloud_name and self.api_key and self.api_secret:
            try:
                import cloudinary
                cloudinary.config(
                    cloud_name=self.cloud_name,
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    secure=True
                )
                logger.info("Cloudinary client initialized with cloud: %s", self.cloud_name)
            except Exception as e:
                logger.warning("Cloudinary configuration failed: %s", e)

    def save_media(
        self,
        filename: str,
        file_bytes: bytes,
        content_type: str = "image/jpeg",
        is_online: bool = False
    ) -> Dict[str, Any]:
        ext = os.path.splitext(filename)[1] or ".jpg"
        unique_name = f"{uuid.uuid4().hex[:12]}_{filename}"
        local_path = os.path.join(self.upload_dir, unique_name)

        # 1. Save locally to edge disk
        with open(local_path, "wb") as f:
            f.write(file_bytes)

        local_url = f"/api/media/file/{unique_name}"
        remote_url: Optional[str] = None
        status = "SAVED_LOCAL_OFFLINE"

        # 2. If online and Cloudinary configured, sync upstream
        if is_online and self.cloud_name and self.api_key:
            try:
                import cloudinary.uploader
                upload_res = cloudinary.uploader.upload(
                    local_path,
                    folder="lifeline_emergency_media"
                )
                remote_url = upload_res.get("secure_url")
                status = "SYNCED_CLOUDINARY"
                logger.info("Uploaded media to Cloudinary: %s", remote_url)
            except Exception as e:
                logger.warning("Failed to sync media to Cloudinary: %s. Preserved on edge disk.", e)

        return {
            "media_id": unique_name,
            "filename": filename,
            "local_path": local_path,
            "local_url": local_url,
            "remote_url": remote_url,
            "status": status,
            "size_bytes": len(file_bytes),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

_global_media_manager: Optional[MediaManager] = None

def get_media_manager() -> MediaManager:
    global _global_media_manager
    if _global_media_manager is None:
        _global_media_manager = MediaManager()
    return _global_media_manager
