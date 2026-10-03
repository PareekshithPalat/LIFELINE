import { useState, useEffect } from "react";
import {
  Heart,
  Shield,
  Activity,
  Wifi,
  WifiOff,
  RefreshCw,
  Search,
  AlertTriangle,
  CheckCircle,
  Clock,
  Database,
  FileText,
  User,
  Zap,
  PhoneCall,
  Camera,
  AlertOctagon,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Layers,
  Save,
  KeyRound,
  EyeOff
} from "lucide-react";
import {
  queryEmergency,
  runTriage,
  getPersonalProfile,
  updatePersonalProfile,
  getIncidentObservations,
  logIncidentObservation,
  getTrustedProtocols,
  getCacheStats,
  clearCache,
  getSyncStatus,
  triggerSync,
  toggleNetwork,
  uploadMedia,
  getSystemHealth,
  getApiKey,
  setApiKey,
  mediaUrl,
  ApiError
} from "./api";
import type {
  GroundedResponse,
  PersonalProfile,
  IncidentObservation,
  EvidenceItem,
  TriageAssessmentRequest,
  TriageAssessmentResponse,
  SyncStatusData,
  CacheStatsData,
  SystemHealth,
  MediaUploadResult,
  AgeCategory
} from "./types";

/** Backend actions are already numbered ("1. ..."); the UI draws its own badges. */
const stripNumber = (s: string) => s.replace(/^\d+\.\s+/, "");

type ListField = "allergies" | "chronic_conditions" | "current_medications";

export default function App() {
  const [activeTab, setActiveTab] = useState<
    "assistant" | "triage" | "vault" | "timeline" | "guidelines" | "diagnostics"
  >("assistant");

  // System & Edge Status
  const [syncStatus, setSyncStatus] = useState<SyncStatusData | null>(null);
  const [cacheStats, setCacheStats] = useState<CacheStatsData | null>(null);
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [needsKey, setNeedsKey] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState(getApiKey());

  // Assistant State
  const [queryText, setQueryText] = useState("");
  const [queryAge, setQueryAge] = useState<"" | AgeCategory>("");
  const [response, setResponse] = useState<GroundedResponse | null>(null);
  const [showCitations, setShowCitations] = useState(true);

  // Triage State
  const [triageInput, setTriageInput] = useState<TriageAssessmentRequest>({
    consciousness: true,
    breathing: true,
    severe_bleeding: false,
    chest_pain: false,
    allergic_swelling: false,
    burns_extent: "none",
    age_category: "adult",
    patient_is_profile_owner: true
  });
  const [triageResult, setTriageResult] = useState<TriageAssessmentResponse | null>(null);

  // Personal Profile State
  const [profile, setProfile] = useState<PersonalProfile | null>(null);
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [editedProfile, setEditedProfile] = useState<PersonalProfile | null>(null);
  const [newItem, setNewItem] = useState<Record<ListField, string>>({
    allergies: "",
    chronic_conditions: "",
    current_medications: ""
  });

  // Incident State
  const [incidentId, setIncidentId] = useState("active_incident");
  const [incidents, setIncidents] = useState<IncidentObservation[]>([]);
  const [newObsSymptoms, setNewObsSymptoms] = useState("");
  const [newObsActions, setNewObsActions] = useState("");
  const [newPulse, setNewPulse] = useState("78");
  const [newSpO2, setNewSpO2] = useState("98");

  // Guidelines State
  const [guidelines, setGuidelines] = useState<EvidenceItem[]>([]);
  const [guidelineSearch, setGuidelineSearch] = useState("");

  // Media State
  const [mediaUploadStatus, setMediaUploadStatus] = useState<MediaUploadResult | null>(null);

  const handleError = (e: unknown, fallback: string) => {
    if (e instanceof ApiError && e.status === 401) {
      setNeedsKey(true);
      showNotice("This Lifeline node requires an API key.");
    } else {
      showNotice(e instanceof Error ? e.message : fallback);
    }
  };

  // Load Initial Edge Data
  const refreshAll = async (incident = incidentId) => {
    const health = await getSystemHealth().catch(() => null);
    setSystemHealth(health);
    try {
      const [sStatus, cStats, pProfile, iList, gList] = await Promise.all([
        getSyncStatus(),
        getCacheStats(),
        getPersonalProfile(),
        getIncidentObservations(incident),
        getTrustedProtocols()
      ]);
      setNeedsKey(false);
      setSyncStatus(sStatus);
      setCacheStats(cStats);
      setProfile(pProfile);
      setEditedProfile(pProfile);
      setIncidents(iList);
      setGuidelines(gList);
    } catch (e) {
      handleError(e, "Could not reach the Lifeline node");
    }
  };

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNetworkToggle = async () => {
    if (!syncStatus) return;
    try {
      const nextOnline = !syncStatus.is_online;
      await toggleNetwork(nextOnline);
      setSyncStatus(await getSyncStatus());
      showNotice(`Network switched to ${nextOnline ? "ONLINE" : "OFFLINE EDGE MODE"}`);
    } catch (e) {
      handleError(e, "Failed to toggle network mode");
    }
  };

  const handleTriggerSync = async () => {
    try {
      setLoading(true);
      const res = await triggerSync();
      setSyncStatus(await getSyncStatus());
      showNotice(res.message);
      if (res.status === "ONLINE_SYNCED" && (res.pulled ?? 0) > 0) await refreshAll();
    } catch (e) {
      handleError(e, "Sync failed");
    } finally {
      setLoading(false);
    }
  };

  const showNotice = (msg: string) => {
    setStatusMessage(msg);
    setTimeout(() => setStatusMessage(null), 4000);
  };

  const saveApiKey = async () => {
    setApiKey(apiKeyInput.trim());
    await refreshAll();
  };

  // Submit Emergency Query
  const handleQuerySubmit = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setQueryText(q);
    try {
      setResponse(await queryEmergency(q, incidentId, true, queryAge || undefined));
      setCacheStats(await getCacheStats());
    } catch (e) {
      handleError(e, "Emergency query failed");
    } finally {
      setLoading(false);
    }
  };

  // Run Triage
  const handleTriageSubmit = async () => {
    setLoading(true);
    try {
      setTriageResult(await runTriage(triageInput));
    } catch (e) {
      handleError(e, "Triage calculation error");
    } finally {
      setLoading(false);
    }
  };

  // Save Profile
  const handleSaveProfile = async () => {
    if (!editedProfile) return;
    setLoading(true);
    try {
      const saved = await updatePersonalProfile(editedProfile);
      setProfile(saved);
      setIsEditingProfile(false);
      await refreshAll();
      showNotice(`Personal vault saved (version ${saved.version}). Cached answers for the old profile are no longer served.`);
    } catch (e) {
      handleError(e, "Failed to save personal profile");
    } finally {
      setLoading(false);
    }
  };

  const addListItem = (field: ListField) => {
    const value = newItem[field].trim();
    if (!editedProfile || !value) return;
    setEditedProfile({ ...editedProfile, [field]: [...editedProfile[field], value] });
    setNewItem({ ...newItem, [field]: "" });
  };

  const removeListItem = (field: ListField, index: number) => {
    if (!editedProfile) return;
    setEditedProfile({ ...editedProfile, [field]: editedProfile[field].filter((_, i) => i !== index) });
  };

  // Log Incident Observation
  const handleLogObservation = async () => {
    if (!newObsSymptoms && !newObsActions) return;
    setLoading(true);
    const split = (v: string) => (v ? v.split(",").map((s) => s.trim()).filter(Boolean) : []);
    try {
      await logIncidentObservation({
        incident_id: incidentId,
        observed_symptoms: split(newObsSymptoms),
        actions_taken: split(newObsActions),
        vital_signs: { pulse: `${newPulse} bpm`, spO2: `${newSpO2}%` },
        severity: "HIGH"
      });
      setNewObsSymptoms("");
      setNewObsActions("");
      await refreshAll();
      showNotice("Observation added to the incident timeline.");
    } catch (e) {
      handleError(e, "Failed to record observation");
    } finally {
      setLoading(false);
    }
  };

  // File Upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    setLoading(true);
    try {
      const res = await uploadMedia(file);
      setMediaUploadStatus(res);
      showNotice(`Media stored on this device: ${res.filename}`);
      refreshAll();
    } catch (err) {
      handleError(err, "Media upload failed");
    } finally {
      setLoading(false);
      e.target.value = "";
    }
  };

  const QUICK_SCENARIOS = [
    { title: "Adult CPR / Unconscious", query: "Adult is unresponsive and not breathing. Start CPR protocol" },
    { title: "Severe Bleeding / Tourniquet", query: "Severe spurting arterial bleeding on arm. How to apply tourniquet?" },
    { title: "Anaphylaxis & EpiPen", query: "Patient has throat swelling and hives after bee sting. How to use EpiPen?" },
    { title: "Aspirin Contraindication Check", query: "Can I give the patient Aspirin for acute chest pain?" },
    { title: "Acute Asthma Attack", query: "Patient is wheezing severely and struggling to breathe. How to use inhaler?" },
    { title: "Child Choking", query: "Child is choking on an object and cannot breathe or cough" }
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Bar / Health & Offline Status */}
      <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-50 px-4 py-3 shadow-md">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-red-600 flex items-center justify-center shadow-lg shadow-red-600/30">
              <Heart className="w-6 h-6 text-white animate-pulse" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-xl font-bold tracking-tight text-white">LIFELINE</h1>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-red-950/80 text-red-400 border border-red-800/60">
                  EDGE MEMORY
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Your emergency memory. Even when the network isn't there.
              </p>
            </div>
          </div>

          {/* Edge Connectivity & Sync Pill Bar */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* Network Mode Toggle */}
            <button
              onClick={handleNetworkToggle}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border font-medium transition cursor-pointer ${
                syncStatus?.is_online
                  ? "bg-emerald-950/60 border-emerald-700 text-emerald-300 hover:bg-emerald-900/60"
                  : "bg-amber-950/60 border-amber-700 text-amber-300 hover:bg-amber-900/60"
              }`}
            >
              {syncStatus?.is_online ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
              <span>{syncStatus?.is_online ? "ONLINE" : "OFFLINE EDGE"}</span>
            </button>

            {/* Sync Status Button */}
            <button
              onClick={handleTriggerSync}
              disabled={loading}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-red-400" : ""}`} />
              <span>
                {syncStatus?.pending_sync_count && syncStatus.pending_sync_count > 0
                  ? `Pending Sync (${syncStatus.pending_sync_count})`
                  : "Sync Status: OK"}
              </span>
            </button>

            {/* Qdrant Status Badge */}
            <div className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/60 text-slate-300">
              <Database className="w-3.5 h-3.5 text-blue-400" />
              <span>
                Qdrant Edge{systemHealth ? (systemHealth.dense_model_ready ? " • hybrid" : " • lexical only") : " • unreachable"}
              </span>
            </div>

            {/* Cache Stats */}
            {cacheStats && (
              <div className="hidden md:flex items-center space-x-1 px-2.5 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/60 text-slate-300">
                <Zap className="w-3.5 h-3.5 text-yellow-400" />
                <span>Cache Hit: {cacheStats.hit_rate_pct}%</span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Global Status Toast */}
      {statusMessage && (
        <div className="bg-blue-600 text-white text-sm py-2 px-4 text-center font-medium shadow-md transition-all">
          {statusMessage}
        </div>
      )}

      {needsKey && (
        <div className="bg-amber-950/80 border-b border-amber-800 px-4 py-3">
          <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-2 text-xs text-amber-200">
            <KeyRound className="w-4 h-4" />
            <span className="font-semibold">This node requires an API key.</span>
            <input
              type="password"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder="X-API-Key"
              className="bg-slate-950 border border-amber-700 rounded-lg px-3 py-1.5 text-slate-100"
            />
            <button
              onClick={saveApiKey}
              className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-black font-semibold cursor-pointer"
            >
              Unlock
            </button>
          </div>
        </div>
      )}

      {/* Navigation Tabs */}
      <nav className="bg-slate-900/60 border-b border-slate-800 px-4">
        <div className="max-w-7xl mx-auto flex space-x-1 overflow-x-auto py-2">
          {[
            { id: "assistant", label: "Emergency Assistant", icon: Heart },
            { id: "triage", label: "Rapid Triage", icon: AlertOctagon },
            { id: "vault", label: "Personal Medical Vault", icon: Shield },
            { id: "timeline", label: "Incident Timeline", icon: Clock },
            { id: "guidelines", label: "Trusted Protocols", icon: FileText },
            { id: "diagnostics", label: "Sync & Diagnostics", icon: Activity }
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition cursor-pointer ${
                  isActive
                    ? "bg-red-600 text-white shadow-sm shadow-red-600/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </nav>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto w-full px-4 py-6 flex-1 flex flex-col gap-6">
        {/* ================= TAB 1: EMERGENCY ASSISTANT ================= */}
        {activeTab === "assistant" && (
          <div className="flex flex-col gap-6">
            {/* Quick Emergency Action Cards */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  One-Touch Critical Scenarios
                </span>
                <span className="text-xs text-slate-500">Zero-latency offline recall</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
                {QUICK_SCENARIOS.map((scen, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleQuerySubmit(scen.query)}
                    className="p-3 text-left rounded-xl bg-slate-900 border border-slate-800 hover:border-red-600/60 hover:bg-slate-850 transition group flex flex-col justify-between cursor-pointer"
                  >
                    <span className="text-xs font-semibold text-slate-200 group-hover:text-red-400 transition">
                      {scen.title}
                    </span>
                    <span className="text-[11px] text-slate-500 mt-2 line-clamp-2">{scen.query}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Query Input Box */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleQuerySubmit(queryText);
                }}
                className="flex flex-col sm:flex-row gap-2"
              >
                <div className="relative flex-1">
                  <Search className="w-5 h-5 absolute left-3.5 top-3.5 text-slate-400" />
                  <input
                    type="text"
                    value={queryText}
                    onChange={(e) => setQueryText(e.target.value)}
                    placeholder="Ask emergency protocol (e.g. 'Adult unconscious not breathing', 'Can I give Aspirin?')..."
                    className="w-full bg-slate-950 border border-slate-700/80 rounded-xl pl-11 pr-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
                <div className="flex gap-2">
                  <select
                    value={queryAge}
                    onChange={(e) => setQueryAge(e.target.value as "" | AgeCategory)}
                    title="Patient age group (auto-detected from the question when left on Auto)"
                    className="bg-slate-800 border border-slate-700 rounded-xl px-3 text-xs text-slate-200"
                  >
                    <option value="">Age: auto</option>
                    <option value="adult">Adult</option>
                    <option value="adolescent">Adolescent</option>
                    <option value="child">Child (1-11)</option>
                    <option value="infant">Infant (&lt;1)</option>
                  </select>
                  <label className="flex items-center justify-center px-4 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium cursor-pointer transition">
                    <Camera className="w-4 h-4 mr-1.5 text-slate-400" />
                    <span>Attach Photo</span>
                    <input type="file" accept="image/*" className="hidden" onChange={handleFileUpload} />
                  </label>
                  <button
                    type="submit"
                    disabled={loading || !queryText.trim()}
                    className="px-6 py-3 rounded-xl bg-red-600 hover:bg-red-500 text-white font-semibold text-sm shadow-lg shadow-red-600/30 disabled:opacity-50 transition cursor-pointer flex items-center justify-center space-x-1.5"
                  >
                    {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                    <span>Get Guidance</span>
                  </button>
                </div>
              </form>
            </div>

            {/* Grounded Emergency Response Display */}
            {response && (
              <div className="flex flex-col gap-4">
                {/* Latency & Provenance Badge */}
                <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-slate-400">
                  <div className="flex items-center space-x-2">
                    {response.cache_hit ? (
                      <span className="px-2.5 py-1 rounded-full bg-yellow-950/80 text-yellow-300 border border-yellow-700/60 font-medium flex items-center space-x-1">
                        <Zap className="w-3.5 h-3.5" />
                        <span>Served from Semantic Cache ({response.latency_ms}ms)</span>
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full bg-blue-950/80 text-blue-300 border border-blue-700/60 font-medium flex items-center space-x-1">
                        <Database className="w-3.5 h-3.5" />
                        <span>
                          {response.retrieval_mode === "profile"
                            ? "Personal vault"
                            : response.retrieval_mode === "incident"
                            ? "Incident timeline"
                            : `Qdrant Edge ${response.retrieval_mode === "lexical_only" ? "keyword" : "hybrid"} search`}{" "}
                          ({response.latency_ms}ms)
                        </span>
                      </span>
                    )}
                    <span className="text-slate-500">•</span>
                    <span>Confidence: {response.confidence.toFixed(3)}</span>
                    <span className="text-slate-500">•</span>
                    <span>Patient: {response.age_category}</span>
                  </div>
                  <span className="text-slate-500 font-mono text-[11px]">{response.edge_timestamp}</span>
                </div>

                {/* Primary Response Banner */}
                <div
                  className={`rounded-2xl border p-5 shadow-2xl transition-all ${
                    response.verdict === "CONFLICT"
                      ? "bg-red-950/30 border-red-700 shadow-red-950/40"
                      : response.risk_level === "CRITICAL"
                      ? "bg-slate-900 border-red-600/80"
                      : "bg-slate-900 border-slate-700"
                  }`}
                >
                  {/* Verdict & Risk Header */}
                  <div className="flex flex-wrap items-center justify-between pb-4 mb-4 border-b border-slate-800 gap-2">
                    <div className="flex items-center space-x-2.5">
                      {response.verdict === "CONFLICT" ? (
                        <div className="px-3 py-1 rounded-lg bg-red-600 text-white font-bold text-xs tracking-wider flex items-center space-x-1">
                          <AlertTriangle className="w-4 h-4" />
                          <span>SAFETY CONFLICT - STEPS WITHHELD</span>
                        </div>
                      ) : response.verdict === "INSUFFICIENT" ? (
                        <div className="px-3 py-1 rounded-lg bg-slate-700 text-slate-200 font-bold text-xs tracking-wider">
                          ABSTAIN (SAFETY THRESHOLD)
                        </div>
                      ) : (
                        <div className="px-3 py-1 rounded-lg bg-emerald-600 text-white font-bold text-xs tracking-wider flex items-center space-x-1">
                          <CheckCircle className="w-4 h-4" />
                          <span>VERIFIED PROTOCOL</span>
                        </div>
                      )}

                      <span
                        className={`text-xs px-2.5 py-1 rounded-md font-bold uppercase tracking-wider ${
                          response.risk_level === "CRITICAL"
                            ? "bg-red-950 text-red-400 border border-red-800"
                            : response.risk_level === "HIGH"
                            ? "bg-amber-950 text-amber-400 border border-amber-800"
                            : "bg-blue-950 text-blue-400 border border-blue-800"
                        }`}
                      >
                        {response.risk_level} RISK
                      </span>
                    </div>

                    {response.escalation_needed && (
                      <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-red-600/20 text-red-400 border border-red-600/50 animate-pulse flex items-center space-x-1">
                        <PhoneCall className="w-3.5 h-3.5" />
                        <span>CALL EMERGENCY DISPATCH (911/112)</span>
                      </span>
                    )}
                  </div>

                  {/* Contraindication Alert Box if Conflict */}
                  {response.contraindications_and_warnings.length > 0 && (
                    <div className="mb-5 p-4 rounded-xl bg-red-950/70 border border-red-700 text-red-200">
                      <div className="flex items-center space-x-2 font-bold text-sm mb-2 text-red-300">
                        <AlertTriangle className="w-5 h-5 text-red-400" />
                        <span>Warnings & Contraindications:</span>
                      </div>
                      <ul className="list-disc list-inside space-y-1.5 text-xs text-red-200">
                        {response.contraindications_and_warnings.map((c, i) => (
                          <li key={i} className="font-medium">
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Summary / Protocol Text */}
                  <p className="text-sm sm:text-base text-slate-200 whitespace-pre-line leading-relaxed mb-6 font-medium">
                    {response.answer}
                  </p>

                  {/* Immediate Action Checklist */}
                  {response.immediate_actions.length > 0 && (
                    <div className="bg-slate-950/70 rounded-xl p-4 border border-slate-800">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center space-x-1.5">
                        <Activity className="w-4 h-4 text-emerald-400" />
                        <span>Immediate Action Steps</span>
                      </h4>
                      <div className="space-y-2.5">
                        {response.immediate_actions.map((act, i) => (
                          <div
                            key={i}
                            className="flex items-start space-x-3 p-2.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 transition"
                          >
                            <span className="w-6 h-6 rounded-full bg-emerald-950 border border-emerald-700 text-emerald-400 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                              {i + 1}
                            </span>
                            <span className="text-xs sm:text-sm text-slate-200 leading-snug">{stripNumber(act)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {response.withheld_actions.length > 0 && (
                    <div className="mt-4 p-3 rounded-xl bg-slate-950/70 border border-red-900/70">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-red-400 mb-2 flex items-center space-x-1.5">
                        <EyeOff className="w-4 h-4" />
                        <span>Withheld for this patient - do not do these</span>
                      </h4>
                      <ul className="space-y-1.5 text-xs text-slate-400 line-through decoration-red-700/70">
                        {response.withheld_actions.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {response.related_protocols.length > 0 && (
                    <div className="mt-4 text-xs text-slate-400">
                      Also closely related: {response.related_protocols.join(" • ")}
                    </div>
                  )}

                  {/* Emergency Contacts To Call */}
                  {response.emergency_contacts_to_call.length > 0 && (
                    <div className="mt-4 p-3 rounded-xl bg-blue-950/40 border border-blue-800/60 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center space-x-2 text-xs text-blue-300">
                        <PhoneCall className="w-4 h-4 text-blue-400" />
                        <span className="font-semibold">Patient Emergency Contacts:</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {response.emergency_contacts_to_call.map((ec, idx) => (
                          <a
                            key={idx}
                            href={`tel:${ec.phone}`}
                            className="px-3 py-1 rounded-lg bg-blue-900/60 hover:bg-blue-800 border border-blue-700 text-xs font-medium text-blue-200 transition"
                          >
                            {ec.name} ({ec.relationship}): {ec.phone}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Evidence Provenance / Citations Drawer */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <button
                    onClick={() => setShowCitations(!showCitations)}
                    className="w-full flex items-center justify-between text-xs font-bold uppercase tracking-wider text-slate-400 hover:text-slate-200 transition cursor-pointer"
                  >
                    <div className="flex items-center space-x-2">
                      <Layers className="w-4 h-4 text-blue-400" />
                      <span>Inspect Grounding Evidence ({response.citations.length} Sources)</span>
                    </div>
                    {showCitations ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>

                  {showCitations && (
                    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                      {response.citations.map((c, i) => (
                        <div
                          key={i}
                          className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex flex-col justify-between"
                        >
                          <div>
                            <div className="flex items-center justify-between text-[11px] mb-1.5">
                              <span
                                className={`px-2 py-0.5 rounded font-bold uppercase ${
                                  c.tier === "TRUSTED"
                                    ? "bg-purple-950 text-purple-300 border border-purple-800"
                                    : c.tier === "PERSONAL"
                                    ? "bg-blue-950 text-blue-300 border border-blue-800"
                                    : "bg-amber-950 text-amber-300 border border-amber-800"
                                }`}
                              >
                                {c.tier} MEMORY
                              </span>
                              <span className="text-slate-500 font-mono">v{c.version} | Hash: {c.hash}</span>
                            </div>
                            <h5 className="text-xs font-bold text-slate-200 mb-1">{c.title}</h5>
                            <p className="text-[11px] text-slate-400 line-clamp-3 leading-relaxed">{c.snippet}</p>
                          </div>
                          <div className="mt-2.5 pt-2 border-t border-slate-900 flex justify-between items-center text-[10px] text-slate-500">
                            <span>Score: {c.relevance_score}</span>
                            <span>{c.freshness_timestamp ? new Date(c.freshness_timestamp).toLocaleTimeString() : ""}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ================= TAB 2: RAPID TRIAGE WIZARD ================= */}
        {activeTab === "triage" && (
          <div className="flex flex-col gap-6 max-w-3xl mx-auto w-full">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
              <div className="flex items-center space-x-3 mb-4">
                <AlertOctagon className="w-6 h-6 text-red-500" />
                <div>
                  <h3 className="text-lg font-bold text-white">Rapid On-Scene Triage Assessment</h3>
                  <p className="text-xs text-slate-400">
                    START-style priorities, adjusted for age and the patient's vault
                  </p>
                </div>
              </div>

              <div className="space-y-4 my-6">
                {[
                  {
                    key: "consciousness",
                    label: "Is the patient conscious & responsive?",
                    desc: "Able to speak, blink, or respond to shoulder tap"
                  },
                  {
                    key: "breathing",
                    label: "Is the patient breathing normally?",
                    desc: "Chest rise and fall, regular breath sounds (not gasping)"
                  },
                  {
                    key: "severe_bleeding",
                    label: "Is there massive or spurting arterial bleeding?",
                    desc: "Pulsing blood, soaking through clothing rapidly"
                  },
                  {
                    key: "chest_pain",
                    label: "Is the patient experiencing severe crushing chest pain?",
                    desc: "Pressure radiating to left arm, neck, or shortness of breath"
                  },
                  {
                    key: "allergic_swelling",
                    label: "Is there rapid facial swelling or throat tightness?",
                    desc: "Anaphylaxis signs following exposure to food, drug, or insect sting"
                  }
                ].map((item) => {
                  const val = triageInput[item.key as keyof TriageAssessmentRequest] as boolean;
                  return (
                    <div
                      key={item.key}
                      className="flex items-center justify-between p-3.5 rounded-xl bg-slate-950 border border-slate-800"
                    >
                      <div>
                        <div className="text-sm font-semibold text-slate-200">{item.label}</div>
                        <div className="text-xs text-slate-500">{item.desc}</div>
                      </div>
                      <div className="flex space-x-1 bg-slate-900 p-1 rounded-lg border border-slate-700">
                        <button
                          type="button"
                          onClick={() => setTriageInput({ ...triageInput, [item.key]: true })}
                          className={`px-3 py-1 text-xs font-semibold rounded-md transition cursor-pointer ${
                            val ? "bg-red-600 text-white" : "text-slate-400 hover:text-white"
                          }`}
                        >
                          YES
                        </button>
                        <button
                          type="button"
                          onClick={() => setTriageInput({ ...triageInput, [item.key]: false })}
                          className={`px-3 py-1 text-xs font-semibold rounded-md transition cursor-pointer ${
                            !val ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                          }`}
                        >
                          NO
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
                <label className="text-xs text-slate-400">
                  Patient age group
                  <select
                    value={triageInput.age_category}
                    onChange={(e) => setTriageInput({ ...triageInput, age_category: e.target.value as AgeCategory })}
                    className="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100"
                  >
                    <option value="adult">Adult</option>
                    <option value="adolescent">Adolescent (12-17)</option>
                    <option value="child">Child (1-11)</option>
                    <option value="infant">Infant (under 1)</option>
                  </select>
                </label>
                <label className="text-xs text-slate-400">
                  Burns
                  <select
                    value={triageInput.burns_extent}
                    onChange={(e) =>
                      setTriageInput({ ...triageInput, burns_extent: e.target.value as "none" | "minor" | "major" })
                    }
                    className="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100"
                  >
                    <option value="none">None</option>
                    <option value="minor">Minor (smaller than palm)</option>
                    <option value="major">Major / face, hands, chemical</option>
                  </select>
                </label>
                <label className="text-xs text-slate-400">
                  Patient
                  <select
                    value={triageInput.patient_is_profile_owner ? "owner" : "other"}
                    onChange={(e) => setTriageInput({ ...triageInput, patient_is_profile_owner: e.target.value === "owner" })}
                    className="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-100"
                  >
                    <option value="owner">Profile owner (use vault)</option>
                    <option value="other">Someone else</option>
                  </select>
                </label>
              </div>

              <button
                onClick={handleTriageSubmit}
                disabled={loading}
                className="w-full py-3.5 rounded-xl bg-red-600 hover:bg-red-500 text-white font-bold text-sm shadow-lg shadow-red-600/30 transition cursor-pointer"
              >
                Compute Triage Category & Action
              </button>
            </div>

            {/* Triage Output */}
            {triageResult && (
              <div
                className={`p-6 rounded-2xl border shadow-2xl ${
                  triageResult.triage_color === "RED"
                    ? "bg-red-950/40 border-red-700"
                    : triageResult.triage_color === "YELLOW"
                    ? "bg-amber-950/40 border-amber-700"
                    : "bg-emerald-950/40 border-emerald-700"
                }`}
              >
                <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
                  <div className="flex items-center space-x-3">
                    <span
                      className={`text-sm px-3 py-1 rounded-lg font-black tracking-widest ${
                        triageResult.triage_color === "RED"
                          ? "bg-red-600 text-white"
                          : triageResult.triage_color === "YELLOW"
                          ? "bg-amber-500 text-black"
                          : "bg-emerald-600 text-white"
                      }`}
                    >
                      TRIAGE: {triageResult.triage_color} (Priority {triageResult.estimated_priority_score})
                    </span>
                    <span className="text-xs font-semibold text-slate-300">{triageResult.risk_level} RISK</span>
                  </div>
                  {triageResult.call_emergency_services_now && (
                    <span className="text-xs font-bold text-red-400 animate-pulse">CALL 911 / 112 NOW</span>
                  )}
                </div>

                <div className="text-base font-bold text-white mb-4">{triageResult.immediate_first_action}</div>

                <div className="space-y-2 mb-4">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Action Protocol:</span>
                  {triageResult.action_checklist.map((c, i) => (
                    <div key={i} className="text-xs text-slate-200 flex items-start space-x-2">
                      <span className="text-red-400 font-bold">•</span>
                      <span>{c}</span>
                    </div>
                  ))}
                </div>

                {triageResult.contraindications.length > 0 && (
                  <div className="p-3 rounded-lg bg-red-950/60 border border-red-800 text-xs text-red-300">
                    <span className="font-bold">Caution: </span>
                    {triageResult.contraindications.join("; ")}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ================= TAB 3: PERSONAL MEDICAL VAULT ================= */}
        {activeTab === "vault" && profile && editedProfile && (
          <div className="flex flex-col gap-6 max-w-4xl mx-auto w-full">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
              <div className="flex flex-wrap items-center justify-between pb-4 mb-6 border-b border-slate-800 gap-3">
                <div className="flex items-center space-x-3">
                  <div className="w-12 h-12 rounded-xl bg-blue-600/20 border border-blue-500/40 text-blue-400 flex items-center justify-center font-black text-xl">
                    {profile.blood_group}
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white">{profile.full_name}</h3>
                    <p className="text-xs text-slate-400">
                      Personal Edge Vault • Version {profile.version} • Last updated:{" "}
                      {new Date(profile.last_updated).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  {!isEditingProfile ? (
                    <button
                      onClick={() => setIsEditingProfile(true)}
                      className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 transition cursor-pointer flex items-center space-x-1.5"
                    >
                      <User className="w-3.5 h-3.5 text-blue-400" />
                      <span>Edit Vault Profile</span>
                    </button>
                  ) : (
                    <div className="flex space-x-2">
                      <button
                        onClick={() => {
                          setEditedProfile(profile);
                          setIsEditingProfile(false);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-300 hover:bg-slate-700 cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveProfile}
                        disabled={loading}
                        className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition cursor-pointer flex items-center space-x-1.5"
                      >
                        <Save className="w-3.5 h-3.5" />
                        <span>Save & Re-Index</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* View / Edit Mode */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Allergies */}
                <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold text-red-400 uppercase tracking-wider flex items-center space-x-1">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      <span>Severe Allergies (Contraindications)</span>
                    </span>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {(isEditingProfile ? editedProfile.allergies : profile.allergies).map((a, i) => (
                      <span
                        key={i}
                        className="px-2.5 py-1 rounded-lg bg-red-950/80 border border-red-800 text-red-300 text-xs font-medium flex items-center space-x-1.5"
                      >
                        <span>{a}</span>
                        {isEditingProfile && (
                          <button
                            onClick={() => removeListItem("allergies", i)}
                            className="text-red-400 hover:text-white cursor-pointer"
                          >
                            ×
                          </button>
                        )}
                      </span>
                    ))}
                  </div>

                  {isEditingProfile && (
                    <div className="mt-3 flex gap-2">
                      <input
                        type="text"
                        value={newItem.allergies}
                        onChange={(e) => setNewItem({ ...newItem, allergies: e.target.value })}
                        placeholder="Add allergy (e.g. Latex)..."
                        className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={() => addListItem("allergies")}
                        className="px-3 py-1.5 bg-red-600 rounded-lg text-xs font-semibold text-white hover:bg-red-500 cursor-pointer"
                      >
                        Add
                      </button>
                    </div>
                  )}
                </div>

                {/* Chronic Conditions */}
                <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                  <span className="text-xs font-bold text-amber-400 uppercase tracking-wider block mb-3">
                    Chronic Medical Conditions
                  </span>
                  <div className="space-y-1.5">
                    {(isEditingProfile ? editedProfile.chronic_conditions : profile.chronic_conditions).map((c, i) => (
                      <div key={i} className="text-xs text-slate-300 flex items-center space-x-2">
                        <span className="text-amber-400">•</span>
                        <span className="flex-1">{c}</span>
                        {isEditingProfile && (
                          <button
                            onClick={() => removeListItem("chronic_conditions", i)}
                            className="text-slate-500 hover:text-white cursor-pointer"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  {isEditingProfile && (
                    <div className="mt-3 flex gap-2">
                      <input
                        type="text"
                        value={newItem.chronic_conditions}
                        onChange={(e) => setNewItem({ ...newItem, chronic_conditions: e.target.value })}
                        placeholder="Add condition (e.g. Epilepsy)..."
                        className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={() => addListItem("chronic_conditions")}
                        className="px-3 py-1.5 bg-slate-700 rounded-lg text-xs font-semibold text-white hover:bg-slate-600 cursor-pointer"
                      >
                        Add
                      </button>
                    </div>
                  )}
                </div>

                {/* Current Medications */}
                <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                  <span className="text-xs font-bold text-blue-400 uppercase tracking-wider block mb-3">
                    Active Medications & Inhalers
                  </span>
                  <div className="space-y-1.5">
                    {(isEditingProfile ? editedProfile.current_medications : profile.current_medications).map((c, i) => (
                      <div key={i} className="text-xs text-slate-300 flex items-center space-x-2">
                        <span className="text-blue-400">•</span>
                        <span className="flex-1">{c}</span>
                        {isEditingProfile && (
                          <button
                            onClick={() => removeListItem("current_medications", i)}
                            className="text-slate-500 hover:text-white cursor-pointer"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  {isEditingProfile && (
                    <div className="mt-3 flex gap-2">
                      <input
                        type="text"
                        value={newItem.current_medications}
                        onChange={(e) => setNewItem({ ...newItem, current_medications: e.target.value })}
                        placeholder="Add medication (e.g. Warfarin 5mg)..."
                        className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={() => addListItem("current_medications")}
                        className="px-3 py-1.5 bg-slate-700 rounded-lg text-xs font-semibold text-white hover:bg-slate-600 cursor-pointer"
                      >
                        Add
                      </button>
                    </div>
                  )}
                </div>

                {/* Emergency Contacts */}
                <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                  <span className="text-xs font-bold text-emerald-400 uppercase tracking-wider block mb-3">
                    In Case of Emergency (ICE) Contacts
                  </span>
                  <div className="space-y-2">
                    {profile.emergency_contacts.map((ec, i) => (
                      <div key={i} className="flex justify-between items-center text-xs text-slate-300">
                        <div>
                          <span className="font-semibold text-slate-100">{ec.name}</span>{" "}
                          <span className="text-slate-500">({ec.relationship})</span>
                        </div>
                        <a href={`tel:${ec.phone}`} className="text-blue-400 hover:underline font-mono">
                          {ec.phone}
                        </a>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Special Instructions & Notes */}
              <div className="mt-6 p-4 rounded-xl bg-slate-950 border border-slate-800">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Critical First-Responder Instructions:
                </span>
                <p className="text-xs text-slate-200 leading-relaxed font-mono bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                  {profile.ice_instructions || "No special instructions provided."}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ================= TAB 4: INCIDENT TIMELINE ================= */}
        {activeTab === "timeline" && (
          <div className="flex flex-col gap-6 max-w-4xl mx-auto w-full">
            {/* New Observation Logger */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
              <h3 className="text-base font-bold text-white mb-2 flex items-center space-x-2">
                <Clock className="w-5 h-5 text-red-500" />
                <span>Log Active Incident Observation (Edge Temporal Memory)</span>
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Record real-time on-scene observations, vital signs, and medications administered. Automatically indexed in Qdrant Edge.
              </p>

              <div className="mb-4">
                <label className="text-xs text-slate-400 block mb-1">Incident ID</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={incidentId}
                    onChange={(e) => setIncidentId(e.target.value)}
                    className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono"
                  />
                  <button
                    onClick={() => refreshAll(incidentId)}
                    className="px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:bg-slate-700 cursor-pointer"
                  >
                    Load
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Heart Rate (bpm)</label>
                  <input
                    type="text"
                    value={newPulse}
                    onChange={(e) => setNewPulse(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Oxygen Saturation (SpO2 %)</label>
                  <input
                    type="text"
                    value={newSpO2}
                    onChange={(e) => setNewSpO2(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100"
                  />
                </div>
              </div>

              <div className="space-y-3 mb-4">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Observed Symptoms (comma separated)</label>
                  <input
                    type="text"
                    value={newObsSymptoms}
                    onChange={(e) => setNewObsSymptoms(e.target.value)}
                    placeholder="e.g. Unresponsive, shallow breathing, pale skin..."
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Actions Taken On-Scene (comma separated)</label>
                  <input
                    type="text"
                    value={newObsActions}
                    onChange={(e) => setNewObsActions(e.target.value)}
                    placeholder="e.g. Began CPR compressions, Albuterol 2 puffs given..."
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100"
                  />
                </div>
              </div>

              <button
                onClick={handleLogObservation}
                disabled={loading || (!newObsSymptoms && !newObsActions)}
                className="w-full py-2.5 bg-red-600 hover:bg-red-500 rounded-xl text-white font-semibold text-xs shadow-md shadow-red-600/30 transition cursor-pointer"
              >
                Save to Incident Memory Tier
              </button>
            </div>

            {/* Timeline Stream */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                Chronological Incident Stream ({incidents.length} Records)
              </h4>
              {incidents.map((obs, i) => (
                <div key={obs.id || i} className="p-4 rounded-xl bg-slate-900 border border-slate-800">
                  <div className="flex items-center justify-between text-xs mb-2">
                    <span className="font-bold text-slate-200">
                      Observation #{obs.version}
                      {obs.origin_node && <span className="ml-2 text-slate-500 font-normal">from {obs.origin_node}</span>}
                    </span>
                    <span className="text-slate-500 font-mono">{new Date(obs.timestamp).toLocaleTimeString()}</span>
                  </div>
                  {obs.vital_signs && Object.keys(obs.vital_signs).length > 0 && (
                    <div className="flex gap-4 text-xs font-mono text-emerald-400 mb-2">
                      {Object.entries(obs.vital_signs).map(([k, v]) => (
                        <span key={k}>
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                  {obs.observed_symptoms.length > 0 && (
                    <div className="text-xs text-slate-300 mb-1">
                      <span className="text-slate-500 font-semibold">Symptoms: </span>
                      {obs.observed_symptoms.join(", ")}
                    </div>
                  )}
                  {obs.actions_taken.length > 0 && (
                    <div className="text-xs text-slate-300">
                      <span className="text-slate-500 font-semibold">Actions: </span>
                      {obs.actions_taken.join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ================= TAB 5: TRUSTED GUIDELINES ================= */}
        {activeTab === "guidelines" && (
          <div className="flex flex-col gap-6">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-bold text-white">Clinical Trusted Memory Guidelines</h3>
                <p className="text-xs text-slate-400">
                  Certified first-aid protocols, stored offline in Qdrant Edge local vectors
                </p>
              </div>
              <input
                type="text"
                value={guidelineSearch}
                onChange={(e) => setGuidelineSearch(e.target.value)}
                placeholder="Search protocols (CPR, burns, allergy)..."
                className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-red-500 w-full sm:w-64"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {guidelines
                .filter(
                  (g) =>
                    !guidelineSearch ||
                    g.title.toLowerCase().includes(guidelineSearch.toLowerCase()) ||
                    g.content.toLowerCase().includes(guidelineSearch.toLowerCase())
                )
                .map((g) => (
                  <div
                    key={g.id}
                    className="p-5 rounded-2xl bg-slate-900 border border-slate-800 flex flex-col justify-between hover:border-slate-700 transition"
                  >
                    <div>
                      <div className="flex items-center justify-between text-[11px] mb-2">
                        <span className="px-2 py-0.5 rounded font-bold uppercase bg-purple-950 text-purple-300 border border-purple-800">
                          {g.risk_level}
                        </span>
                        <span className="text-slate-500 font-mono">v{g.version}</span>
                      </div>
                      <h4 className="text-sm font-bold text-white mb-2">{g.title}</h4>
                      <p className="text-xs text-slate-300 line-clamp-4 leading-relaxed mb-4">{g.content}</p>

                      {g.contraindications && g.contraindications.length > 0 && (
                        <div className="p-2.5 rounded-lg bg-red-950/40 border border-red-800/60 text-[11px] text-red-300">
                          <span className="font-bold">Contraindications: </span>
                          {g.contraindications.join(" ")}
                        </div>
                      )}
                    </div>
                    <div className="mt-4 pt-3 border-t border-slate-800 flex justify-between items-center text-[10px] text-slate-500">
                      <span>Source: {g.author}</span>
                      <span>Hash: {g.hash}</span>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* ================= TAB 6: DIAGNOSTICS & SYNC ================= */}
        {activeTab === "diagnostics" && (
          <div className="flex flex-col gap-6 max-w-4xl mx-auto w-full">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Qdrant Edge Status */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <h4 className="text-sm font-bold text-white mb-3 flex items-center space-x-2">
                  <Database className="w-4 h-4 text-blue-400" />
                  <span>Qdrant Edge Vector Storage</span>
                </h4>
                {systemHealth && (
                  <div className="space-y-2 text-xs font-mono text-slate-300">
                    <div>Mode: {systemHealth.mode}</div>
                    <div>Storage Engine: {systemHealth.storage_mode}</div>
                    <div>Dense model: {systemHealth.dense_model_ready ? "ready" : "unavailable (keyword-only mode)"}</div>
                    <div>Edge Node ID: {systemHealth.edge_node_id}</div>
                    <div>API key required: {systemHealth.auth_required ? "yes" : "no"}</div>
                    <div className="pt-2 border-t border-slate-800">
                      <div className="font-bold text-slate-400 mb-1">Shards:</div>
                      {Object.entries(systemHealth.collections || {}).map(([c, info]) =>
                        typeof info === "string" ? null : (
                          <div key={c} className="text-slate-400">
                            • {c}: {info.documents} documents / {info.points_count} points
                          </div>
                        )
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Semantic Cache Stats */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-bold text-white flex items-center space-x-2">
                    <Zap className="w-4 h-4 text-yellow-400" />
                    <span>Evidence-State Semantic Cache</span>
                  </h4>
                  <button
                    onClick={async () => {
                      await clearCache();
                      const c = await getCacheStats();
                      setCacheStats(c);
                      showNotice("Semantic Cache purged.");
                    }}
                    className="text-[11px] px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 cursor-pointer"
                  >
                    Purge Cache
                  </button>
                </div>
                {cacheStats && (
                  <div className="space-y-1.5 text-xs text-slate-300">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Hit Rate:</span>
                      <span className="font-bold text-emerald-400">{cacheStats.hit_rate_pct}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Total Queries:</span>
                      <span>{cacheStats.total_queries}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Cache Hits:</span>
                      <span>{cacheStats.hits}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">State Invalidations:</span>
                      <span className="text-amber-400 font-bold">{cacheStats.state_invalidations}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Blocked by safety terms:</span>
                      <span>{cacheStats.salient_mismatches}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Active Entries:</span>
                      <span>{cacheStats.active_cached_entries}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Sync & Access */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
              <h4 className="text-sm font-bold text-white mb-3 flex items-center space-x-2">
                <RefreshCw className="w-4 h-4 text-blue-400" />
                <span>Replication & Access</span>
              </h4>
              {syncStatus && (
                <div className="space-y-1 text-xs font-mono text-slate-300 mb-4">
                  <div>Upstream hub: {syncStatus.remote_server_url || "not configured (standalone node)"}</div>
                  <div>
                    Pending changes: {syncStatus.pending_sync_count} / log size {syncStatus.total_mutation_log_count}
                  </div>
                  <div>
                    Last synced: {syncStatus.last_synced_at ? new Date(syncStatus.last_synced_at).toLocaleString() : "never"}
                  </div>
                  {syncStatus.last_error && <div className="text-amber-400">Last error: {syncStatus.last_error}</div>}
                </div>
              )}
              <div className="flex flex-wrap gap-2 items-center text-xs">
                <KeyRound className="w-4 h-4 text-slate-400" />
                <input
                  type="password"
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder="API key for this node (stored in this browser)"
                  className="flex-1 min-w-[12rem] bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-100"
                />
                <button
                  onClick={saveApiKey}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700 cursor-pointer"
                >
                  Save key
                </button>
              </div>
            </div>

            {/* Media Integration Status */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
              <h4 className="text-sm font-bold text-white mb-2 flex items-center space-x-2">
                <Camera className="w-4 h-4 text-emerald-400" />
                <span>Media Integration (Local Storage & Cloudinary Sync)</span>
              </h4>
              <p className="text-xs text-slate-400 mb-4">
                Images of wounds, prescription labels, or medical documents are preserved locally on edge disk and synced to Cloudinary when network connectivity is restored.
              </p>
              <input
                type="file"
                accept="image/*,video/mp4,video/quicktime,audio/*,application/pdf"
                onChange={handleFileUpload}
                className="text-xs text-slate-400"
              />
              {mediaUploadStatus && (
                <div className="mt-3 p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-300 font-mono">
                  <div>Status: {mediaUploadStatus.status}</div>
                  <div>
                    Stored file:{" "}
                    <a
                      href={mediaUrl(mediaUploadStatus.local_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-400 underline"
                    >
                      {mediaUploadStatus.filename}
                    </a>{" "}
                    ({Math.round(mediaUploadStatus.size_bytes / 1024)} KB)
                  </div>
                  {mediaUploadStatus.remote_url && <div>Cloudinary: {mediaUploadStatus.remote_url}</div>}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-slate-900 border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-500">
        Lifeline v2.0 • Risk-aware emergency memory on Qdrant Edge • Not a substitute for emergency services
      </footer>
    </div>
  );
}
