import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from edge.config import get_retrieval_config
from edge.runtime.safety import ADULT, ADOLESCENT, CHILD, INFANT

logger = logging.getLogger("lifeline.validator")


@dataclass
class GateResult:
    accepted: bool
    primary: Optional[Dict[str, Any]] = None
    related: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    mode: str = "none"
    reason: str = ""


class EvidenceValidator:
    """
    Relevance gate: decides whether a trusted protocol clearly answers the query.
    Below the calibrated thresholds the system ABSTAINS instead of returning the
    "least unrelated" protocol. Safety screening of the accepted protocol happens
    afterwards in the response builder (SUFFICIENT vs CONFLICT).
    """

    def __init__(self):
        self.gate = get_retrieval_config()["gate"]

    def _passes(self, cand: Dict[str, Any], second: Optional[Dict[str, Any]]) -> bool:
        g = self.gate
        if cand["mode"] == "lexical_only":
            margin = cand["bm25_score"] - (second["bm25_score"] if second else 0.0)
            return cand["bm25_score"] >= g["lexical_only_min_bm25"] and margin >= g["lexical_only_min_margin"]
        return (cand["confidence"] >= g["accept_confidence"]
                and cand["dense_score"] >= g["min_dense"]
                and cand["bm25_score"] >= g["min_bm25"])

    def evaluate(self, candidates: List[Dict[str, Any]], age_category: Optional[str] = None) -> GateResult:
        if not candidates:
            return GateResult(False, reason="no_candidates")

        accepted = [c for i, c in enumerate(candidates)
                    if self._passes(c, candidates[i + 1] if i + 1 < len(candidates) else None)]
        if not accepted:
            top = candidates[0]
            logger.info("Gate rejected all candidates (top %s conf=%.3f dense=%.3f bm25=%.2f)",
                        top["evidence_id"], top["confidence"], top["dense_score"], top["bm25_score"])
            return GateResult(False, confidence=round(top["confidence"], 4), mode=top["mode"],
                              reason="below_relevance_threshold")

        primary = accepted[0]
        # Age-specific protocol preference (e.g. infant CPR over adult CPR).
        wanted = {CHILD: "pediatric", INFANT: "pediatric", ADULT: "adult", ADOLESCENT: "adult"}.get(age_category or "")
        if wanted:
            for c in accepted:
                if c["item"].metadata.get("population") == wanted:
                    primary = c
                    break

        related = [c for c in accepted if c is not primary
                   and primary["confidence"] - c["confidence"] <= self.gate["related_margin"]]
        return GateResult(True, primary, related, round(primary["confidence"], 4), primary["mode"], "accepted")


_global_validator: Optional[EvidenceValidator] = None


def get_validator() -> EvidenceValidator:
    global _global_validator
    if _global_validator is None:
        _global_validator = EvidenceValidator()
    return _global_validator
