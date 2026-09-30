from fastapi import APIRouter
from edge.cache.semantic_cache import get_semantic_cache

router = APIRouter(prefix="/cache", tags=["Semantic Cache"])

@router.get("/stats")
async def get_cache_statistics():
    cache = get_semantic_cache()
    return cache.get_stats()

@router.post("/clear")
async def clear_semantic_cache():
    cache = get_semantic_cache()
    cache.invalidate_all()
    return {"message": "Evidence-State Semantic Cache cleared successfully."}
