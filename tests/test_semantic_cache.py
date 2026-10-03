import time
from models.enums import RiskLevel, QueryIntent, ValidationVerdict
from models.schemas import GroundedResponse, IncidentObservation
from edge.cache.semantic_cache import EvidenceStateSemanticCache, salient_terms
from edge.embeddings.engine import get_embedding_engine


def _resp(q, risk=RiskLevel.CRITICAL, verdict=ValidationVerdict.SUFFICIENT):
    return GroundedResponse(query=q, risk_level=risk, intent=QueryIntent.FIRST_AID_INSTRUCTION,
                            verdict=verdict, answer="x", immediate_actions=["1. do"])


def _vec(q):
    return get_embedding_engine().embed_text(q)


def test_hit_on_near_duplicate_and_miss_on_unrelated():
    c = EvidenceStateSemanticCache()
    q = "adult collapsed and is not breathing"
    c.put(q, _vec(q), _resp(q), {"cpr-adult-01": "h1"}, 1, 0)
    q2 = "Adult collapsed and is not breathing."
    hit, _ = c.get(q2, _vec(q2), 1, 0)
    assert hit is not None and hit.cache_hit
    miss, meta = c.get("how do I cook rice", _vec("how do I cook rice"), 1, 0)
    assert miss is None and meta["reason"] == "no_semantic_match"


def test_negation_and_drug_changes_never_share_an_entry():
    lex = ["not", "aspirin", "ibuprofen"]
    assert salient_terms("he is breathing", lex) != salient_terms("he is not breathing", lex)
    c = EvidenceStateSemanticCache()
    a, b = "can I give aspirin for chest pain", "can I give ibuprofen for chest pain"
    c.put(a, _vec(a), _resp(a, RiskLevel.MEDIUM), {}, 1, 0)
    got, _ = c.get(b, _vec(b), 1, 0)
    assert got is None
    c2 = EvidenceStateSemanticCache()
    a, b = "the patient is unconscious and breathing", "the patient is unconscious and not breathing"
    c2.put(a, _vec(a), _resp(a), {}, 1, 0)
    assert c2.get(b, _vec(b), 1, 0)[0] is None


def test_state_invalidation_by_profile_incident_and_hash():
    q = "severe bleeding from the leg"
    c = EvidenceStateSemanticCache(hash_resolver=lambda ids: {i: "changed" for i in ids})
    c.put(q, _vec(q), _resp(q), {"bleed-01": "orig"}, 1, 0)
    assert c.get(q, _vec(q), 2, 0)[1]["reason"] == "personal_state_invalidated"
    c.put(q, _vec(q), _resp(q), {"bleed-01": "orig"}, 1, 0)
    assert c.get(q, _vec(q), 1, 3)[1]["reason"] == "incident_state_invalidated"
    c.put(q, _vec(q), _resp(q), {"bleed-01": "orig"}, 1, 0)
    assert c.get(q, _vec(q), 1, 0)[1]["reason"] == "evidence_hash_mutated"


def test_insufficient_never_cached_and_lru_bound():
    c = EvidenceStateSemanticCache(max_entries=2)
    assert c.put("x", _vec("x"), _resp("x", verdict=ValidationVerdict.INSUFFICIENT), {}, 1, 0) is None
    for q in ("burn on hand", "seizure on floor", "choking on food"):
        c.put(q, _vec(q), _resp(q), {}, 1, 0)
    assert len(c.entries) == 2 and c.stats["lru_evictions"] == 1


def test_ttl_expiry():
    c = EvidenceStateSemanticCache()
    q = "baby not breathing"
    c.put(q, _vec(q), _resp(q), {}, 1, 0, age_category="infant")
    next(iter(c.entries.values())).created_at = time.time() - 10_000
    assert c.get(q, _vec(q), 1, 0, "infant")[0] is None
    assert c.stats["expired_evictions"] == 1


def test_pipeline_cache_hit_then_invalidated_by_new_observation(pipeline, profile):
    from edge import memory_service
    q = "how do I stop heavy bleeding from a deep cut"
    first = pipeline.process_query(q, profile, incident_id="cache-test")
    second = pipeline.process_query(q, profile, incident_id="cache-test")
    assert not first.cache_hit and second.cache_hit
    memory_service.log_observation(IncidentObservation(incident_id="cache-test", observed_symptoms=["pale"]))
    third = pipeline.process_query(q, profile, incident_id="cache-test")
    assert not third.cache_hit
