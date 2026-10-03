export type RiskLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type AgeCategory = "adult" | "adolescent" | "child" | "infant";
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
  author?: string;
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
  withheld_actions: string[];
  citations: SourceCitation[];
  related_protocols: string[];
  escalation_needed: boolean;
  emergency_contacts_to_call: Array<{ name: string; relationship: string; phone: string }>;
  confidence: number;
  age_category: AgeCategory;
  retrieval_mode: "hybrid" | "lexical_only" | "profile" | "incident" | "none";
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
  origin_node?: string;
  version: number;
  synced: boolean;
}

export interface EvidenceItem {
  id: string;
  tier: MemoryTier;
  title: string;
  content: string;
  tags: string[];
  triggers: string[];
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
  burns_extent?: "none" | "minor" | "major";
  age_category: AgeCategory;
  patient_is_profile_owner: boolean;
}

export interface TriageAssessmentResponse {
  triage_color: "RED" | "YELLOW" | "GREEN";
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
  last_synced_at?: string | null;
  last_error?: string | null;
  remote_server_configured: boolean;
  remote_server_url?: string | null;
  hub_seq: number;
}

export interface SyncResult {
  success: boolean;
  status: "NO_UPSTREAM" | "OFFLINE" | "UNREACHABLE" | "ONLINE_SYNCED";
  message: string;
  pending_count: number;
  pushed?: number;
  pulled?: number;
}

export interface CollectionStats {
  documents: number;
  points_count: number;
  status: string;
}

export interface SystemHealth {
  status: string;
  mode: string;
  is_network_online: boolean;
  edge_node_id: string;
  storage_mode: string;
  dense_model_ready: boolean;
  auth_required: boolean;
  cache_entries: number;
  collections: Record<string, CollectionStats | string>;
}

export interface MediaUploadResult {
  media_id: string;
  filename: string;
  content_type: string;
  local_url: string;
  remote_url: string | null;
  status: string;
  size_bytes: number;
  timestamp: string;
}

export interface CacheStatsData {
  hits: number;
  misses: number;
  state_invalidations: number;
  expired_evictions: number;
  lru_evictions: number;
  salient_mismatches: number;
  total_queries: number;
  active_cached_entries: number;
  hit_rate_pct: number;
}
