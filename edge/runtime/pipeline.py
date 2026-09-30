import time
import logging
from typing import Optional, Dict, Any, List
from models.enums import RiskLevel, QueryIntent, ValidationVerdict, MemoryTier
from models.schemas import GroundedResponse, PersonalProfile, IncidentObservation
from edge.runtime.router import get_router, IntentAndRiskRouter
from edge.runtime.reranker import get_reranker, RiskAwareReranker
from edge.runtime.validator import get_validator, EvidenceValidator
from edge.runtime.slm import get_slm, AdaptiveEdgeSLM
from edge.retrieval.hybrid import get_hybrid_retriever, HybridRetriever
from edge.cache.semantic_cache import get_semantic_cache, EvidenceStateSemanticCache
from edge.qdrant.client import get_qdrant_manager, QdrantEdgeManager

logger = logging.getLogger("lifeline.pipeline")

class EmergencyRuntimePipeline:
    """
    Complete end-to-end Risk-Aware Adaptive Emergency Memory Pipeline:
    USER QUERY ->
    INTENT + RISK ROUTER ->
    EVIDENCE-STATE SEMANTIC CACHE (check validity & hashes) ->
    HYBRID RETRIEVAL (Dense + Sparse BM25 via Qdrant Edge) ->
    RRF FUSION ->
    RISK-AWARE RERANKER (Tier weights + Contraindications) ->
    EVIDENCE VALIDATOR (Sufficient / Conflict / Insufficient) ->
    ADAPTIVE EDGE SLM / CLINICAL GROUNDING ->
    CACHE WRITE ->
    GROUNDED RESPONSE
    """
    def __init__(
        self,
        router: Optional[IntentAndRiskRouter] = None,
        retriever: Optional[HybridRetriever] = None,
        reranker: Optional[RiskAwareReranker] = None,
        validator: Optional[EvidenceValidator] = None,
        slm: Optional[AdaptiveEdgeSLM] = None,
        cache: Optional[EvidenceStateSemanticCache] = None,
        qdrant: Optional[QdrantEdgeManager] = None
    ):
        self.router = router or get_router()
        self.retriever = retriever or get_hybrid_retriever()
        self.reranker = reranker or get_reranker()
        self.validator = validator or get_validator()
        self.slm = slm or get_slm()
        self.cache = cache or get_semantic_cache()
        self.qdrant = qdrant or get_qdrant_manager()

    def process_query(
        self,
        query: str,
        personal_profile: Optional[PersonalProfile] = None,
        incident_id: str = "active_incident",
        current_incident_version: int = 1,
        allow_cache: bool = True,
        prefer_ollama: bool = False
    ) -> GroundedResponse:
        start_time = time.perf_counter()

        # 1. Intent + Risk Routing
        risk_level, intent, routing_meta = self.router.route(query)
        personal_version = personal_profile.version if personal_profile else 1

        # 2. Evidence-State Semantic Cache Lookup
        if allow_cache:
            cached_resp, cache_meta = self.cache.get(
                query=query,
                current_personal_version=personal_version,
                current_incident_version=current_incident_version
            )
            if cached_resp is not None:
                elapsed = (time.perf_counter() - start_time) * 1000.0
                cached_resp.latency_ms = round(elapsed, 2)
                logger.info("Serving query '%s' from semantic cache (latency: %.2fms)", query, elapsed)
                return cached_resp

        # 3. Hybrid Dense + Sparse Retrieval with Qdrant Edge
        tiers = [MemoryTier.TRUSTED, MemoryTier.PERSONAL, MemoryTier.INCIDENT]
        raw_candidates = self.retriever.retrieve(
            query=query,
            tiers=tiers,
            top_k=6
        )

        # 4. Risk-Aware Reranker
        reranked = self.reranker.rerank(
            candidates=raw_candidates,
            query=query,
            risk_level=risk_level,
            personal_profile=personal_profile
        )

        # 5. Evidence Validator (3-state paradigm)
        verdict, citations, contraindications, val_details = self.validator.validate(
            candidates=reranked,
            query=query,
            risk_level=risk_level,
            personal_profile=personal_profile
        )

        # 6. Adaptive Edge SLM / Grounded Response Generation
        grounded_resp = self.slm.generate(
            query=query,
            risk_level=risk_level,
            intent=intent,
            verdict=verdict,
            citations=citations,
            contraindications=contraindications,
            personal_profile=personal_profile,
            prefer_ollama=prefer_ollama
        )

        # 7. Write to Evidence-State Semantic Cache (if valid)
        if allow_cache and verdict != ValidationVerdict.INSUFFICIENT:
            bound_ids = [c.evidence_id for c in citations]
            bound_hashes = {c.evidence_id: c.hash for c in citations}
            entry_id = self.cache.put(
                query=query,
                response=grounded_resp,
                bound_evidence_ids=bound_ids,
                bound_evidence_hashes=bound_hashes,
                personal_version=personal_version,
                incident_version=current_incident_version
            )
            grounded_resp.cache_entry_id = entry_id

        # 8. Calculate latency
        elapsed = (time.perf_counter() - start_time) * 1000.0
        grounded_resp.latency_ms = round(elapsed, 2)

        return grounded_resp

_global_pipeline: Optional[EmergencyRuntimePipeline] = None

def get_pipeline() -> EmergencyRuntimePipeline:
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = EmergencyRuntimePipeline()
    return _global_pipeline
