from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import hashlib
from models.enums import RiskLevel, MemoryTier, ValidationVerdict, QueryIntent, SyncStatus

def compute_evidence_hash(content: str, title: str, version: int) -> str:
    payload = f"{title}:{content}:{version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

class SourceCitation(BaseModel):
    evidence_id: str
    tier: MemoryTier
    title: str
    snippet: str
    version: int
    hash: str
    relevance_score: float
    freshness_timestamp: Optional[str] = None
    contraindications_found: List[str] = Field(default_factory=list)

class EvidenceItem(BaseModel):
    id: str
    tier: MemoryTier
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    contraindications: List[str] = Field(default_factory=list)
    author: str = "clinical_authority"
    version: int = 1
    hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    media_url: Optional[str] = None
    media_local_path: Optional[str] = None
    verified: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context):
        if not self.hash:
            self.hash = compute_evidence_hash(self.content, self.title, self.version)

class EmergencyContact(BaseModel):
    name: str
    relationship: str
    phone: str
    priority: int = 1

class PersonalProfile(BaseModel):
    user_id: str = "primary_user"
    full_name: str
    dob: Optional[str] = None
    blood_group: str
    allergies: List[str] = Field(default_factory=list)
    current_medications: List[str] = Field(default_factory=list)
    chronic_conditions: List[str] = Field(default_factory=list)
    emergency_contacts: List[EmergencyContact] = Field(default_factory=list)
    medical_notes: str = ""
    ice_instructions: str = ""
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = 1
    synced: bool = True

class IncidentObservation(BaseModel):
    id: str
    incident_id: str = "active_incident"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    vital_signs: Dict[str, Any] = Field(default_factory=dict)  # pulse, bp, sp02, breathing_rate, consciousness
    observed_symptoms: List[str] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    severity: RiskLevel = RiskLevel.HIGH
    reporter: str = "edge_first_responder"
    version: int = 1
    synced: bool = False

class EmergencyQueryRequest(BaseModel):
    query: str
    incident_id: Optional[str] = "active_incident"
    allow_cache: bool = True
    force_tier: Optional[MemoryTier] = None
    patient_context_override: Optional[Dict[str, Any]] = None

class GroundedResponse(BaseModel):
    query: str
    risk_level: RiskLevel
    intent: QueryIntent
    verdict: ValidationVerdict
    answer: str
    immediate_actions: List[str] = Field(default_factory=list)
    contraindications_and_warnings: List[str] = Field(default_factory=list)
    citations: List[SourceCitation] = Field(default_factory=list)
    escalation_needed: bool = False
    emergency_contacts_to_call: List[Dict[str, str]] = Field(default_factory=list)
    cache_hit: bool = False
    cache_entry_id: Optional[str] = None
    state_valid: bool = True
    latency_ms: float = 0.0
    offline_mode: bool = True
    edge_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class CacheEntry(BaseModel):
    id: str
    query_text: str
    query_vector: List[float] = Field(default_factory=list)
    bound_evidence_ids: List[str] = Field(default_factory=list)
    bound_evidence_hashes: Dict[str, str] = Field(default_factory=dict)
    incident_version: int = 1
    personal_version: int = 1
    response: GroundedResponse
    risk_level: RiskLevel
    created_at: float
    ttl_seconds: float
    hit_count: int = 0

class SyncLogEntry(BaseModel):
    id: str
    entity_type: str  # "trusted", "personal", "incident", "media"
    entity_id: str
    operation: str    # "CREATE", "UPDATE", "DELETE"
    vector_clock: Dict[str, int] = Field(default_factory=dict) # e.g. {"edge-01": 4, "server": 3}
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: SyncStatus = SyncStatus.PENDING_PUSH
    payload: Dict[str, Any] = Field(default_factory=dict)

class TriageAssessmentRequest(BaseModel):
    consciousness: bool
    breathing: bool
    severe_bleeding: bool
    chest_pain: bool
    allergic_swelling: bool
    burns_extent: Optional[str] = None
    age_category: str = "adult"  # adult, child, infant

class TriageAssessmentResponse(BaseModel):
    triage_color: str  # RED (Immediate), YELLOW (Delayed), GREEN (Minor), BLACK (Expectant)
    risk_level: RiskLevel
    immediate_first_action: str
    action_checklist: List[str]
    contraindications: List[str]
    call_emergency_services_now: bool
    estimated_priority_score: int
