from apps.api.routes.emergency import router as emergency_router
from apps.api.routes.memory import router as memory_router
from apps.api.routes.cache import router as cache_router
from apps.api.routes.sync import router as sync_router
from apps.api.routes.media import router as media_router

__all__ = [
    "emergency_router",
    "memory_router",
    "cache_router",
    "sync_router",
    "media_router"
]
