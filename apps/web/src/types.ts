export type RiskLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type MemoryTier = "TRUSTED" | "PERSONAL" | "INCIDENT";
export type ValidationVerdict = "SUFFICIENT" | "CONFLICT" | "INSUFFICIENT";
export type QueryIntent =
  | "FIRST_AID_INSTRUCTION"
  | "TRIAGE_ASSESSMENT"
  | "CONTRAINDICATION_CHECK"
  | "PERSONAL_MED_CHECK"
  | "INCIDENT_UPDATE"
  | "EMERGENCY_CONTACT"
  | "GENERAL_PREPAREDNESS";

export interface SourceCitation {
  evidence_id: string;
  tier: MemoryTier;
  title: string;
  snippet: string;
  version: number;
  hash: string;
  relevance_score: number;
  freshness_timestamp?: string;
  contraindications_found: string[];
}

export interface GroundedResponse {
  query: string;
  risk_level: RiskLevel;
  intent: QueryIntent;
  verdict: ValidationVerdict;
  answer: string;
  immediate_actions: string[];
  contraindications_and_warnings: string[];
  citations: SourceCitation[];
  escalation_needed: boolean;
  emergency_contacts_to_call: Array<{ name: string; relationship: string; phone: string }>;
  cache_hit: boolean;
  cache_entry_id?: string;
  state_valid: boolean;
  latency_ms: number;
  offline_mode: boolean;
  edge_timestamp: string;
}

export interface EmergencyContact {
  name: string;
  relationship: string;
  phone: string;
  priority: number;
}

export interface PersonalProfile {
  user_id: string;
  full_name: string;
  dob?: string;
  blood_group: string;
  allergies: string[];
  current_medications: string[];
  chronic_conditions: string[];
  emergency_contacts: EmergencyContact[];
  medical_notes: string;
  ice_instructions: string;
  last_updated: string;
  version: number;
  synced: boolean;
}

export interface IncidentObservation {
  id: string;
  incident_id: string;
  timestamp: string;
  vital_signs: Record<string, any>;
  observed_symptoms: string[];
  actions_taken: string[];
  severity: RiskLevel;
  reporter: string;
  version: number;
  synced: boolean;
}

export interface EvidenceItem {
  id: string;
  tier: MemoryTier;
  title: string;
  content: string;
  tags: string[];
  risk_level: RiskLevel;
  contraindications: string[];
  author: string;
  version: number;
  hash: string;
  created_at: string;
  updated_at: string;
  media_url?: string;
  media_local_path?: string;
  verified: boolean;
}

export interface TriageAssessmentRequest {
  consciousness: boolean;
  breathing: boolean;
  severe_bleeding: boolean;
  chest_pain: boolean;
  allergic_swelling: boolean;
  burns_extent?: string;
  age_category: string;
}

export interface TriageAssessmentResponse {
  triage_color: "RED" | "YELLOW" | "GREEN" | "BLACK";
  risk_level: RiskLevel;
  immediate_first_action: string;
  action_checklist: string[];
  contraindications: string[];
  call_emergency_services_now: boolean;
  estimated_priority_score: number;
}

export interface SyncStatusData {
  node_id: string;
  is_online: boolean;
  pending_sync_count: number;
  total_mutation_log_count: number;
  last_synced_at?: string;
  remote_server_configured: boolean;
}

export interface CacheStatsData {
  hits: number;
  misses: number;
  state_invalidations: number;
  expired_evictions: number;
  total_queries: number;
  active_cached_entries: number;
  hit_rate_pct: number;
}
