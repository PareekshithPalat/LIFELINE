import json
import os
import uuid
from typing import List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from models.enums import MemoryTier, RiskLevel, SyncStatus
from models.schemas import EvidenceItem, PersonalProfile, IncidentObservation
from edge.qdrant.client import get_qdrant_manager
from edge.sync.controller import get_sync_controller
from edge.cache.semantic_cache import get_semantic_cache

router = APIRouter(prefix="/memory", tags=["Memory Tiers"])

PERSONAL_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "default_personal.json"))
INCIDENT_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "incidents.json"))

# 1. Trusted Memory Endpoints
@router.get("/trusted", response_model=List[EvidenceItem])
async def list_trusted_protocols():
    qdrant = get_qdrant_manager()
    return qdrant.list_evidence(tier=MemoryTier.TRUSTED, limit=100)

@router.post("/trusted", response_model=EvidenceItem)
async def create_or_update_trusted_protocol(item: EvidenceItem):
    item.tier = MemoryTier.TRUSTED
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()
    cache = get_semantic_cache()

    success = qdrant.upsert_evidence(item)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to upsert trusted guideline into Qdrant Edge")

    sync.record_mutation(
        entity_type="trusted",
        entity_id=item.id,
        operation="UPSERT",
        payload=item.model_dump()
    )
    cache.invalidate_all()
    return item

# 2. Personal Medical Memory Endpoints
@router.get("/personal", response_model=PersonalProfile)
async def get_personal_profile():
    if os.path.exists(PERSONAL_FILE):
        try:
            with open(PERSONAL_FILE, "r", encoding="utf-8") as f:
                return PersonalProfile.model_validate(json.load(f))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read personal profile: {e}")
    return PersonalProfile(full_name="Emergency Patient", blood_group="O-")

@router.put("/personal", response_model=PersonalProfile)
async def update_personal_profile(profile: PersonalProfile):
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()
    cache = get_semantic_cache()

    profile.version += 1
    profile.last_updated = datetime.now(timezone.utc).isoformat()
    profile.synced = sync.is_online

    # Persist to disk
    os.makedirs(os.path.dirname(PERSONAL_FILE), exist_ok=True)
    with open(PERSONAL_FILE, "w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, indent=2)

    # Index in Qdrant Personal Memory Tier
    allergies_str = ", ".join(profile.allergies)
    meds_str = ", ".join(profile.current_medications)
    conditions_str = ", ".join(profile.chronic_conditions)
    content = (
        f"Personal Emergency Profile for {profile.full_name}:\n"
        f"Blood Group: {profile.blood_group}\n"
        f"Allergies: {allergies_str}\n"
        f"Current Medications: {meds_str}\n"
        f"Chronic Conditions: {conditions_str}\n"
        f"ICE Instructions: {profile.ice_instructions}\n"
        f"Notes: {profile.medical_notes}"
    )
    personal_item = EvidenceItem(
        id=f"profile-{profile.user_id}",
        tier=MemoryTier.PERSONAL,
        title=f"Emergency Profile - {profile.full_name}",
        content=content,
        tags=["profile", "personal", "allergies", "blood_group", "ice"],
        risk_level=RiskLevel.HIGH,
        contraindications=[f"Patient allergic to {a}" for a in profile.allergies],
        author="user_personal_vault",
        version=profile.version,
        verified=True
    )
    qdrant.upsert_evidence(personal_item)

    # Log mutation for sync
    sync.record_mutation(
        entity_type="personal",
        entity_id=profile.user_id,
        operation="UPDATE",
        payload=profile.model_dump()
    )

    # State invalidation for cache
    cache.invalidate_all()

    return profile

# 3. Incident Memory Endpoints
def _load_incidents() -> List[IncidentObservation]:
    if os.path.exists(INCIDENT_FILE):
        try:
            with open(INCIDENT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [IncidentObservation.model_validate(x) for x in data]
        except Exception:
            return []
    return []

def _save_incidents(items: List[IncidentObservation]):
    os.makedirs(os.path.dirname(INCIDENT_FILE), exist_ok=True)
    with open(INCIDENT_FILE, "w", encoding="utf-8") as f:
        json.dump([x.model_dump() for x in items], f, indent=2)

@router.get("/incident", response_model=List[IncidentObservation])
async def list_incident_observations():
    return _load_incidents()

@router.post("/incident", response_model=IncidentObservation)
async def log_incident_observation(obs: IncidentObservation):
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()
    cache = get_semantic_cache()

    if not obs.id:
        obs.id = f"obs-{uuid.uuid4().hex[:8]}"
    obs.timestamp = datetime.now(timezone.utc).isoformat()
    obs.synced = sync.is_online

    # Save to disk
    items = _load_incidents()
    obs.version = len(items) + 1
    items.insert(0, obs)
    _save_incidents(items)

    # Index in Qdrant Incident Memory Tier
    vitals_summary = ", ".join(f"{k}: {v}" for k, v in obs.vital_signs.items())
    symptoms_summary = ", ".join(obs.observed_symptoms)
    actions_summary = ", ".join(obs.actions_taken)
    content = (
        f"Incident Observation [{obs.severity.value}] at {obs.timestamp}:\n"
        f"Vitals: {vitals_summary or 'None'}\n"
        f"Observed Symptoms: {symptoms_summary or 'None'}\n"
        f"Actions Taken On-Scene: {actions_summary or 'None'}\n"
        f"Reporter: {obs.reporter}"
    )
    ev = EvidenceItem(
        id=obs.id,
        tier=MemoryTier.INCIDENT,
        title=f"Incident Observation #{obs.version}",
        content=content,
        tags=["incident", "timeline", "observation", "vitals"],
        risk_level=obs.severity,
        contraindications=[],
        author=obs.reporter,
        version=obs.version,
        verified=True
    )
    qdrant.upsert_evidence(ev)

    # Log sync mutation
    sync.record_mutation(
        entity_type="incident",
        entity_id=obs.id,
        operation="CREATE",
        payload=obs.model_dump()
    )

    # Invalidate cache due to state evolution
    cache.invalidate_all()

    return obs

@router.get("/stats")
async def get_memory_stats():
    qdrant = get_qdrant_manager()
    return qdrant.get_stats()
