import logging
from typing import List, Dict, Any, Optional
from models.enums import MemoryTier
from edge.config import get_retrieval_config
from edge.qdrant.client import get_qdrant_manager, QdrantEdgeManager

logger = logging.getLogger("lifeline.retrieval")


def fused_confidence(dense_score: float, bm25_score: float, gate: Dict[str, Any]) -> float:
    """Calibrated convex fusion of semantic and lexical evidence (see data/retrieval_config.json)."""
    return dense_score + gate["lexical_weight"] * min(bm25_score, gate["lexical_cap"])


class HybridRetriever:
    """
    Dense (max-sim over protocol chunks) + sparse (BM25 with IDF) retrieval on the
    Qdrant Edge shard, fused into one calibrated confidence per evidence item.

    Rank-only fusion such as RRF is not used for the decision because it throws away
    the score magnitudes that tell "relevant" apart from "merely the closest thing".
    """

    def __init__(self, qdrant_manager: Optional[QdrantEdgeManager] = None):
        self.qdrant = qdrant_manager or get_qdrant_manager()
        self.gate = get_retrieval_config()["gate"]

    def retrieve(self, dense_vector: Optional[List[float]], sparse_vector, tier: MemoryTier = MemoryTier.TRUSTED,
                 limit: int = 8) -> List[Dict[str, Any]]:
        candidates = self.qdrant.search(tier, dense_vector, sparse_vector, limit=limit)
        lexical_only = dense_vector is None
        for c in candidates:
            c["confidence"] = (c["bm25_score"] if lexical_only
                               else fused_confidence(c["dense_score"], c["bm25_score"], self.gate))
            c["mode"] = "lexical_only" if lexical_only else "hybrid"
        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        return candidates


_global_hybrid_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever() -> HybridRetriever:
    global _global_hybrid_retriever
    if _global_hybrid_retriever is None:
        _global_hybrid_retriever = HybridRetriever()
    return _global_hybrid_retriever


def reset_hybrid_retriever():
    global _global_hybrid_retriever
    _global_hybrid_retriever = None
