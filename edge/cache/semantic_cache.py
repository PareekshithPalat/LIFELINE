import time
import logging
import uuid
from typing import Optional, Dict, Any, List, Tuple
from models.enums import RiskLevel
from models.schemas import CacheEntry, GroundedResponse
from edge.embeddings.engine import EmbeddingEngine, get_embedding_engine
from edge.qdrant.client import QdrantEdgeManager, get_qdrant_manager

logger = logging.getLogger("lifeline.cache")

SIMILARITY_THRESHOLDS = {
    RiskLevel.CRITICAL: 0.96,
    RiskLevel.HIGH: 0.94,
    RiskLevel.MEDIUM: 0.90,
    RiskLevel.LOW: 0.88
}

DEFAULT_TTLS = {
    RiskLevel.CRITICAL: 120.0,   # 2 minutes for immediate life threat
    RiskLevel.HIGH: 300.0,       # 5 minutes
    RiskLevel.MEDIUM: 900.0,     # 15 minutes
    RiskLevel.LOW: 3600.0        # 1 hour
}

class EvidenceStateSemanticCache:
    """
    Evidence-State Semantic Cache for Edge Medical Emergency Memory.
    Validates semantic similarity AND evidence state integrity (hashes, versions,
    active incident changes, and contraindication mutations) before serving.
    """
    def __init__(self, qdrant_manager: Optional[QdrantEdgeManager] = None):
        self.entries: Dict[str, CacheEntry] = {}
        self.qdrant = qdrant_manager or get_qdrant_manager()
        self.engine = get_embedding_engine()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "state_invalidations": 0,
            "expired_evictions": 0,
            "total_queries": 0
        }

    def get(
        self,
        query: str,
        current_personal_version: int = 1,
        current_incident_version: int = 1,
        current_evidence_hashes: Optional[Dict[str, str]] = None
    ) -> Tuple[Optional[GroundedResponse], Dict[str, Any]]:
        self.stats["total_queries"] += 1
        query_vec = self.engine.embed_text(query)
        now = time.time()

        best_entry: Optional[CacheEntry] = None
        best_sim: float = -1.0

        for entry_id, entry in list(self.entries.items()):
            # 1. TTL Check
            if now - entry.created_at > entry.ttl_seconds:
                self.stats["expired_evictions"] += 1
                del self.entries[entry_id]
                continue

            sim = EmbeddingEngine.cosine_similarity(query_vec, entry.query_vector)
            threshold = SIMILARITY_THRESHOLDS.get(entry.risk_level, 0.90)

            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_entry = entry

        if not best_entry:
            self.stats["misses"] += 1
            return None, {"reason": "no_semantic_match", "max_similarity": best_sim}

        # 2. State Validation: Personal profile version
        if best_entry.personal_version != current_personal_version:
            logger.info("Cache entry %s invalidated: personal profile version changed (%d -> %d)",
                        best_entry.id, best_entry.personal_version, current_personal_version)
            self._invalidate_entry(best_entry.id)
            return None, {"reason": "personal_state_invalidated", "similarity": best_sim}

        # 3. State Validation: Incident observation timeline version
        if best_entry.incident_version != current_incident_version:
            logger.info("Cache entry %s invalidated: incident timeline changed (%d -> %d)",
                        best_entry.id, best_entry.incident_version, current_incident_version)
            self._invalidate_entry(best_entry.id)
            return None, {"reason": "incident_state_invalidated", "similarity": best_sim}

        # 4. State Validation: Bound evidence hashes
        if current_evidence_hashes:
            for ev_id, bound_hash in best_entry.bound_evidence_hashes.items():
                cur_hash = current_evidence_hashes.get(ev_id)
                if cur_hash is not None and cur_hash != bound_hash:
                    logger.info("Cache entry %s invalidated: bound evidence %s hash mutated (%s -> %s)",
                                best_entry.id, ev_id, bound_hash, cur_hash)
                    self._invalidate_entry(best_entry.id)
                    return None, {"reason": "evidence_hash_mutated", "similarity": best_sim}

        # 5. Cache Hit - Update stats & return response copy
        self.stats["hits"] += 1
        best_entry.hit_count += 1
        
        resp = best_entry.response.model_copy(deep=True)
        resp.cache_hit = True
        resp.cache_entry_id = best_entry.id
        resp.state_valid = True
        return resp, {
            "hit": True,
            "similarity": best_sim,
            "entry_id": best_entry.id,
            "hit_count": best_entry.hit_count
        }

    def put(
        self,
        query: str,
        response: GroundedResponse,
        bound_evidence_ids: List[str],
        bound_evidence_hashes: Dict[str, str],
        personal_version: int = 1,
        incident_version: int = 1
    ) -> str:
        entry_id = str(uuid.uuid4())
        query_vec = self.engine.embed_text(query)
        ttl = DEFAULT_TTLS.get(response.risk_level, 900.0)

        entry = CacheEntry(
            id=entry_id,
            query_text=query,
            query_vector=query_vec,
            bound_evidence_ids=bound_evidence_ids,
            bound_evidence_hashes=bound_evidence_hashes,
            incident_version=incident_version,
            personal_version=personal_version,
            response=response,
            risk_level=response.risk_level,
            created_at=time.time(),
            ttl_seconds=ttl,
            hit_count=0
        )
        self.entries[entry_id] = entry
        return entry_id

    def _invalidate_entry(self, entry_id: str):
        if entry_id in self.entries:
            del self.entries[entry_id]
            self.stats["state_invalidations"] += 1

    def invalidate_all(self):
        self.entries.clear()

    def get_stats(self) -> Dict[str, Any]:
        total = self.stats["total_queries"]
        hit_rate = (self.stats["hits"] / total) if total > 0 else 0.0
        return {
            **self.stats,
            "active_cached_entries": len(self.entries),
            "hit_rate_pct": round(hit_rate * 100, 2)
        }

_global_semantic_cache: Optional[EvidenceStateSemanticCache] = None

def get_semantic_cache() -> EvidenceStateSemanticCache:
    global _global_semantic_cache
    if _global_semantic_cache is None:
        _global_semantic_cache = EvidenceStateSemanticCache()
    return _global_semantic_cache
