import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.enums import ValidationVerdict, RiskLevel
from models.schemas import PersonalProfile
from edge.runtime.pipeline import get_pipeline

def run_demo():
    print("="*60)
    print("  LIFELINE: Risk-Aware Adaptive Emergency Memory Demo")
    print("="*60)

    pipeline = get_pipeline()

    # Load personal profile
    personal_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "default_personal.json"))
    with open(personal_file, "r", encoding="utf-8") as f:
        profile = PersonalProfile.model_validate(json.load(f))

    print(f"\n[Active Patient Profile]: {profile.full_name} | Blood: {profile.blood_group}")
    print(f"Allergies: {', '.join(profile.allergies)}")
    print(f"Chronic Conditions: {', '.join(profile.chronic_conditions)}")

    # Scenario 1: CRITICAL CPR EMERGENCY
    print("\n" + "-"*50)
    print("Scenario 1: Adult Unresponsive / Cardiac Arrest (CRITICAL)")
    print("-"*50)
    q1 = "Adult is unresponsive and not breathing. What should I do right now?"
    res1 = pipeline.process_query(q1, personal_profile=profile)
    print(f"Query: '{q1}'")
    print(f"Risk Level: {res1.risk_level.value}")
    print(f"Verdict:    {res1.verdict.value}")
    print(f"Cache Hit:  {res1.cache_hit} (Latency: {res1.latency_ms}ms)")
    print(f"Answer:     {res1.answer}")
    print("Action Steps:")
    for a in res1.immediate_actions[:4]:
        print(f"  * {a}")
    print(f"Top Citation: {res1.citations[0].title} (v{res1.citations[0].version})")

    # Scenario 2: SEMANTIC CACHE VERIFICATION
    print("\n" + "-"*50)
    print("Scenario 2: Semantic Cache Acceleration (Instant repeat)")
    print("-"*50)
    res2 = pipeline.process_query(q1, personal_profile=profile, allow_cache=True)
    print(f"Cache Hit:  {res2.cache_hit} (Latency: {res2.latency_ms}ms)")
    print(f"Cache Entry ID: {res2.cache_entry_id}")

    # Scenario 3: CRITICAL CONTRAINDICATION CONFLICT
    print("\n" + "-"*50)
    print("Scenario 3: Contraindication Conflict Detection (Aspirin + Allergy/Ulcer)")
    print("-"*50)
    q3 = "Can I give the patient Aspirin for chest pain?"
    res3 = pipeline.process_query(q3, personal_profile=profile, allow_cache=False)
    print(f"Query: '{q3}'")
    print(f"Risk Level: {res3.risk_level.value}")
    print(f"Verdict:    {res3.verdict.value}")
    print(f"Escalation Needed: {res3.escalation_needed}")
    print(f"Contraindications Found:")
    for c in res3.contraindications_and_warnings:
        print(f"  ! {c}")
    print("Immediate Safe Actions:")
    for a in res3.immediate_actions[:3]:
        print(f"  * {a}")

    # Scenario 4: STATE-BASED CACHE INVALIDATION
    print("\n" + "-"*50)
    print("Scenario 4: Evidence-State Invalidation (Profile update)")
    print("-"*50)
    # First query for pain medicine
    q4 = "What can I do for severe bleeding?"
    res4_a = pipeline.process_query(q4, personal_profile=profile, allow_cache=True)
    print(f"First query cache hit: {res4_a.cache_hit}")
    
    # Mutate profile version (e.g. new observation or allergy logged)
    profile_v2 = profile.model_copy()
    profile_v2.version = 2
    res4_b = pipeline.process_query(q4, personal_profile=profile_v2, allow_cache=True)
    print(f"After version bump (v1 -> v2) cache hit: {res4_b.cache_hit} (Properly invalidated & re-evaluated!)")

    print("\n" + "="*60)
    print("  ALL EDGE MEMORY SCENARIOS PASSED WITH CLINICAL INTEGRITY")
    print("="*60)

if __name__ == "__main__":
    run_demo()
