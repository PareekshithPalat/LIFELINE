import pytest
from edge.runtime.router import get_router
from edge.runtime.validator import get_validator
from models.enums import RiskLevel, QueryIntent, ValidationVerdict
from models.schemas import PersonalProfile

def test_intent_and_risk_router():
    router = get_router()
    risk1, intent1, _ = router.route("Patient is unconscious, not breathing, start CPR")
    assert risk1 == RiskLevel.CRITICAL
    assert intent1 == QueryIntent.FIRST_AID_INSTRUCTION

    risk2, intent2, _ = router.route("Can I give Aspirin to the patient?")
    assert risk2 in [RiskLevel.HIGH, RiskLevel.MEDIUM]
    assert intent2 == QueryIntent.CONTRAINDICATION_CHECK

    risk3, intent3, _ = router.route("What supplies are needed for emergency first aid kit?")
    assert risk3 == RiskLevel.LOW
    assert intent3 == QueryIntent.GENERAL_PREPAREDNESS

def test_validator_empty_pool_insufficient():
    validator = get_validator()
    verdict, citations, contraindications, details = validator.validate(
        candidates=[],
        query="What is the capital of Mars?",
        risk_level=RiskLevel.LOW
    )
    assert verdict == ValidationVerdict.INSUFFICIENT
    assert details.get("reason") == "empty_candidate_pool"

def test_validator_detects_allergy_conflict():
    validator = get_validator()
    profile = PersonalProfile(
        full_name="Allergic Patient",
        blood_group="A+",
        allergies=["Aspirin"]
    )
    mock_candidates = [
        {
            "id": "heart-attack-01",
            "composite_score": 0.08,
            "contraindications_found": ["ALLERGY ALERT: Patient is allergic to 'aspirin'"],
            "payload": {
                "title": "Heart attack guidance",
                "content": "Administer chewable aspirin 325mg immediately.",
                "tier": "TRUSTED",
                "version": 1
            }
        }
    ]
    verdict, citations, contraindications, details = validator.validate(
        candidates=mock_candidates,
        query="Can I give Aspirin for chest pain?",
        risk_level=RiskLevel.HIGH,
        personal_profile=profile
    )
    assert verdict == ValidationVerdict.CONFLICT
    assert any("aspirin" in c.lower() for c in contraindications)
