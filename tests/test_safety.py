from models.schemas import PersonalProfile
from edge.runtime.safety import (allergy_terms, build_safety_context, screen_steps, query_conflicts,
                                 detect_age_category, describes_other_person)


def test_compound_allergy_is_expanded():
    terms = allergy_terms("NSAIDs (Ibuprofen, Naproxen)")
    assert {"ibuprofen", "naproxen", "nsaid", "aspirin"} <= terms


def test_plural_food_allergy_matches_singular_mentions():
    ctx = build_safety_context(PersonalProfile(full_name="x", blood_group="O+", allergies=["Peanuts"]), "adult")
    res = screen_steps(["Give crackers with cheese or peanut butter.", "Wait 15 minutes."], ctx)
    assert res.withheld == ["Give crackers with cheese or peanut butter."]
    assert res.safe_steps == ["Wait 15 minutes."]


def test_bleeding_history_blocks_aspirin_without_allergy():
    p = PersonalProfile(full_name="x", blood_group="O+", chronic_conditions=["Peptic ulcer with GI bleeding"])
    assert screen_steps(["Chew one 325mg aspirin."], build_safety_context(p, "adult")).withheld


def test_child_never_gets_aspirin_and_infant_never_gets_abdominal_thrusts():
    assert screen_steps(["Give 325mg aspirin"], build_safety_context(None, "child")).withheld
    res = screen_steps(["Perform 5 abdominal thrusts (Heimlich Maneuver)."], build_safety_context(None, "infant"))
    assert res.withheld and "chest thrusts" in res.safe_steps[0]


def test_query_conflict_only_for_administration_questions():
    ctx = build_safety_context(PersonalProfile(full_name="x", blood_group="O+", allergies=["Peanuts"]), "adult")
    assert query_conflicts("can I give him a peanut butter sandwich", ctx)
    assert not query_conflicts("he ate peanuts and his throat is swelling", ctx)


def test_age_and_person_detection():
    assert detect_age_category("my 8 month old is choking") == "infant"
    assert detect_age_category("6 year old fell") == "child"
    assert detect_age_category("15 year old with chest pain") == "adolescent"
    assert detect_age_category("patient collapsed") is None
    assert describes_other_person("my father has chest pain")
    assert not describes_other_person("the patient has chest pain")


def test_conflict_response_withholds_aspirin_for_allergic_owner(pipeline, profile):
    r = pipeline.process_query("Can I give the patient Aspirin for chest pain?", profile, allow_cache=False)
    assert r.verdict.value == "CONFLICT"
    assert all("aspirin" not in a.lower() for a in r.immediate_actions)
    assert any("DO NOT GIVE ASPIRIN" in w for w in r.contraindications_and_warnings)
    assert r.withheld_actions


def test_profile_not_applied_to_other_person(pipeline, profile):
    r = pipeline.process_query("my father has crushing chest pain", profile, allow_cache=False)
    assert r.verdict.value == "SUFFICIENT"
    assert any("NOT applied" in w for w in r.contraindications_and_warnings)


def test_full_protocol_steps_are_returned(pipeline, profile):
    r = pipeline.process_query("where do I inject the epipen", profile, allow_cache=False)
    assert len(r.immediate_actions) == 7
    assert any("Epinephrine Auto-Injector" in a and "0.15mg" in a for a in r.immediate_actions)
