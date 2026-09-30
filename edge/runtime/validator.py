import logging
from typing import List, Dict, Any, Tuple, Optional
from models.enums import ValidationVerdict, RiskLevel, MemoryTier
from models.schemas import SourceCitation, PersonalProfile

logger = logging.getLogger("lifeline.validator")

MIN_CONFIDENCE_THRESHOLD = 0.015

class EvidenceValidator:
    """
    Validates retrieved evidence against the 3-state emergency paradigm:
    1. SUFFICIENT: Direct, uncontradicted evidence found.
    2. CONFLICT: Active contraindication or conflicting medical guidelines detected.
    3. INSUFFICIENT: Low confidence or out-of-domain query. Refuses to hallucinate.
    """
    def validate(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        risk_level: RiskLevel,
        personal_profile: Optional[PersonalProfile] = None
    ) -> Tuple[ValidationVerdict, List[SourceCitation], List[str], Dict[str, Any]]:
        if not candidates:
            return (
                ValidationVerdict.INSUFFICIENT,
                [],
                ["No relevant emergency medical protocols found in local memory."],
                {"reason": "empty_candidate_pool"}
            )

        top_cand = candidates[0]
        top_score = top_cand.get("composite_score", 0.0)

        # 1. Insufficient Evidence Check
        if top_score < MIN_CONFIDENCE_THRESHOLD:
            logger.warning("Top candidate score %.4f below minimum threshold %.4f for query: '%s'",
                           top_score, MIN_CONFIDENCE_THRESHOLD, query)
            return (
                ValidationVerdict.INSUFFICIENT,
                [],
                ["Retrieved information does not meet emergency clinical confidence thresholds."],
                {"reason": "low_confidence_score", "top_score": top_score}
            )

        # 2. Build citations and inspect conflicts
        citations: List[SourceCitation] = []
        all_contraindications: List[str] = []
        has_critical_conflict = False

        top_cand_contra = top_cand.get("contraindications_found", [])
        if top_cand_contra:
            has_critical_conflict = True
            all_contraindications.extend(top_cand_contra)

        for cand in candidates[:4]:
            payload = cand.get("payload", {})
            tier_str = payload.get("tier", cand.get("tier", MemoryTier.TRUSTED))
            try:
                tier = MemoryTier(tier_str)
            except ValueError:
                tier = MemoryTier.TRUSTED

            cand_contra = cand.get("contraindications_found", [])
            # If the user specifically asks if something is safe or contraindication check, any matching candidate triggers conflict
            if cand_contra and any(k in query.lower() for k in ["can i give", "safe to", "contraindication", "aspirin", "ibuprofen", "allergic"]):
                has_critical_conflict = True
                all_contraindications.extend(cand_contra)

            content = payload.get("content", "")
            snippet = content[:200] + "..." if len(content) > 200 else content

            citations.append(
                SourceCitation(
                    evidence_id=cand.get("id", payload.get("evidence_id", "unknown")),
                    tier=tier,
                    title=payload.get("title", "Guideline"),
                    snippet=snippet,
                    version=payload.get("version", 1),
                    hash=payload.get("hash", ""),
                    relevance_score=round(cand.get("composite_score", 0.0), 4),
                    freshness_timestamp=payload.get("updated_at") or payload.get("created_at"),
                    contraindications_found=cand_contra
                )
            )

        # 3. Conflict / Contraindication Verdict
        if has_critical_conflict:
            logger.warning("Active contraindication conflict detected for query: '%s'", query)
            return (
                ValidationVerdict.CONFLICT,
                citations,
                list(set(all_contraindications)),
                {"reason": "contraindication_detected", "conflict_count": len(all_contraindications)}
            )

        # 4. Sufficient Verdict
        return (
            ValidationVerdict.SUFFICIENT,
            citations,
            all_contraindications,
            {"status": "validated", "citation_count": len(citations)}
        )

_global_validator: Optional[EvidenceValidator] = None

def get_validator() -> EvidenceValidator:
    global _global_validator
    if _global_validator is None:
        _global_validator = EvidenceValidator()
    return _global_validator
