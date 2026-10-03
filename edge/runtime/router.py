import re
import logging
from typing import Tuple, Dict, Any, Optional
from models.enums import RiskLevel, QueryIntent
from edge.runtime.safety import detect_age_category

logger = logging.getLogger("lifeline.router")

CRITICAL_KEYWORDS = [
    r"\bunconscious\b", r"\bunresponsive\b", r"\bnot breathing\b", r"\bstopped breathing\b", r"\bisn'?t breathing\b",
    r"\bno pulse\b", r"\bcollapsed?\b", r"\bcardiac arrest\b", r"\bcpr\b", r"\bheart attack\b", r"\bsevere bleeding\b",
    r"\barterial\b", r"\bgushing\b", r"\bspurting\b", r"\btourniquet\b", r"\banaphyla", r"\bthroat (is )?(closing|swelling)\b",
    r"\bchoking\b", r"\bairway\b", r"\bepipen\b", r"\bepinephrine\b", r"\bchest compressions?\b", r"\baed\b",
    r"\bdefibrillator\b", r"\bdrowning\b", r"\bblue lips\b", r"\bcyanosis\b", r"\bhemorrhage\b", r"\bhaemorrhage\b",
    r"\boverdose\b", r"\bnarcan\b", r"\bnaloxone\b", r"\bcan'?t breathe\b", r"\bcannot breathe\b",
]

HIGH_KEYWORDS = [
    r"\bburns?\b", r"\bburned\b", r"\bscald", r"\bfracture\b", r"\bbroken bone\b", r"\bseizure\b", r"\bconvuls",
    r"\bfit\b", r"\bpoison", r"\bingested\b", r"\bswallowed\b", r"\bbleach\b", r"\bchemical\b", r"\basthma\b",
    r"\binhaler\b", r"\bwheez", r"\bconcussion\b", r"\bhead injury\b", r"\bstroke\b", r"\bface droop", r"\bdrooping\b",
    r"\bslurred\b", r"\bhypothermia\b", r"\bheatstroke\b", r"\bsnake ?bite\b", r"\bvenom\b", r"\bdeep cut\b",
    r"\blaceration\b", r"\bbleeding\b", r"\bdiabetic\b", r"\bhypoglyc", r"\blow blood sugar\b", r"\binsulin\b",
    r"\bchest pain\b", r"\bchest pressure\b",
]

MEDIUM_KEYWORDS = [
    r"\bsprain\b", r"\bstrain\b", r"\bbruise\b", r"\bmild allergy\b", r"\brash\b", r"\bhives\b", r"\bbee sting\b",
    r"\binsect bite\b", r"\bfever\b", r"\bnausea\b", r"\bheadache\b", r"\bdressing\b", r"\bbandage\b",
    r"\bblister", r"\baspirin\b", r"\bibuprofen\b", r"\bmedication\b", r"\bdose\b", r"\bdrug\b", r"\bpill",
]

INTENT_PATTERNS = [
    (QueryIntent.EMERGENCY_CONTACT, [r"\bemergency contacts?\b", r"\bnext of kin\b", r"\bice contacts?\b",
                                     r"\bwho (should|do) i call\b", r"\bwho to call\b"]),
    (QueryIntent.PERSONAL_MED_CHECK, [r"\bblood (type|group)\b", r"\bmy allergies\b",
                                      r"\bwhat (am i|is (he|she|the patient)) allergic to\b",
                                      r"\b(my|patient'?s?|current) medications\b", r"\bmedical history\b",
                                      r"\bmedical profile\b", r"\bmy profile\b", r"\bchronic conditions?\b"]),
    (QueryIntent.INCIDENT_UPDATE, [r"\btimeline\b", r"\bincident (report|summary|log)\b", r"\blogged vitals?\b",
                                   r"\bwhat has been done\b", r"\bactions taken\b"]),
    (QueryIntent.CONTRAINDICATION_CHECK, [r"\bcan i give\b", r"\bsafe to (give|take|use)\b", r"\bcontraindicat",
                                          r"\bshould i give\b", r"\binteraction\b", r"\bok(ay)? to (give|take)\b"]),
    (QueryIntent.TRIAGE_ASSESSMENT, [r"\btriage\b", r"\bassess\b", r"\bpriority\b", r"\bcheck vitals\b"]),
    (QueryIntent.GENERAL_PREPAREDNESS, [r"\bfirst aid kit\b", r"\bsupplies\b", r"\bprepar(e|ation|edness)\b",
                                        r"\bchecklist\b"]),
]

PROFILE_INTENTS = {QueryIntent.PERSONAL_MED_CHECK, QueryIntent.EMERGENCY_CONTACT}


class IntentAndRiskRouter:
    """
    Zero-latency rule router that determines:
    1. Risk level (CRITICAL / HIGH / MEDIUM / LOW) - drives cache strictness and escalation
    2. Intent - decides whether the answer comes from protocols, the profile or the incident log
    3. Patient age group when stated in the query (adult / adolescent / child / infant)
    """

    def route(self, query: str) -> Tuple[RiskLevel, QueryIntent, Dict[str, Any]]:
        text = query.lower()

        if any(re.search(p, text) for p in CRITICAL_KEYWORDS):
            risk = RiskLevel.CRITICAL
        elif any(re.search(p, text) for p in HIGH_KEYWORDS):
            risk = RiskLevel.HIGH
        elif any(re.search(p, text) for p in MEDIUM_KEYWORDS):
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        intent = QueryIntent.FIRST_AID_INSTRUCTION
        for candidate, patterns in INTENT_PATTERNS:
            if any(re.search(p, text) for p in patterns):
                intent = candidate
                break

        details = {
            "age_category": detect_age_category(query),
            "requires_immediate_action": risk in (RiskLevel.CRITICAL, RiskLevel.HIGH),
        }
        return risk, intent, details


_global_router: Optional[IntentAndRiskRouter] = None


def get_router() -> IntentAndRiskRouter:
    global _global_router
    if _global_router is None:
        _global_router = IntentAndRiskRouter()
    return _global_router
