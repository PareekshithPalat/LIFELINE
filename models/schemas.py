from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import hashlib
from models.enums import RiskLevel, MemoryTier, ValidationVerdict, QueryIntent, SyncStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    author: Optional[str] = None
    freshness_timestamp: Optional[str] = None
    contraindications_found: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    id: str
    tier: MemoryTier
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    # Lay-language descriptions of the situation this protocol answers. They are
    # embedded as separate chunks so symptom-style queries match precisely.
    triggers: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    contraindications: List[str] = Field(default_factory=list)
    author: str = "clinical_authority"
    version: int = 1
    hash: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    media_url: Optional[str] = None
    media_local_path: Optional[str] = None
    verified: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context):
        if not self.hash:
            self.hash = compute_evidence_hash(self.content, self.title, self.version)

    def rehash(self) -> "EvidenceItem":
        self.hash = compute_evidence_hash(self.content, self.title, self.version)
        return self


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
    last_updated: str = Field(default_factory=utc_now)
    version: int = 1
    synced: bool = True


class IncidentObservation(BaseModel):
    id: str = ""
    incident_id: str = "active_incident"
    timestamp: str = Field(default_factory=utc_now)
    vital_signs: Dict[str, Any] = Field(default_factory=dict)  # pulse, bp, spo2, breathing_rate, consciousness
    observed_symptoms: List[str] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    severity: RiskLevel = RiskLevel.HIGH
    reporter: str = "edge_first_responder"
    origin_node: Optional[str] = None
    version: int = 1
    synced: bool = False


class EmergencyQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    incident_id: Optional[str] = "active_incident"
    allow_cache: bool = True
    # "adult" | "child" | "infant"; when omitted it is inferred from the query text.
    age_category: Optional[str] = None
    patient_context_override: Optional[Dict[str, Any]] = None


class GroundedResponse(BaseModel):
    query: str
    risk_level: RiskLevel
    intent: QueryIntent
    verdict: ValidationVerdict
    answer: str
    immediate_actions: List[str] = Field(default_factory=list)
    contraindications_and_warnings: List[str] = Field(default_factory=list)
    withheld_actions: List[str] = Field(default_factory=list)
    citations: List[SourceCitation] = Field(default_factory=list)
    related_protocols: List[str] = Field(default_factory=list)
    escalation_needed: bool = False
    emergency_contacts_to_call: List[Dict[str, str]] = Field(default_factory=list)
    confidence: float = 0.0
    age_category: str = "adult"
    retrieval_mode: str = "hybrid"  # hybrid | lexical_only | profile | incident | none
    cache_hit: bool = False
    cache_entry_id: Optional[str] = None
    state_valid: bool = True
    latency_ms: float = 0.0
    offline_mode: bool = True
    edge_timestamp: str = Field(default_factory=utc_now)


class CacheEntry(BaseModel):
    id: str
    query_text: str
    query_vector: List[float] = Field(default_factory=list)
    salient_terms: List[str] = Field(default_factory=list)
    age_category: str = "adult"
    bound_evidence_ids: List[str] = Field(default_factory=list)
    bound_evidence_hashes: Dict[str, str] = Field(default_factory=dict)
    incident_version: int = 0
    personal_version: int = 1
    response: GroundedResponse
    risk_level: RiskLevel
    created_at: float
    last_hit_at: float = 0.0
    ttl_seconds: float
    hit_count: int = 0


class SyncLogEntry(BaseModel):
    id: str
    entity_type: str  # "trusted", "personal", "incident", "media"
    entity_id: str
    operation: str    # "CREATE", "UPDATE", "UPSERT", "UPLOAD"
    origin_node: str = ""
    seq: int = 0      # position in THIS node's log (used as the hub pull cursor)
    vector_clock: Dict[str, int] = Field(default_factory=dict)  # {origin_node: origin_seq}
    timestamp: str = Field(default_factory=utc_now)
    status: SyncStatus = SyncStatus.PENDING_PUSH
    payload: Dict[str, Any] = Field(default_factory=dict)


class SyncPushRequest(BaseModel):
    node_id: str
    entries: List[SyncLogEntry]


class TriageAssessmentRequest(BaseModel):
    consciousness: bool
    breathing: bool
    severe_bleeding: bool
    chest_pain: bool
    allergic_swelling: bool
    burns_extent: Optional[str] = None   # "none" | "minor" | "major"
    age_category: str = "adult"          # adult, adolescent, child, infant
    # False when triaging someone other than the profile owner (their allergies are unknown).
    patient_is_profile_owner: bool = True


class TriageAssessmentResponse(BaseModel):
    triage_color: str  # RED (Immediate), YELLOW (Urgent), GREEN (Minor)
    risk_level: RiskLevel
    immediate_first_action: str
    action_checklist: List[str]
    contraindications: List[str]
    call_emergency_services_now: bool
    estimated_priority_score: int
