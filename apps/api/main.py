import os
import sys
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from apps.api.routes import (
    emergency_router,
    memory_router,
    cache_router,
    sync_router,
    media_router
)
from edge.qdrant.client import get_qdrant_manager
from edge.sync.controller import get_sync_controller
from scripts.seed_data import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("lifeline.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Lifeline Edge Architecture...")
    # Verify/seed initial clinical guidelines and patient profile
    try:
        qdrant = get_qdrant_manager()
        stats = qdrant.get_stats()
        trusted_count = stats.get("TRUSTED", {}).get("points_count", 0)
        if trusted_count == 0:
            logger.info("Empty trusted collection detected. Seeding clinical protocols...")
            seed_database()
        else:
            logger.info("Qdrant Edge collections verified with %d trusted protocols.", trusted_count)
    except Exception as e:
        logger.error("Lifespan startup verification failed: %s", e)
    yield
    logger.info("Lifeline Edge shutting down.")

app = FastAPI(
    title="Lifeline - Risk-Aware Adaptive Emergency Memory API",
    description="Offline-First Personal Emergency Memory System for Edge Devices.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for edge web console
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(emergency_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(cache_router, prefix="/api")
app.include_router(sync_router, prefix="/api")
app.include_router(media_router, prefix="/api")

@app.get("/api/system/health", tags=["System"])
async def system_health():
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()
    stats = qdrant.get_stats()

    return {
        "status": "HEALTHY",
        "system": "Lifeline Edge System",
        "mode": "OFFLINE_FIRST",
        "is_network_online": sync.is_online,
        "edge_node_id": sync.node_id,
        "collections": stats,
        "storage_mode": "embedded_local_qdrant",
        "storage_ready": os.path.exists("./data/qdrant_storage")
    }

# Mount built web console at root
dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "dist"))
if os.path.exists(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static_web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
