from enum import Enum

class RiskLevel(str, Enum):
    CRITICAL = "CRITICAL"   # Life threat: cardiac arrest, severe hemorrhage, anaphylaxis, choking, apnea
    HIGH = "HIGH"           # Major burns, fractures, seizure, poisoning, acute asthma
    MEDIUM = "MEDIUM"       # Sprains, mild lacerations, minor allergic reaction, dosage check
    LOW = "LOW"             # General preparedness, first aid kit guide, routine safety

class MemoryTier(str, Enum):
    TRUSTED = "TRUSTED"     # Verified clinical first-aid guidelines, triage protocols, hospital directories
    PERSONAL = "PERSONAL"   # User medical profile, allergies, medications, blood type, ICE contacts
    INCIDENT = "INCIDENT"   # Real-time incident observations, vitals, actions logged on-scene

class ValidationVerdict(str, Enum):
    SUFFICIENT = "SUFFICIENT"     # Clear, unambiguous evidence; proceed with grounded response
    CONFLICT = "CONFLICT"         # Conflicting instructions or active contraindication; escalate with safety warnings
    INSUFFICIENT = "INSUFFICIENT" # Insufficient or off-domain evidence; abstain from guessing, surface emergency numbers

class QueryIntent(str, Enum):
    FIRST_AID_INSTRUCTION = "FIRST_AID_INSTRUCTION"
    TRIAGE_ASSESSMENT = "TRIAGE_ASSESSMENT"
    CONTRAINDICATION_CHECK = "CONTRAINDICATION_CHECK"
    PERSONAL_MED_CHECK = "PERSONAL_MED_CHECK"
    INCIDENT_UPDATE = "INCIDENT_UPDATE"
    EMERGENCY_CONTACT = "EMERGENCY_CONTACT"
    GENERAL_PREPAREDNESS = "GENERAL_PREPAREDNESS"

class SyncStatus(str, Enum):
    SYNCED = "SYNCED"
    PENDING_PUSH = "PENDING_PUSH"
    PENDING_PULL = "PENDING_PULL"
    CONFLICT = "CONFLICT"

class ConflictStrategy(str, Enum):
    SAFETY_MAXIMUM = "SAFETY_MAXIMUM"  # Retain all allergy/contraindication warnings (never delete warning)
    TRUSTED_AUTHORITY = "TRUSTED_AUTHORITY" # Signed upstream medical guidelines always take precedence
    MONOTONIC_APPEND = "MONOTONIC_APPEND" # Incident observations are append-only CRDT
