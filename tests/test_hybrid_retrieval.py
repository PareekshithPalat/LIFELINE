import pytest
from edge.retrieval.rrf import reciprocal_rank_fusion
from edge.retrieval.hybrid import get_hybrid_retriever
from models.enums import MemoryTier

def test_reciprocal_rank_fusion_logic():
    dense = [
        {"id": "doc_a", "score": 0.95},
        {"id": "doc_b", "score": 0.85},
        {"id": "doc_c", "score": 0.75}
    ]
    sparse = [
        {"id": "doc_b", "score": 12.5},
        {"id": "doc_a", "score": 8.0},
        {"id": "doc_d", "score": 5.0}
    ]

    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    assert len(fused) == 4
    # Check that doc_a and doc_b are ranked at top due to appearing in both rankings
    top_ids = [fused[0]["id"], fused[1]["id"]]
    assert "doc_a" in top_ids
    assert "doc_b" in top_ids
    assert fused[0]["rrf_score"] > fused[2]["rrf_score"]

def test_hybrid_retriever_execution():
    retriever = get_hybrid_retriever()
    results = retriever.retrieve("CPR for cardiac arrest", tiers=[MemoryTier.TRUSTED], top_k=3)
    assert len(results) > 0
    top_payload = results[0].get("payload", {})
    assert "cpr" in top_payload.get("title", "").lower() or "resuscitation" in top_payload.get("title", "").lower()
