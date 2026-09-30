import type {
  GroundedResponse,
  PersonalProfile,
  IncidentObservation,
  EvidenceItem,
  TriageAssessmentRequest,
  TriageAssessmentResponse,
  SyncStatusData,
  CacheStatsData
} from "./types";

const API_BASE = "/api";

export async function queryEmergency(query: string, allowCache = true): Promise<GroundedResponse> {
  const res = await fetch(`${API_BASE}/emergency/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, allow_cache: allowCache })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Emergency query failed" }));
    throw new Error(err.detail || "Query failed");
  }
  return res.json();
}

export async function runTriage(data: TriageAssessmentRequest): Promise<TriageAssessmentResponse> {
  const res = await fetch(`${API_BASE}/emergency/triage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error("Triage request failed");
  return res.json();
}

export async function getPersonalProfile(): Promise<PersonalProfile> {
  const res = await fetch(`${API_BASE}/memory/personal`);
  if (!res.ok) throw new Error("Failed to load personal profile");
  return res.json();
}

export async function updatePersonalProfile(profile: PersonalProfile): Promise<PersonalProfile> {
  const res = await fetch(`${API_BASE}/memory/personal`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile)
  });
  if (!res.ok) throw new Error("Failed to update profile");
  return res.json();
}

export async function getIncidentObservations(): Promise<IncidentObservation[]> {
  const res = await fetch(`${API_BASE}/memory/incident`);
  if (!res.ok) throw new Error("Failed to load incident timeline");
  return res.json();
}

export async function logIncidentObservation(obs: Partial<IncidentObservation>): Promise<IncidentObservation> {
  const res = await fetch(`${API_BASE}/memory/incident`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(obs)
  });
  if (!res.ok) throw new Error("Failed to log incident");
  return res.json();
}

export async function getTrustedProtocols(): Promise<EvidenceItem[]> {
  const res = await fetch(`${API_BASE}/memory/trusted`);
  if (!res.ok) throw new Error("Failed to load trusted guidelines");
  return res.json();
}

export async function getCacheStats(): Promise<CacheStatsData> {
  const res = await fetch(`${API_BASE}/cache/stats`);
  if (!res.ok) throw new Error("Failed to load cache stats");
  return res.json();
}

export async function clearCache(): Promise<void> {
  const res = await fetch(`${API_BASE}/cache/clear`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to clear cache");
}

export async function getSyncStatus(): Promise<SyncStatusData> {
  const res = await fetch(`${API_BASE}/sync/status`);
  if (!res.ok) throw new Error("Failed to load sync status");
  return res.json();
}

export async function triggerSync(): Promise<any> {
  const res = await fetch(`${API_BASE}/sync/trigger`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger sync");
  return res.json();
}

export async function toggleNetwork(online: boolean): Promise<any> {
  const res = await fetch(`${API_BASE}/sync/toggle-network`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ online })
  });
  if (!res.ok) throw new Error("Failed to toggle network mode");
  return res.json();
}

export async function uploadMedia(file: File): Promise<any> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/media/upload`, {
    method: "POST",
    body: formData
  });
  if (!res.ok) throw new Error("Failed to upload media");
  return res.json();
}

export async function getSystemHealth(): Promise<any> {
  const res = await fetch(`${API_BASE}/system/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}
