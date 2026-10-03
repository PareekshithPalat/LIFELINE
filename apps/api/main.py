import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from apps.api.routes import emergency_router, memory_router, cache_router, sync_router, media_router
from apps.api.security import require_api_key
from edge.config import get_settings
from edge.bootstrap import ensure_indexed, shutdown
from edge.qdrant.client import get_qdrant_manager
from edge.sync.controller import get_sync_controller
from edge.cache.semantic_cache import get_semantic_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("lifeline.api")

SYNC_INTERVAL_SECONDS = 60


async def _background_sync():
    sync = get_sync_controller()
    while True:
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
        if sync.is_online and sync.remote_url:
            result = await run_in_threadpool(sync.trigger_sync)
            logger.info("Background sync: %s", result.get("status"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting Lifeline edge node '%s'", settings.node_id)
    if not settings.api_key:
        logger.warning("LIFELINE_API_KEY is not set: the API is unauthenticated. Set it before exposing the "
                       "node beyond localhost.")
    report = await run_in_threadpool(ensure_indexed)
    logger.info("Edge memory ready: %s", report)
    task = asyncio.create_task(_background_sync()) if settings.server_url else None
    yield
    if task:
        task.cancel()
    shutdown()
    logger.info("Lifeline edge node stopped.")


app = FastAPI(
    title="Lifeline - Risk-Aware Adaptive Emergency Memory API",
    description="Offline-first personal emergency memory on Qdrant Edge.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key"],
)

protected = [Depends(require_api_key)]
for r in (emergency_router, memory_router, cache_router, sync_router, media_router):
    app.include_router(r, prefix="/api", dependencies=protected)


@app.get("/api/system/health", tags=["System"])
def system_health():
    """Unauthenticated liveness probe; reveals no patient data."""
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()
    return {
        "status": "HEALTHY",
        "system": "Lifeline Edge System",
        "mode": "OFFLINE_FIRST",
        "is_network_online": sync.is_online,
        "edge_node_id": sync.node_id,
        "collections": qdrant.get_stats(),
        "storage_mode": "qdrant_edge_embedded",
        "dense_model_ready": qdrant.engine.dense_available,
        "auth_required": bool(get_settings().api_key),
        "cache_entries": get_semantic_cache().get_stats()["active_cached_entries"],
    }


dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "dist"))
if os.path.exists(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static_web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
