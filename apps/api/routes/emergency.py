import json
import os
from fastapi import APIRouter, HTTPException
from models.schemas import (
    EmergencyQueryRequest,
    GroundedResponse,
    TriageAssessmentRequest,
    TriageAssessmentResponse,
    PersonalProfile
)
from models.enums import RiskLevel
from edge.runtime.pipeline import get_pipeline

router = APIRouter(prefix="/emergency", tags=["Emergency Engine"])

def _get_active_profile() -> PersonalProfile:
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "default_personal.json"))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return PersonalProfile.model_validate(json.load(f))
        except Exception:
            pass
    return PersonalProfile(full_name="Emergency Patient", blood_group="Unknown")

@router.post("/query", response_model=GroundedResponse)
async def process_emergency_query(req: EmergencyQueryRequest):
    pipeline = get_pipeline()
    profile = _get_active_profile()
    if req.patient_context_override:
        profile = PersonalProfile.model_validate({**profile.model_dump(), **req.patient_context_override})

    resp = pipeline.process_query(
        query=req.query,
        personal_profile=profile,
        incident_id=req.incident_id or "active_incident",
        allow_cache=req.allow_cache
    )
    return resp

@router.post("/triage", response_model=TriageAssessmentResponse)
async def rapid_triage_assessment(req: TriageAssessmentRequest):
    """
    Rapid Edge Triage Protocol (START algorithm adapted for emergency edge devices).
    """
    # 1. Immediate Life-Threats (RED - Immediate)
    if not req.breathing:
        return TriageAssessmentResponse(
            triage_color="RED",
            risk_level=RiskLevel.CRITICAL,
            immediate_first_action="NO BREATHING DETECTED: Immediately open airway and begin CPR compressions (100-120/min). Call for AED.",
            action_checklist=[
                "Call 911 / 112 immediately",
                "Begin 30 chest compressions followed by 2 rescue breaths",
                "Apply AED as soon as available"
            ],
            contraindications=["Do not pause compressions for more than 10 seconds."],
            call_emergency_services_now=True,
            estimated_priority_score=100
        )

    if req.severe_bleeding:
        return TriageAssessmentResponse(
            triage_color="RED",
            risk_level=RiskLevel.CRITICAL,
            immediate_first_action="MASSIVE HEMORRHAGE: Apply direct pressure and pack wound or apply windlass tourniquet 2-3 inches above bleeding site.",
            action_checklist=[
                "Expose wound and press firmly with clean dressing",
                "Apply tourniquet until bright arterial spurting stops",
                "Record exact time of tourniquet placement on patient forehead",
                "Keep patient warm to combat hypothermia"
            ],
            contraindications=["Never loosen or remove a tourniquet once applied."],
            call_emergency_services_now=True,
            estimated_priority_score=95
        )

    if req.allergic_swelling:
        return TriageAssessmentResponse(
            triage_color="RED",
            risk_level=RiskLevel.CRITICAL,
            immediate_first_action="SUSPECTED ANAPHYLAXIS: Administer Epinephrine Auto-Injector (EpiPen 0.3mg) into outer mid-thigh immediately.",
            action_checklist=[
                "Inject EpiPen 0.3mg into anterolateral thigh, hold 3 seconds",
                "Call emergency medical dispatch (911/112)",
                "Lay patient flat with legs elevated (unless vomiting/dyspneic)",
                "Repeat injection in 5-15 mins if airway swelling persists"
            ],
            contraindications=["Do not rely on oral antihistamines for airway compromise."],
            call_emergency_services_now=True,
            estimated_priority_score=90
        )

    if not req.consciousness:
        return TriageAssessmentResponse(
            triage_color="RED",
            risk_level=RiskLevel.CRITICAL,
            immediate_first_action="UNRESPONSIVE BUT BREATHING: Place patient in the Recovery Position on their side to prevent airway aspiration.",
            action_checklist=[
                "Roll patient onto side, tilt head back gently to open airway",
                "Check breathing every 60 seconds",
                "Loosen tight clothing around neck",
                "Call 911/112"
            ],
            contraindications=["Do not give oral fluids, food, or pills."],
            call_emergency_services_now=True,
            estimated_priority_score=85
        )

    # 2. Urgent / Delayed (YELLOW)
    if req.chest_pain:
        return TriageAssessmentResponse(
            triage_color="YELLOW",
            risk_level=RiskLevel.HIGH,
            immediate_first_action="CARDIAC CHEST DISCOMFORT: Place patient in seated semi-Fowler position, rest, call EMS, check for Aspirin allergy.",
            action_checklist=[
                "Call 911 immediately and state 'Suspected Acute Coronary Syndrome'",
                "Check personal memory vault for Aspirin allergy or bleeding history",
                "If no contraindications, chew 325mg adult aspirin",
                "Monitor for loss of consciousness"
            ],
            contraindications=["DO NOT administer Aspirin if patient is allergic or has active bleeding."],
            call_emergency_services_now=True,
            estimated_priority_score=75
        )

    # 3. Minor (GREEN)
    return TriageAssessmentResponse(
        triage_color="GREEN",
        risk_level=RiskLevel.MEDIUM,
        immediate_first_action="STABLE / WALKING WOUNDED: Patient conscious and breathing normally. Clean and dress injuries.",
        action_checklist=[
            "Clean wounds with clean water and apply sterile bandage",
            "Monitor vitals for signs of delayed shock",
            "Re-assess if symptoms worsen"
        ],
        contraindications=["Do not leave injured patient unattended in hazard area."],
        call_emergency_services_now=False,
        estimated_priority_score=30
    )
