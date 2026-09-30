import pytest
import time
from edge.cache.semantic_cache import EvidenceStateSemanticCache
from models.enums import RiskLevel, QueryIntent, ValidationVerdict
from models.schemas import GroundedResponse, SourceCitation

def test_semantic_cache_hit_and_miss():
    cache = EvidenceStateSemanticCache()
    sample_response = GroundedResponse(
        query="Adult not breathing CPR",
        risk_level=RiskLevel.CRITICAL,
        intent=QueryIntent.FIRST_AID_INSTRUCTION,
        verdict=ValidationVerdict.SUFFICIENT,
        answer="Start chest compressions immediately.",
        immediate_actions=["30 compressions", "2 breaths"]
    )
    
    # Put into cache
    entry_id = cache.put(
        query="Adult not breathing CPR",
        response=sample_response,
        bound_evidence_ids=["cpr-adult-01"],
        bound_evidence_hashes={"cpr-adult-01": "hash_v1"},
        personal_version=1,
        incident_version=1
    )
    assert entry_id is not None

    # Exact or near-identical query -> Hit
    resp, meta = cache.get("Adult not breathing CPR", current_personal_version=1, current_incident_version=1)
    assert resp is not None
    assert meta.get("hit") is True

    # Completely different query -> Miss
    resp_miss, meta_miss = cache.get("How to cook rice", current_personal_version=1, current_incident_version=1)
    assert resp_miss is None
    assert meta_miss.get("reason") == "no_semantic_match"

def test_semantic_cache_state_invalidation():
    cache = EvidenceStateSemanticCache()
    sample_response = GroundedResponse(
        query="What medicine for pain?",
        risk_level=RiskLevel.MEDIUM,
        intent=QueryIntent.FIRST_AID_INSTRUCTION,
        verdict=ValidationVerdict.SUFFICIENT,
        answer="Take recommended analgesic.",
        immediate_actions=[]
    )
    cache.put(
        query="What medicine for pain?",
        response=sample_response,
        bound_evidence_ids=["pain-guideline-01"],
        bound_evidence_hashes={"pain-guideline-01": "initial_hash"},
        personal_version=1,
        incident_version=1
    )

    # 1. State Invalidation: Personal profile allergy added (v1 -> v2)
    resp, meta = cache.get("What medicine for pain?", current_personal_version=2, current_incident_version=1)
    assert resp is None
    assert meta.get("reason") == "personal_state_invalidated"

    # Re-cache with v2
    cache.put(
        query="What medicine for pain?",
        response=sample_response,
        bound_evidence_ids=["pain-guideline-01"],
        bound_evidence_hashes={"pain-guideline-01": "initial_hash"},
        personal_version=2,
        incident_version=1
    )

    # 2. State Invalidation: Bound evidence content mutated
    resp, meta = cache.get(
        "What medicine for pain?",
        current_personal_version=2,
        current_incident_version=1,
        current_evidence_hashes={"pain-guideline-01": "mutated_hash_v2"}
    )
    assert resp is None
    assert meta.get("reason") == "evidence_hash_mutated"
