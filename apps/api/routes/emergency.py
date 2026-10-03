from fastapi import APIRouter
from models.schemas import (EmergencyQueryRequest, GroundedResponse, TriageAssessmentRequest,
                            TriageAssessmentResponse, PersonalProfile)
from edge.runtime.pipeline import get_pipeline
from edge.runtime.triage import assess
from edge.stores import get_profile_store

router = APIRouter(prefix="/emergency", tags=["Emergency Engine"])


@router.post("/query", response_model=GroundedResponse)
def process_emergency_query(req: EmergencyQueryRequest):
    profile = get_profile_store().get()
    allow_cache = req.allow_cache
    if req.patient_context_override:
        # A one-off patient context must never be served from, or written to, the shared cache.
        profile = PersonalProfile.model_validate({**profile.model_dump(), **req.patient_context_override})
        allow_cache = False
    return get_pipeline().process_query(
        query=req.query,
        personal_profile=profile,
        incident_id=req.incident_id or "active_incident",
        allow_cache=allow_cache,
        age_category=req.age_category,
    )


@router.post("/triage", response_model=TriageAssessmentResponse)
def rapid_triage_assessment(req: TriageAssessmentRequest):
    return assess(req, get_profile_store().get(), req.patient_is_profile_owner)
