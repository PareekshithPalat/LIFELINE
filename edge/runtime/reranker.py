import re
import logging
from typing import List, Dict, Any, Optional
from models.enums import RiskLevel, MemoryTier
from models.schemas import PersonalProfile

logger = logging.getLogger("lifeline.reranker")

TIER_AUTHORITY_WEIGHTS = {
    MemoryTier.TRUSTED: 1.35,
    MemoryTier.PERSONAL: 1.25,
    MemoryTier.INCIDENT: 1.15
}

class RiskAwareReranker:
    """
    Reranks hybrid retrieval candidates by factoring:
    1. Base RRF score
    2. Memory Tier authority (Clinical Trusted > Confirmed Personal > Incident on-scene)
    3. Emergency Risk Level alignment
    4. Personal Contraindication cross-matching (e.g. Aspirin/NSAID allergy with bleeding/pain protocols)
    """
    def rerank(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        risk_level: RiskLevel,
        personal_profile: Optional[PersonalProfile] = None
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        user_allergies = [a.lower() for a in (personal_profile.allergies if personal_profile else [])]
        user_conditions = [c.lower() for c in (personal_profile.chronic_conditions if personal_profile else [])]
        user_meds = [m.lower() for m in (personal_profile.current_medications if personal_profile else [])]

        reranked = []
        for cand in candidates:
            item = dict(cand)
            payload = item.get("payload", {})
            tier_str = payload.get("tier", item.get("tier", MemoryTier.TRUSTED))
            try:
                tier = MemoryTier(tier_str)
            except ValueError:
                tier = MemoryTier.TRUSTED

            base_rrf = item.get("rrf_score", 0.0)
            authority_mult = TIER_AUTHORITY_WEIGHTS.get(tier, 1.0)
            score = base_rrf * authority_mult

            # Risk Alignment Boost
            cand_risk = payload.get("risk_level", RiskLevel.MEDIUM)
            if risk_level == RiskLevel.CRITICAL:
                if cand_risk == RiskLevel.CRITICAL:
                    score *= 1.4
                elif cand_risk == RiskLevel.HIGH:
                    score *= 1.2
            elif risk_level == RiskLevel.HIGH and cand_risk == RiskLevel.HIGH:
                score *= 1.25

            # Contraindication Cross-Matching
            contraindications_found = []
            content_text = (payload.get("title", "") + " " + payload.get("content", "")).lower()

            for allergy in user_allergies:
                if allergy and re.search(r'\b' + re.escape(allergy) + r'\b', content_text):
                    contraindications_found.append(f"ALLERGY ALERT: Patient is allergic to '{allergy}', which appears in this guideline.")

            for condition in user_conditions:
                if "bleed" in condition and ("aspirin" in content_text or "blood thinner" in content_text):
                    contraindications_found.append(f"CONDITION WARNING: Patient has '{condition}', contraindicating blood-thinning agents.")
                if "asthma" in condition and ("beta-blocker" in content_text or "nsaid" in content_text):
                    contraindications_found.append(f"CONDITION WARNING: Patient has '{condition}', caution with NSAIDs or non-selective agents.")

            # Add existing item contraindications
            raw_contra = payload.get("contraindications", [])
            for c in raw_contra:
                if any(al in c.lower() for al in user_allergies):
                    contraindications_found.append(f"DIRECT CONTRAINDICATION: {c}")

            item["composite_score"] = score
            item["contraindications_found"] = contraindications_found
            item["has_contraindication"] = len(contraindications_found) > 0

            reranked.append(item)

        # Sort descending by composite score
        reranked.sort(key=lambda x: x["composite_score"], reverse=True)
        return reranked

_global_reranker: Optional[RiskAwareReranker] = None

def get_reranker() -> RiskAwareReranker:
    global _global_reranker
    if _global_reranker is None:
        _global_reranker = RiskAwareReranker()
    return _global_reranker
