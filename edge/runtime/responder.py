import logging
from typing import List, Optional, Dict
import httpx
from models.enums import ValidationVerdict, RiskLevel, QueryIntent, MemoryTier
from models.schemas import (GroundedResponse, SourceCitation, PersonalProfile, IncidentObservation, EvidenceItem)
from edge.config import get_settings
from edge.qdrant.client import split_steps
from edge.runtime.safety import SafetyContext, screen_steps, query_conflicts
from edge.runtime.validator import GateResult

logger = logging.getLogger("lifeline.responder")

EMS_LINE = "Call emergency services now (911 in the US, 112 in the EU/India) and keep the line open."

ABSTAIN_ACTIONS = [
    EMS_LINE,
    "Make sure the scene is safe for you and the patient.",
    "Check Airway (clear?), Breathing (normal?) and Circulation (pulse, severe bleeding?).",
    "If unresponsive but breathing normally, place them on their side in the recovery position.",
    "If unresponsive and not breathing normally, start CPR: push hard and fast in the centre of the chest.",
]


def _numbered(lines: List[str]) -> List[str]:
    return [f"{i}. {line}" for i, line in enumerate(lines, start=1)]


def _contacts(profile: Optional[PersonalProfile]) -> List[Dict[str, str]]:
    if not profile:
        return []
    return [{"name": c.name, "relationship": c.relationship, "phone": c.phone}
            for c in sorted(profile.emergency_contacts, key=lambda c: c.priority)]


def citation_for(item: EvidenceItem, score: float, found: Optional[List[str]] = None) -> SourceCitation:
    snippet = item.content if len(item.content) <= 240 else item.content[:240].rsplit(" ", 1)[0] + " …"
    return SourceCitation(
        evidence_id=item.id, tier=item.tier, title=item.title, snippet=snippet, version=item.version,
        hash=item.hash, relevance_score=round(score, 4), author=item.author,
        freshness_timestamp=item.updated_at or item.created_at, contraindications_found=found or [],
    )


class GroundedResponseBuilder:
    """
    Turns validated evidence into a response. Every instruction shown to the user is
    a verbatim step from a trusted protocol (after patient-specific safety screening)
    or a fixed safety fallback - nothing is generated.
    """

    def __init__(self):
        self.settings = get_settings()

    # ------------------------------------------------------------- protocol answers
    def from_protocol(self, query: str, risk: RiskLevel, intent: QueryIntent, gate: GateResult,
                      ctx: SafetyContext, profile: Optional[PersonalProfile],
                      profile_applied: bool) -> GroundedResponse:
        item: EvidenceItem = gate.primary["item"]
        screening = screen_steps(split_steps(item.content), ctx)
        asked_conflicts = query_conflicts(query, ctx)
        conflict = bool(screening.withheld or asked_conflicts)

        warnings = asked_conflicts + screening.warnings + list(item.contraindications) + ctx.cautions
        if not profile_applied and profile is not None:
            warnings.append("Personal profile allergies were NOT applied: the patient described appears to be "
                            "someone other than the profile owner. Ask about their allergies before giving any medicine.")

        source = f"{item.author}, v{item.version}"
        if conflict:
            answer = (f"SAFETY CONFLICT - {item.title}\n"
                      f"Parts of this protocol are unsafe for this patient and have been removed. "
                      f"Follow only the steps below and read the warnings; tell emergency services why "
                      f"steps were withheld. (Source: {source})")
        else:
            answer = f"{item.title}\nFollow these steps in order. (Source: {source})"
            llm = self._llm_summary(query, item, screening.safe_steps) if risk != RiskLevel.CRITICAL else None
            if llm:
                answer += f"\n\nSummary: {llm}"

        citations = [citation_for(item, gate.confidence, screening.warnings + asked_conflicts)]
        citations += [citation_for(c["item"], c["confidence"]) for c in gate.related]
        if profile_applied and profile is not None and (screening.withheld or asked_conflicts):
            citations.append(SourceCitation(
                evidence_id=f"profile-{profile.user_id}", tier=MemoryTier.PERSONAL,
                title=f"Emergency Profile - {profile.full_name}",
                snippet=f"Allergies: {', '.join(profile.allergies) or 'none'}; Conditions: "
                        f"{', '.join(profile.chronic_conditions) or 'none'}",
                version=profile.version, hash=f"v{profile.version}", relevance_score=1.0,
                author="user_personal_vault", freshness_timestamp=profile.last_updated))

        return GroundedResponse(
            query=query,
            risk_level=RiskLevel.CRITICAL if conflict and risk != RiskLevel.CRITICAL else risk,
            intent=intent,
            verdict=ValidationVerdict.CONFLICT if conflict else ValidationVerdict.SUFFICIENT,
            answer=answer,
            immediate_actions=_numbered(screening.safe_steps),
            contraindications_and_warnings=list(dict.fromkeys(warnings)),
            withheld_actions=screening.withheld,
            citations=citations,
            related_protocols=[c["item"].title for c in gate.related],
            escalation_needed=conflict or risk in (RiskLevel.CRITICAL, RiskLevel.HIGH),
            emergency_contacts_to_call=_contacts(profile) if profile_applied else [],
            confidence=gate.confidence,
            age_category=ctx.age_category,
            retrieval_mode=gate.mode,
        )

    def abstain(self, query: str, risk: RiskLevel, intent: QueryIntent, gate: GateResult,
                ctx: SafetyContext, profile: Optional[PersonalProfile], profile_applied: bool) -> GroundedResponse:
        warnings = query_conflicts(query, ctx)
        warnings.append("No verified protocol in local memory clearly matches this situation. Do not give "
                        "medicines or attempt procedures you are not trained for.")
        return GroundedResponse(
            query=query, risk_level=risk, intent=intent, verdict=ValidationVerdict.INSUFFICIENT,
            answer=("SAFETY ABSTAIN: Lifeline has no verified protocol that clearly matches this question, so it "
                    "will not guess. If this is an emergency, call emergency services and follow the basic "
                    "life-support checks below."),
            immediate_actions=_numbered(ABSTAIN_ACTIONS),
            contraindications_and_warnings=warnings,
            escalation_needed=True,
            emergency_contacts_to_call=_contacts(profile) if profile_applied else [],
            confidence=gate.confidence, age_category=ctx.age_category, retrieval_mode=gate.mode,
        )

    # ------------------------------------------------------------- memory answers
    def from_profile(self, query: str, risk: RiskLevel, intent: QueryIntent,
                     profile: PersonalProfile) -> GroundedResponse:
        lines = [
            f"Blood group: {profile.blood_group}",
            f"Allergies: {', '.join(profile.allergies) or 'none recorded'}",
            f"Current medications: {', '.join(profile.current_medications) or 'none recorded'}",
            f"Chronic conditions: {', '.join(profile.chronic_conditions) or 'none recorded'}",
        ]
        if profile.ice_instructions:
            lines.append(f"ICE instructions: {profile.ice_instructions}")
        contacts = _contacts(profile)
        for c in contacts:
            lines.append(f"Contact: {c['name']} ({c['relationship']}) {c['phone']}")
        cit = SourceCitation(
            evidence_id=f"profile-{profile.user_id}", tier=MemoryTier.PERSONAL,
            title=f"Emergency Profile - {profile.full_name}", snippet="; ".join(lines[:4]),
            version=profile.version, hash=f"v{profile.version}", relevance_score=1.0,
            author="user_personal_vault", freshness_timestamp=profile.last_updated)
        return GroundedResponse(
            query=query, risk_level=risk, intent=intent, verdict=ValidationVerdict.SUFFICIENT,
            answer=f"Emergency profile for {profile.full_name} (version {profile.version}).",
            immediate_actions=lines, citations=[cit], emergency_contacts_to_call=contacts,
            confidence=1.0, retrieval_mode="profile",
        )

    def from_incident(self, query: str, risk: RiskLevel, intent: QueryIntent, incident_id: str,
                      observations: List[IncidentObservation]) -> GroundedResponse:
        if not observations:
            return GroundedResponse(
                query=query, risk_level=risk, intent=intent, verdict=ValidationVerdict.INSUFFICIENT,
                answer=f"No observations have been logged for incident '{incident_id}' yet.",
                retrieval_mode="incident")
        lines = []
        for o in observations[:10]:
            vitals = ", ".join(f"{k}: {v}" for k, v in o.vital_signs.items()) or "no vitals"
            parts = [f"[{o.timestamp[11:19] or o.timestamp}] {o.severity.value}: {vitals}"]
            if o.observed_symptoms:
                parts.append("symptoms: " + ", ".join(o.observed_symptoms))
            if o.actions_taken:
                parts.append("actions: " + ", ".join(o.actions_taken))
            lines.append("; ".join(parts))
        return GroundedResponse(
            query=query, risk_level=risk, intent=intent, verdict=ValidationVerdict.SUFFICIENT,
            answer=f"Incident '{incident_id}': {len(observations)} observation(s), newest first.",
            immediate_actions=lines, confidence=1.0, retrieval_mode="incident")

    # ------------------------------------------------------------- optional LLM
    def _llm_summary(self, query: str, item: EvidenceItem, steps: List[str]) -> Optional[str]:
        """One-sentence plain-language summary from a local model. Never replaces the steps."""
        if not self.settings.enable_llm_summary:
            return None
        prompt = (
            "Summarise in ONE short sentence what the person should focus on, using ONLY these protocol steps. "
            "Do not add any new advice, drugs or doses.\n"
            f"Question: {query}\nProtocol: {item.title}\nSteps:\n" + "\n".join(steps)
        )
        try:
            with httpx.Client(timeout=2.5) as client:
                res = client.post(f"{self.settings.ollama_url}/api/generate",
                                  json={"model": self.settings.ollama_model, "prompt": prompt, "stream": False})
            if res.status_code == 200:
                text = (res.json().get("response") or "").strip()
                return text.split("\n")[0][:300] or None
        except Exception as e:
            logger.info("LLM summary unavailable: %s", e)
        return None


_builder: Optional[GroundedResponseBuilder] = None


def get_response_builder() -> GroundedResponseBuilder:
    global _builder
    if _builder is None:
        _builder = GroundedResponseBuilder()
    return _builder
