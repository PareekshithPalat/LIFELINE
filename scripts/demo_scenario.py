import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge.bootstrap import ensure_indexed
from edge.stores import get_profile_store
from edge.runtime.pipeline import get_pipeline
from edge.qdrant.client import reset_qdrant_manager


def show(title, resp):
    print("\n" + "-" * 70)
    print(title)
    print("-" * 70)
    print(f"Query:      {resp.query}")
    print(f"Verdict:    {resp.verdict.value}   Risk: {resp.risk_level.value}   Confidence: {resp.confidence}")
    print(f"Cache hit:  {resp.cache_hit}   Latency: {resp.latency_ms} ms   Age group: {resp.age_category}")
    print(resp.answer)
    for a in resp.immediate_actions:
        print(f"  {a}")
    for w in resp.contraindications_and_warnings[:4]:
        print(f"  ! {w}")


def run_demo():
    ensure_indexed()
    pipeline = get_pipeline()
    profile = get_profile_store().get()
    print(f"Patient profile: {profile.full_name} | allergies: {', '.join(profile.allergies)}")

    q = "Adult is unresponsive and not breathing. What should I do right now?"
    show("1. Cardiac arrest (CRITICAL)", pipeline.process_query(q, profile))
    show("2. Same question again - served from the evidence-state cache", pipeline.process_query(q, profile))
    show("3. Contraindication: aspirin for a patient allergic to it",
         pipeline.process_query("Can I give the patient aspirin for chest pain?", profile, allow_cache=False))
    show("4. Infant choking - adult technique withheld",
         pipeline.process_query("my 8 month old baby is choking on a grape", profile, allow_cache=False))
    show("5. Off-domain question - the system abstains instead of guessing",
         pipeline.process_query("how do I cook rice", profile, allow_cache=False))

    bumped = profile.model_copy()
    bumped.version += 1
    resp = pipeline.process_query(q, bumped)
    print(f"\n6. After a profile version change the cached answer is invalidated: cache_hit={resp.cache_hit}")


if __name__ == "__main__":
    run_demo()
    reset_qdrant_manager()
