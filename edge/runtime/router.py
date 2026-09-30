import re
import logging
from typing import Tuple, Dict, Any, List, Optional
from models.enums import RiskLevel, QueryIntent

logger = logging.getLogger("lifeline.router")

CRITICAL_KEYWORDS = [
    r"\bunconscious\b", r"\bnot breathing\b", r"\bstopped breathing\b", r"\bno pulse\b",
    r"\bcardiac arrest\b", r"\bcpr\b", r"\bheart attack\b", r"\bsevere bleeding\b",
    r"\barterial\b", r"\bgushing\b", r"\btourniquet\b", r"\banaphylaxis\b",
    r"\bchoking\b", r"\bairway\b", r"\bepipen\b", r"\bepinephrine\b",
    r"\bchest compression\b", r"\baed\b", r"\bdefibrillator\b", r"\bdrowning\b",
    r"\bblue lips\b", r"\bcyanosis\b", r"\bsevere hemorrhage\b", r"\boverdose\b",
    r"\bnarcan\b", r"\bnaloxone\b"
]

HIGH_KEYWORDS = [
    r"\bburn\b", r"\bscalding\b", r"\bfracture\b", r"\bbroken bone\b", r"\bcompound fracture\b",
    r"\bseizure\b", r"\bconvulsion\b", r"\bpoison\b", r"\bingested\b", r"\bchemical\b",
    r"\basthma\b", r"\binhaler\b", r"\bconcussion\b", r"\bhead injury\b", r"\bhead trauma\b",
    r"\bstroke\b", r"\bface droop\b", r"\bspeech slurred\b", r"\bhypothermia\b",
    r"\bheatstroke\b", r"\bsnakebite\b", r"\bvenom\b", r"\bdeep cut\b", r"\blaceration\b",
    r"\bdiabetic\b", r"\bhypoglycemia\b", r"\binsulin\b"
]

MEDIUM_KEYWORDS = [
    r"\bsprain\b", r"\bstrain\b", r"\bbruise\b", r"\bmild allergy\b", r"\brash\b",
    r"\bhives\b", r"\bbee sting\b", r"\binsect bite\b", r"\bmild fever\b", r"\bnausea\b",
    r"\bpain medicine\b", r"\bheadache\b", r"\bdressing\b", r"\bbandage\b", r"\bblister\b",
    r"\baspirin\b", r"\bibuprofen\b", r"\bmedication\b", r"\bdose\b", r"\bdrug\b", r"\bpill\b"
]

INTENT_PATTERNS = [
    (QueryIntent.TRIAGE_ASSESSMENT, [r"\btriage\b", r"\bassess\b", r"\bpriority\b", r"\bcheck vitals\b", r"\bpatient status\b"]),
    (QueryIntent.CONTRAINDICATION_CHECK, [r"\bcan i give\b", r"\bsafe to give\b", r"\bcontraindication\b", r"\ballergic to\b", r"\binteraction\b"]),
    (QueryIntent.PERSONAL_MED_CHECK, [r"\bmy blood\b", r"\bmy allergies\b", r"\bmy medication\b", r"\bmy ice\b", r"\bmedical history\b", r"\bprofile\b"]),
    (QueryIntent.INCIDENT_UPDATE, [r"\blog vital\b", r"\bpatient pulse\b", r"\baction taken\b", r"\btimeline\b", r"\bincident report\b"]),
    (QueryIntent.EMERGENCY_CONTACT, [r"\bemergency contact\b", r"\bcall next of kin\b", r"\bice contact\b", r"\bwho to call\b", r"\bhospital number\b"]),
    (QueryIntent.GENERAL_PREPAREDNESS, [r"\bkit\b", r"\bchecklist\b", r"\bpreparation\b", r"\bsupplies\b", r"\bguideline\b"])
]

class IntentAndRiskRouter:
    """
    Rapid, zero-latency rule & semantic router that determines:
    1. Risk Level: CRITICAL, HIGH, MEDIUM, LOW
    2. Intent: FIRST_AID_INSTRUCTION, CONTRAINDICATION_CHECK, etc.
    """
    def route(self, query: str) -> Tuple[RiskLevel, QueryIntent, Dict[str, Any]]:
        text = query.lower()

        # 1. Determine Risk Level
        for pat in CRITICAL_KEYWORDS:
            if re.search(pat, text):
                risk = RiskLevel.CRITICAL
                break
        else:
            for pat in HIGH_KEYWORDS:
                if re.search(pat, text):
                    risk = RiskLevel.HIGH
                    break
            else:
                for pat in MEDIUM_KEYWORDS:
                    if re.search(pat, text):
                        risk = RiskLevel.MEDIUM
                        break
                else:
                    risk = RiskLevel.LOW

        # 2. Determine Intent
        intent = QueryIntent.FIRST_AID_INSTRUCTION  # default
        for candidate_intent, patterns in INTENT_PATTERNS:
            if any(re.search(p, text) for p in patterns):
                intent = candidate_intent
                break

        details = {
            "critical_signal": risk == RiskLevel.CRITICAL,
            "requires_immediate_action": risk in [RiskLevel.CRITICAL, RiskLevel.HIGH],
            "bypass_slow_inference": risk == RiskLevel.CRITICAL
        }
        return risk, intent, details

_global_router: Optional[IntentAndRiskRouter] = None

def get_router() -> IntentAndRiskRouter:
    global _global_router
    if _global_router is None:
        _global_router = IntentAndRiskRouter()
    return _global_router
