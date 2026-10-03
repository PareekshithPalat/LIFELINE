from fastapi import APIRouter
from edge.cache.semantic_cache import get_semantic_cache

router = APIRouter(prefix="/cache", tags=["Semantic Cache"])


@router.get("/stats")
def get_cache_statistics():
    return get_semantic_cache().get_stats()


@router.post("/clear")
def clear_semantic_cache():
    get_semantic_cache().invalidate_all()
    return {"message": "Evidence-State Semantic Cache cleared successfully."}
