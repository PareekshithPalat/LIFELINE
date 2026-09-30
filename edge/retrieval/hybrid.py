import logging
from typing import List, Dict, Any, Optional
from models.enums import MemoryTier
from models.schemas import EvidenceItem
from edge.embeddings.engine import get_embedding_engine
from edge.qdrant.client import get_qdrant_manager, QdrantEdgeManager
from edge.retrieval.rrf import reciprocal_rank_fusion

logger = logging.getLogger("lifeline.retrieval")

class HybridRetriever:
    """
    Orchestrates dense semantic search + sparse BM25 search across
    Trusted, Personal, and Incident memory tiers, fused with RRF.
    """
    def __init__(self, qdrant_manager: Optional[QdrantEdgeManager] = None):
        self.qdrant = qdrant_manager or get_qdrant_manager()
        self.engine = get_embedding_engine()

    def retrieve(
        self,
        query: str,
        tiers: Optional[List[MemoryTier]] = None,
        top_k: int = 6,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if not tiers:
            tiers = [MemoryTier.TRUSTED, MemoryTier.PERSONAL, MemoryTier.INCIDENT]

        dense_vec, (sparse_indices, sparse_values) = self.engine.embed_query_hybrid(query)

        all_fused_candidates: List[Dict[str, Any]] = []

        for tier in tiers:
            # 1. Dense retrieval
            dense_hits = self.qdrant.query_dense(
                tier=tier,
                query_vector=dense_vec,
                limit=top_k * 2,
                filter_dict=filter_dict
            )

            # 2. Sparse retrieval
            sparse_hits = []
            if sparse_indices:
                sparse_hits = self.qdrant.query_sparse(
                    tier=tier,
                    indices=sparse_indices,
                    values=sparse_values,
                    limit=top_k * 2,
                    filter_dict=filter_dict
                )

            # 3. Fuse with RRF
            fused = reciprocal_rank_fusion(dense_hits, sparse_hits)
            for item in fused:
                item["tier"] = tier
                all_fused_candidates.append(item)

        # Sort all cross-tier candidates by RRF score
        all_fused_candidates.sort(key=lambda x: x.get("rrf_score", 0.0), reverse=True)
        return all_fused_candidates[:top_k]

_global_hybrid_retriever: Optional[HybridRetriever] = None

def get_hybrid_retriever() -> HybridRetriever:
    global _global_hybrid_retriever
    if _global_hybrid_retriever is None:
        _global_hybrid_retriever = HybridRetriever()
    return _global_hybrid_retriever
