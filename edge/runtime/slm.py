import logging
import httpx
import json
from typing import List, Dict, Any, Optional
from models.enums import ValidationVerdict, RiskLevel, QueryIntent
from models.schemas import GroundedResponse, SourceCitation, PersonalProfile

logger = logging.getLogger("lifeline.slm")

class AdaptiveEdgeSLM:
    """
    Adaptive SLM inference engine:
    1. Supports local Ollama or lightweight LLM endpoint if active.
    2. Zero-dependency deterministic clinical grounding engine that runs offline with 0ms latency.
    3. Strictly enforces grounded answers, immediate action extraction, and contraindication alerts.
    """
    def __init__(self, ollama_url: str = "http://localhost:11434", model_name: str = "llama3.2:1b"):
        self.ollama_url = ollama_url
        self.model_name = model_name

    def generate(
        self,
        query: str,
        risk_level: RiskLevel,
        intent: QueryIntent,
        verdict: ValidationVerdict,
        citations: List[SourceCitation],
        contraindications: List[str],
        personal_profile: Optional[PersonalProfile] = None,
        prefer_ollama: bool = False
    ) -> GroundedResponse:
        
        # 1. Handle INSUFFICIENT Verdict (Abstain)
        if verdict == ValidationVerdict.INSUFFICIENT:
            return self._build_abstain_response(query, risk_level, intent, citations)

        # 2. Handle CONFLICT Verdict (Escalate)
        if verdict == ValidationVerdict.CONFLICT:
            return self._build_conflict_response(query, risk_level, intent, citations, contraindications, personal_profile)

        # 3. Handle SUFFICIENT Verdict
        # Attempt Ollama if requested/available, else clinical heuristic synthesizer
        if prefer_ollama:
            ollama_resp = self._try_ollama_generate(query, citations, contraindications, personal_profile)
            if ollama_resp:
                return ollama_resp

        return self._build_grounded_clinical_response(query, risk_level, intent, citations, contraindications, personal_profile)

    def _build_abstain_response(
        self,
        query: str,
        risk_level: RiskLevel,
        intent: QueryIntent,
        citations: List[SourceCitation]
    ) -> GroundedResponse:
        answer = (
            "SAFETY ABSTAIN: The available local emergency memory does not contain sufficient, "
            "clinically-verified evidence to answer this specific query with certainty. "
            "To prevent medical harm or hallucination, this system refuses to guess."
        )
        immediate_actions = [
            "1. Call Emergency Medical Services immediately (911 in US, 112 in EU/India).",
            "2. Ensure the scene is safe for you and the patient.",
            "3. Assess ABCs: Airway (clear?), Breathing (normal?), Circulation (pulse/severe bleeding?).",
            "4. If patient is unresponsive but breathing normally, place them in the Recovery Position on their side."
        ]
        return GroundedResponse(
            query=query,
            risk_level=risk_level,
            intent=intent,
            verdict=ValidationVerdict.INSUFFICIENT,
            answer=answer,
            immediate_actions=immediate_actions,
            contraindications_and_warnings=["Do not administer medications or invasive procedures without verified clinical guidance."],
            citations=citations,
            escalation_needed=True,
            offline_mode=True
        )

    def _build_conflict_response(
        self,
        query: str,
        risk_level: RiskLevel,
        intent: QueryIntent,
        citations: List[SourceCitation],
        contraindications: List[str],
        personal_profile: Optional[PersonalProfile]
    ) -> GroundedResponse:
        conflict_reasons = "\n".join(f"• {c}" for c in contraindications)
        answer = (
            "CRITICAL SAFETY WARNING: Active Contraindication / Clinical Conflict Detected!\n\n"
            f"The requested action conflicts with recorded patient profile or conflicting medical guidance:\n{conflict_reasons}\n\n"
            "DO NOT administer the contraindicated medication or procedure."
        )
        immediate_actions = [
            "1. STOP: Do not administer contraindicated substances.",
            "2. Keep the patient calm, seated or lying down in a comfortable position.",
            "3. Monitor airway, breathing, and consciousness continuously.",
            "4. Contact emergency dispatch (911 / 112) and inform them of the patient's allergy/condition.",
            "5. Prepare patient's emergency profile for paramedics."
        ]
        emergency_contacts = []
        if personal_profile and personal_profile.emergency_contacts:
            for ec in personal_profile.emergency_contacts:
                emergency_contacts.append({
                    "name": ec.name,
                    "relationship": ec.relationship,
                    "phone": ec.phone
                })

        return GroundedResponse(
            query=query,
            risk_level=RiskLevel.CRITICAL,  # escalate risk on conflict
            intent=intent,
            verdict=ValidationVerdict.CONFLICT,
            answer=answer,
            immediate_actions=immediate_actions,
            contraindications_and_warnings=contraindications,
            citations=citations,
            escalation_needed=True,
            emergency_contacts_to_call=emergency_contacts,
            offline_mode=True
        )

    def _build_grounded_clinical_response(
        self,
        query: str,
        risk_level: RiskLevel,
        intent: QueryIntent,
        citations: List[SourceCitation],
        contraindications: List[str],
        personal_profile: Optional[PersonalProfile]
    ) -> GroundedResponse:
        top_citation = citations[0] if citations else None
        
        # Extract actions from snippet and content
        actions: List[str] = []
        if top_citation:
            # Parse lines that look like steps or bullet points
            lines = top_citation.snippet.split("\n")
            for line in lines:
                cleaned = line.strip().strip("-•*").strip()
                if cleaned and len(cleaned) > 5 and not cleaned.lower().startswith("contraindication"):
                    actions.append(cleaned)

        if not actions and top_citation:
            actions = [top_citation.snippet]

        # Add primary emergency contacts if available
        emergency_contacts = []
        if personal_profile and personal_profile.emergency_contacts:
            for ec in personal_profile.emergency_contacts:
                emergency_contacts.append({
                    "name": ec.name,
                    "relationship": ec.relationship,
                    "phone": ec.phone
                })

        summary_header = f"EMERGENCY PROTOCOL: {top_citation.title if top_citation else 'Standard Procedure'}"
        answer_text = (
            f"{summary_header}\n\n"
            f"Based on verified edge evidence (Version {top_citation.version if top_citation else 1}), "
            "follow these prioritized life-saving actions immediately:"
        )

        return GroundedResponse(
            query=query,
            risk_level=risk_level,
            intent=intent,
            verdict=ValidationVerdict.SUFFICIENT,
            answer=answer_text,
            immediate_actions=actions[:6],
            contraindications_and_warnings=contraindications,
            citations=citations,
            escalation_needed=risk_level == RiskLevel.CRITICAL,
            emergency_contacts_to_call=emergency_contacts,
            offline_mode=True
        )

    def _try_ollama_generate(
        self,
        query: str,
        citations: List[SourceCitation],
        contraindications: List[str],
        personal_profile: Optional[PersonalProfile]
    ) -> Optional[GroundedResponse]:
        try:
            evidence_context = "\n---\n".join(
                f"[{c.tier.value}] {c.title} (v{c.version}):\n{c.snippet}" for c in citations
            )
            prompt = (
                f"You are Lifeline, an offline edge emergency medical assistant.\n"
                f"Evidence:\n{evidence_context}\n"
                f"Contraindications: {'; '.join(contraindications)}\n"
                f"User Emergency Query: {query}\n"
                f"Respond with concise, numbered life-saving steps. Strictly ground your answer in the evidence."
            )
            with httpx.Client(timeout=2.0) as client:
                res = client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.model_name, "prompt": prompt, "stream": False}
                )
                if res.status_code == 200:
                    text = res.json().get("response", "")
                    if text:
                        return GroundedResponse(
                            query=query,
                            risk_level=RiskLevel.MEDIUM,
                            intent=QueryIntent.FIRST_AID_INSTRUCTION,
                            verdict=ValidationVerdict.SUFFICIENT,
                            answer=text,
                            immediate_actions=[line.strip() for line in text.split("\n") if line.strip()][:6],
                            contraindications_and_warnings=contraindications,
                            citations=citations,
                            offline_mode=True
                        )
        except Exception:
            pass
        return None

_global_slm: Optional[AdaptiveEdgeSLM] = None

def get_slm() -> AdaptiveEdgeSLM:
    global _global_slm
    if _global_slm is None:
        _global_slm = AdaptiveEdgeSLM()
    return _global_slm
