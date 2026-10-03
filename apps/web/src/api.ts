import type {
  GroundedResponse,
  PersonalProfile,
  IncidentObservation,
  EvidenceItem,
  TriageAssessmentRequest,
  TriageAssessmentResponse,
  SyncStatusData,
  CacheStatsData,
  SyncResult,
  SystemHealth,
  MediaUploadResult
} from "./types";

const API_BASE = "/api";
const KEY_STORAGE = "lifeline.apiKey";

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable: key lasts for this page only */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Media URLs are loaded by <img>/<a>, which cannot send headers. */
export function mediaUrl(localUrl: string): string {
  const key = getApiKey();
  return key ? `${localUrl}?api_key=${encodeURIComponent(key)}` : localUrl;
}

export const queryEmergency = (query: string, incidentId: string, allowCache = true, ageCategory?: string) =>
  request<GroundedResponse>("/emergency/query", {
    method: "POST",
    body: JSON.stringify({ query, incident_id: incidentId, allow_cache: allowCache, age_category: ageCategory || null })
  });

export const runTriage = (data: TriageAssessmentRequest) =>
  request<TriageAssessmentResponse>("/emergency/triage", { method: "POST", body: JSON.stringify(data) });

export const getPersonalProfile = () => request<PersonalProfile>("/memory/personal");

export const updatePersonalProfile = (profile: PersonalProfile) =>
  request<PersonalProfile>("/memory/personal", { method: "PUT", body: JSON.stringify(profile) });

export const getIncidentObservations = (incidentId?: string) =>
  request<IncidentObservation[]>(
    `/memory/incident${incidentId ? `?incident_id=${encodeURIComponent(incidentId)}` : ""}`
  );

export const logIncidentObservation = (obs: Partial<IncidentObservation>) =>
  request<IncidentObservation>("/memory/incident", { method: "POST", body: JSON.stringify(obs) });

export const getTrustedProtocols = () => request<EvidenceItem[]>("/memory/trusted");

export const getCacheStats = () => request<CacheStatsData>("/cache/stats");

export const clearCache = () => request<{ message: string }>("/cache/clear", { method: "POST" });

export const getSyncStatus = () => request<SyncStatusData>("/sync/status");

export const triggerSync = () => request<SyncResult>("/sync/trigger", { method: "POST" });

export const toggleNetwork = (online: boolean) =>
  request<{ is_online: boolean }>("/sync/toggle-network", { method: "POST", body: JSON.stringify({ online }) });

export const uploadMedia = (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return request<MediaUploadResult>("/media/upload", { method: "POST", body: formData });
};

export const getSystemHealth = () => request<SystemHealth>("/system/health");
