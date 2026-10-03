import time
import logging
from datetime import date
from typing import Optional, Tuple
from models.enums import MemoryTier, QueryIntent
from models.schemas import GroundedResponse, PersonalProfile
from edge.embeddings.engine import get_embedding_engine, EmbeddingEngine
from edge.retrieval.hybrid import get_hybrid_retriever, HybridRetriever
from edge.cache.semantic_cache import get_semantic_cache, EvidenceStateSemanticCache
from edge.stores import get_incident_store, IncidentStore
from edge.runtime.router import get_router, IntentAndRiskRouter, PROFILE_INTENTS
from edge.runtime.validator import get_validator, EvidenceValidator
from edge.runtime.responder import get_response_builder, GroundedResponseBuilder
from edge.runtime.safety import (build_safety_context, describes_other_person, AGE_CATEGORIES, ADULT,
                                 ADOLESCENT, CHILD, INFANT)

logger = logging.getLogger("lifeline.pipeline")


def profile_age_category(profile: Optional[PersonalProfile]) -> Optional[str]:
    if not profile or not profile.dob:
        return None
    try:
        born = date.fromisoformat(profile.dob[:10])
    except ValueError:
        return None
    today = date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return INFANT if years < 1 else CHILD if years < 12 else ADOLESCENT if years < 18 else ADULT


def resolve_patient(query: str, requested_age: Optional[str], detected_age: Optional[str],
                    profile: Optional[PersonalProfile]) -> Tuple[str, bool]:
    """
    Returns (age_category, profile_applies). The owner's allergies are only applied
    when the patient may be the owner: not when the query clearly describes someone
    else ("my father", "a stranger") or a different age group ("my baby"). Ambiguous
    wording ("the patient", "he") keeps the profile applied - the conservative choice
    when a responder is using the owner's phone.
    """
    owner_age = profile_age_category(profile)
    stated = requested_age if requested_age in AGE_CATEGORIES else detected_age
    applies = not describes_other_person(query)
    if stated is None:
        return owner_age or ADULT, applies
    if owner_age is not None and stated != owner_age:
        return stated, False
    return stated, applies


class EmergencyRuntimePipeline:
    """
    QUERY -> ROUTER (risk, intent, age) -> EMBED ONCE (dense + BM25)
          -> EVIDENCE-STATE SEMANTIC CACHE (similarity + salient terms + versions + hashes)
          -> QDRANT EDGE HYBRID RETRIEVAL (max-sim chunks + BM25/IDF)
          -> CALIBRATED RELEVANCE GATE (accept or ABSTAIN)
          -> PATIENT SAFETY SCREENING (allergies, conditions, age)  -> SUFFICIENT | CONFLICT
          -> GROUNDED RESPONSE (verbatim protocol steps) -> CACHE WRITE
    """

    def __init__(self, router: Optional[IntentAndRiskRouter] = None, engine: Optional[EmbeddingEngine] = None,
                 retriever: Optional[HybridRetriever] = None, validator: Optional[EvidenceValidator] = None,
                 builder: Optional[GroundedResponseBuilder] = None,
                 cache: Optional[EvidenceStateSemanticCache] = None, incidents: Optional[IncidentStore] = None):
        self.router = router or get_router()
        self.engine = engine or get_embedding_engine()
        self.retriever = retriever or get_hybrid_retriever()
        self.validator = validator or get_validator()
        self.builder = builder or get_response_builder()
        self.cache = cache or get_semantic_cache()
        self.incidents = incidents or get_incident_store()

    def process_query(self, query: str, personal_profile: Optional[PersonalProfile] = None,
                      incident_id: str = "active_incident", allow_cache: bool = True,
                      age_category: Optional[str] = None) -> GroundedResponse:
        start = time.perf_counter()
        query = query.strip()
        risk, intent, routing = self.router.route(query)
        age, profile_applies = resolve_patient(query, age_category, routing["age_category"], personal_profile)
        personal_version = personal_profile.version if personal_profile else 0
        incident_version = self.incidents.version(incident_id)

        # Memory lookups answer from the vault/timeline directly - no similarity guessing.
        if intent in PROFILE_INTENTS and personal_profile is not None:
            return self._finish(self.builder.from_profile(query, risk, intent, personal_profile), start)
        if intent == QueryIntent.INCIDENT_UPDATE:
            return self._finish(self.builder.from_incident(query, risk, intent, incident_id,
                                                           self.incidents.list(incident_id)), start)

        dense, sparse = self.engine.embed_query_hybrid(query)

        if allow_cache:
            cached, meta = self.cache.get(query, dense, personal_version, incident_version, age)
            if cached is not None:
                logger.info("Cache hit for '%s' (sim %.3f)", query, meta.get("similarity", 0))
                return self._finish(cached, start)

        candidates = self.retriever.retrieve(dense, sparse, MemoryTier.TRUSTED)
        gate = self.validator.evaluate(candidates, age)
        ctx = build_safety_context(personal_profile if profile_applies else None, age)

        if not gate.accepted:
            resp = self.builder.abstain(query, risk, intent, gate, ctx, personal_profile, profile_applies)
        else:
            resp = self.builder.from_protocol(query, risk, intent, gate, ctx, personal_profile, profile_applies)
            if allow_cache:
                bound = {c.evidence_id: c.hash for c in resp.citations if c.tier == MemoryTier.TRUSTED}
                resp.cache_entry_id = self.cache.put(query, dense, resp, bound, personal_version,
                                                     incident_version, age)
        return self._finish(resp, start)

    @staticmethod
    def _finish(resp: GroundedResponse, start: float) -> GroundedResponse:
        resp.latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return resp


_global_pipeline: Optional[EmergencyRuntimePipeline] = None


def get_pipeline() -> EmergencyRuntimePipeline:
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = EmergencyRuntimePipeline()
    return _global_pipeline


def reset_pipeline():
    global _global_pipeline
    _global_pipeline = None
