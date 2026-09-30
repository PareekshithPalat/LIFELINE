from typing import List, Dict, Any

def reciprocal_rank_fusion(
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]],
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Combines dense and sparse search rankings using Reciprocal Rank Fusion (RRF).
    Formula: score(d) = (w_dense / (k + rank_dense)) + (w_sparse / (k + rank_sparse))
    """
    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}
    dense_ranks: Dict[str, int] = {}
    sparse_ranks: Dict[str, int] = {}

    for rank, hit in enumerate(dense_results, start=1):
        doc_id = hit["id"]
        dense_ranks[doc_id] = rank
        items[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + (dense_weight / (k + rank))

    for rank, hit in enumerate(sparse_results, start=1):
        doc_id = hit["id"]
        sparse_ranks[doc_id] = rank
        if doc_id not in items:
            items[doc_id] = hit
        scores[doc_id] = scores.get(doc_id, 0.0) + (sparse_weight / (k + rank))

    fused_results = []
    for doc_id, score in scores.items():
        doc = dict(items[doc_id])
        doc["rrf_score"] = score
        doc["dense_rank"] = dense_ranks.get(doc_id, None)
        doc["sparse_rank"] = sparse_ranks.get(doc_id, None)
        fused_results.append(doc)

    # Sort descending by fused RRF score
    fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused_results
