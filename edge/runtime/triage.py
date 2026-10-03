from typing import Optional, List
from models.enums import RiskLevel
from models.schemas import TriageAssessmentRequest, TriageAssessmentResponse, PersonalProfile
from edge.runtime.safety import build_safety_context, ADULT, ADOLESCENT, CHILD, INFANT, AGE_CATEGORIES

EMS = "Call emergency services now (911 / 112) and put the phone on speaker."

CPR_STEPS = {
    ADULT: ["Push hard and fast in the centre of the chest: 5-6 cm deep, 100-120 per minute",
            "If trained, give 2 rescue breaths after every 30 compressions; otherwise keep doing hands-only CPR",
            "Use an AED as soon as one arrives and follow its voice prompts"],
    CHILD: ["Use one or two hands on the centre of the chest: about 5 cm deep, 100-120 per minute",
            "Give 2 gentle rescue breaths after every 30 compressions (15:2 if two trained rescuers)",
            "If alone without a phone, do 2 minutes of CPR before leaving to call for help",
            "Use an AED with paediatric pads if available"],
    INFANT: ["Use 2 fingers (or two thumbs encircling the chest) on the centre of the chest: about 4 cm deep, "
             "100-120 per minute",
             "Cover the baby's mouth AND nose with your mouth; give 2 gentle breaths after every 30 compressions",
             "If alone without a phone, do 2 minutes of CPR before leaving to call for help"],
}
CPR_STEPS[ADOLESCENT] = CPR_STEPS[ADULT]

EPI_DOSE = {
    ADULT: "Inject the epinephrine auto-injector (0.3 mg) into the outer mid-thigh now and hold for 3 seconds.",
    ADOLESCENT: "Inject the epinephrine auto-injector (0.3 mg if over 30 kg, otherwise 0.15 mg) into the outer "
                "mid-thigh now and hold for 3 seconds.",
    CHILD: "Inject the child's epinephrine auto-injector (0.15 mg for 15-30 kg, 0.3 mg if over 30 kg) into the "
           "outer mid-thigh now and hold for 3 seconds.",
    INFANT: "Inject the infant's prescribed epinephrine auto-injector (0.1 mg for 7.5-15 kg where available) into "
            "the outer mid-thigh now; if none is available, follow the dispatcher's instructions.",
}


def assess(req: TriageAssessmentRequest, profile: Optional[PersonalProfile] = None,
           profile_applies: bool = True) -> TriageAssessmentResponse:
    """Rule-based single-patient triage (START-style priorities, age-aware)."""
    age = req.age_category if req.age_category in AGE_CATEGORIES else ADULT
    ctx = build_safety_context(profile if profile_applies else None, age)

    if not req.breathing:
        return TriageAssessmentResponse(
            triage_color="RED", risk_level=RiskLevel.CRITICAL,
            immediate_first_action="NOT BREATHING: start CPR immediately and get an AED.",
            action_checklist=[EMS] + CPR_STEPS[age],
            contraindications=["Do not pause compressions for more than 10 seconds.",
                               "Do not do CPR on someone who is breathing normally."],
            call_emergency_services_now=True, estimated_priority_score=100)

    if req.severe_bleeding:
        return TriageAssessmentResponse(
            triage_color="RED", risk_level=RiskLevel.CRITICAL,
            immediate_first_action="MASSIVE BLEEDING: press hard directly on the wound with a clean cloth.",
            action_checklist=[EMS,
                              "Keep firm, continuous pressure; add more cloth on top if blood soaks through",
                              "If a limb is still bleeding heavily, apply a tourniquet 5-7 cm above the wound "
                              "(not over a joint) and tighten until bleeding stops",
                              "Write the time the tourniquet was applied on the patient",
                              "Keep the patient warm and lying down"],
            contraindications=["Never loosen or remove a tourniquet once applied."],
            call_emergency_services_now=True, estimated_priority_score=95)

    if req.allergic_swelling:
        return TriageAssessmentResponse(
            triage_color="RED", risk_level=RiskLevel.CRITICAL,
            immediate_first_action="SUSPECTED ANAPHYLAXIS: " + EPI_DOSE[age],
            action_checklist=[EMS,
                              "Lay the patient flat with legs raised; let them sit up if they are struggling to "
                              "breathe or vomiting",
                              "If there is no improvement after 5-15 minutes, give a second auto-injector in the "
                              "other thigh",
                              "Be ready to start CPR if they stop breathing"],
            contraindications=["Do not rely on antihistamine tablets for throat or breathing swelling.",
                               "Do not make the patient stand or walk."],
            call_emergency_services_now=True, estimated_priority_score=90)

    if not req.consciousness:
        return TriageAssessmentResponse(
            triage_color="RED", risk_level=RiskLevel.CRITICAL,
            immediate_first_action="UNRESPONSIVE BUT BREATHING: put the patient in the recovery position.",
            action_checklist=[EMS,
                              "Roll them onto their side and tilt the head back to keep the airway open",
                              "Check breathing every minute; start CPR if it stops",
                              "Loosen tight clothing around the neck"],
            contraindications=["Do not give food, drink or pills to an unresponsive person."],
            call_emergency_services_now=True, estimated_priority_score=85)

    if req.chest_pain:
        checklist = [EMS + " Say 'suspected heart attack'.",
                     "Sit the patient down, half-sitting with knees bent; keep them calm and still"]
        contra = ["Do not let the patient walk or exert themselves."]
        aspirin_blocked = [r.reason for r in ctx.rules if r.term == "aspirin"]
        if age in (CHILD, INFANT, ADOLESCENT):
            contra.append("Do not give aspirin to children or adolescents (Reye syndrome).")
        elif aspirin_blocked:
            contra.append("DO NOT GIVE ASPIRIN: " + "; ".join(dict.fromkeys(aspirin_blocked)) + ".")
        else:
            checklist.append("If the patient is not allergic to aspirin, has no bleeding problems and no doctor "
                             "has told them to avoid it: give 300-325 mg aspirin to chew")
            if not profile_applies or profile is None:
                contra.append("Ask about aspirin allergy and bleeding problems before giving aspirin.")
        checklist.append("Be ready to start CPR and use an AED if they become unresponsive")
        return TriageAssessmentResponse(
            triage_color="YELLOW", risk_level=RiskLevel.HIGH,
            immediate_first_action="POSSIBLE HEART ATTACK: call emergency services and keep the patient at rest.",
            action_checklist=checklist, contraindications=contra,
            call_emergency_services_now=True, estimated_priority_score=75)

    burns = (req.burns_extent or "none").lower()
    if burns in ("major", "large", "severe"):
        return TriageAssessmentResponse(
            triage_color="RED" if age in (CHILD, INFANT) else "YELLOW", risk_level=RiskLevel.HIGH,
            immediate_first_action="MAJOR BURN: cool the burn under cool running water for 20 minutes.",
            action_checklist=[EMS, "Remove jewellery and clothing near the burn unless stuck to the skin",
                              "Cover loosely with cling film or a clean non-fluffy dressing",
                              "Keep the rest of the patient warm"],
            contraindications=["Do not use ice, butter or creams.", "Do not burst blisters."],
            call_emergency_services_now=True, estimated_priority_score=80 if age in (CHILD, INFANT) else 70)

    checklist: List[str] = ["Clean wounds with clean water and cover with a sterile dressing",
                            "Watch for signs of shock: pale, cold, clammy skin, fast breathing",
                            "Re-assess if anything gets worse"]
    if burns in ("minor", "small"):
        checklist.insert(0, "Cool the burn under cool running water for 20 minutes, then cover loosely")
    return TriageAssessmentResponse(
        triage_color="GREEN", risk_level=RiskLevel.MEDIUM,
        immediate_first_action="STABLE: conscious and breathing normally. Treat minor injuries and keep monitoring.",
        action_checklist=checklist,
        contraindications=["Do not leave an injured patient alone in a hazardous area."],
        call_emergency_services_now=False, estimated_priority_score=30)
