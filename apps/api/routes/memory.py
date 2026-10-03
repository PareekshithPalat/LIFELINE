from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from models.schemas import EvidenceItem, PersonalProfile, IncidentObservation
from edge.qdrant.client import get_qdrant_manager
from edge.stores import get_profile_store, get_incident_store, get_trusted_store
from edge import memory_service
from apps.api.security import require_admin

router = APIRouter(prefix="/memory", tags=["Memory Tiers"])


@router.get("/trusted", response_model=List[EvidenceItem])
def list_trusted_protocols():
    return sorted(get_trusted_store().all(), key=lambda i: i.title)


@router.post("/trusted", response_model=EvidenceItem, dependencies=[Depends(require_admin)])
def create_or_update_trusted_protocol(item: EvidenceItem):
    stored = memory_service.upsert_trusted(item)
    if stored is None:
        current = get_trusted_store().get(item.id)
        raise HTTPException(409, f"Rejected by TRUSTED_AUTHORITY: version {item.version} is not newer than "
                                 f"the stored version {current.version if current else '?'}.")
    return stored


@router.get("/personal", response_model=PersonalProfile)
def get_personal_profile():
    return get_profile_store().get()


@router.put("/personal", response_model=PersonalProfile)
def update_personal_profile(profile: PersonalProfile):
    return memory_service.update_profile(profile)


@router.get("/incident", response_model=List[IncidentObservation])
def list_incident_observations(incident_id: Optional[str] = Query(None)):
    return get_incident_store().list(incident_id)


@router.post("/incident", response_model=IncidentObservation)
def log_incident_observation(obs: IncidentObservation):
    try:
        return memory_service.log_observation(obs)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/stats")
def get_memory_stats():
    return get_qdrant_manager().get_stats()
