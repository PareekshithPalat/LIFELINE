import re
import time
import uuid
import threading
import logging
from collections import OrderedDict
from typing import Optional, Dict, Any, List, Tuple, Callable, Iterable
import numpy as np
from models.enums import RiskLevel, ValidationVerdict
from models.schemas import CacheEntry, GroundedResponse
from edge.config import get_retrieval_config

logger = logging.getLogger("lifeline.cache")

_TOKEN = re.compile(r"[a-z0-9']+")


def salient_terms(query: str, lexicon: Iterable[str]) -> List[str]:
    """
    Words that change the medically correct answer even when the sentence embedding
    barely moves: negations ("not breathing"), age ("baby"), drugs and allergens.
    Two queries may share a cache entry only if these sets are identical.
    """
    tokens = set(_TOKEN.findall(query.lower()))
    tokens |= {t.replace("'", "") for t in tokens}
    lex = set(lexicon)
    found = {t for t in tokens if t in lex or t.isdigit()}
    return sorted(found)


class EvidenceStateSemanticCache:
    """
    Evidence-State Semantic Cache.

    An entry is served only if ALL of these hold:
      1. cosine(query, entry) >= risk-adaptive threshold (stricter for CRITICAL)
      2. identical salient terms (negation / age / drug / allergen words)
      3. same patient age group
      4. TTL not expired (shorter for CRITICAL)
      5. personal profile version unchanged
      6. incident timeline version unchanged
      7. every bound evidence item still has the hash it had when cached
    Lookup is one vectorised matrix-vector product over all live entries.
    """

    def __init__(self, hash_resolver: Optional[Callable[[Iterable[str]], Dict[str, Optional[str]]]] = None,
                 max_entries: Optional[int] = None):
        cfg = get_retrieval_config()["cache"]
        self.thresholds = {RiskLevel(k): v for k, v in cfg["similarity"].items()}
        self.ttls = {RiskLevel(k): float(v) for k, v in cfg["ttl_seconds"].items()}
        self.lexicon = set(cfg["salient_terms"])
        self.max_entries = max_entries or cfg["max_entries"]
        self.hash_resolver = hash_resolver
        self.entries: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._matrix: Optional[np.ndarray] = None
        self._ids: List[str] = []
        self._lock = threading.RLock()
        self.stats = {"hits": 0, "misses": 0, "state_invalidations": 0, "expired_evictions": 0,
                      "lru_evictions": 0, "salient_mismatches": 0, "total_queries": 0}

    def _rebuild_matrix(self):
        self._ids = list(self.entries.keys())
        self._matrix = (np.asarray([self.entries[i].query_vector for i in self._ids], dtype=np.float32)
                        if self._ids else None)

    def _drop(self, entry_id: str, stat: Optional[str] = None):
        if self.entries.pop(entry_id, None) is not None:
            if stat:
                self.stats[stat] += 1
            self._matrix = None

    def get(self, query: str, query_vector: Optional[List[float]], current_personal_version: int,
            current_incident_version: int, age_category: str = "adult",
            current_evidence_hashes: Optional[Dict[str, str]] = None) -> Tuple[Optional[GroundedResponse], Dict[str, Any]]:
        with self._lock:
            self.stats["total_queries"] += 1
            if query_vector is None or not self.entries:
                self.stats["misses"] += 1
                return None, {"reason": "empty_cache" if query_vector is not None else "no_query_vector"}

            now = time.time()
            for eid in [e.id for e in self.entries.values() if now - e.created_at > e.ttl_seconds]:
                self._drop(eid, "expired_evictions")
            if self._matrix is None:
                self._rebuild_matrix()
            if self._matrix is None:
                self.stats["misses"] += 1
                return None, {"reason": "empty_cache"}

            sims = self._matrix @ np.asarray(query_vector, dtype=np.float32)
            terms = salient_terms(query, self.lexicon)
            best, best_sim, salient_blocked = None, -1.0, False
            for idx in np.argsort(-sims):
                sim = float(sims[idx])
                entry = self.entries[self._ids[idx]]
                if sim < self.thresholds.get(entry.risk_level, 0.95):
                    continue
                if entry.salient_terms != terms or entry.age_category != age_category:
                    salient_blocked = True
                    continue
                best, best_sim = entry, sim
                break

            if best is None:
                if salient_blocked:
                    self.stats["salient_mismatches"] += 1
                self.stats["misses"] += 1
                return None, {"reason": "salient_terms_differ" if salient_blocked else "no_semantic_match",
                              "max_similarity": float(sims.max())}

            if best.personal_version != current_personal_version:
                self._drop(best.id, "state_invalidations")
                self.stats["misses"] += 1
                return None, {"reason": "personal_state_invalidated", "similarity": best_sim}
            if best.incident_version != current_incident_version:
                self._drop(best.id, "state_invalidations")
                self.stats["misses"] += 1
                return None, {"reason": "incident_state_invalidated", "similarity": best_sim}

            hashes = current_evidence_hashes
            if hashes is None and self.hash_resolver and best.bound_evidence_ids:
                hashes = self.hash_resolver(best.bound_evidence_ids)
            for ev_id, bound in best.bound_evidence_hashes.items():
                if hashes is not None and ev_id in hashes and hashes[ev_id] != bound:
                    self._drop(best.id, "state_invalidations")
                    self.stats["misses"] += 1
                    return None, {"reason": "evidence_hash_mutated", "similarity": best_sim, "evidence_id": ev_id}

            self.stats["hits"] += 1
            best.hit_count += 1
            best.last_hit_at = now
            self.entries.move_to_end(best.id)
            resp = best.response.model_copy(deep=True)
            resp.cache_hit = True
            resp.cache_entry_id = best.id
            resp.state_valid = True
            return resp, {"hit": True, "similarity": best_sim, "entry_id": best.id, "hit_count": best.hit_count}

    def put(self, query: str, query_vector: Optional[List[float]], response: GroundedResponse,
            bound_evidence_hashes: Dict[str, str], personal_version: int, incident_version: int,
            age_category: str = "adult") -> Optional[str]:
        if query_vector is None or response.verdict == ValidationVerdict.INSUFFICIENT:
            return None
        with self._lock:
            entry_id = str(uuid.uuid4())
            self.entries[entry_id] = CacheEntry(
                id=entry_id, query_text=query, query_vector=list(query_vector),
                salient_terms=salient_terms(query, self.lexicon), age_category=age_category,
                bound_evidence_ids=list(bound_evidence_hashes.keys()),
                bound_evidence_hashes=dict(bound_evidence_hashes),
                incident_version=incident_version, personal_version=personal_version,
                response=response.model_copy(deep=True), risk_level=response.risk_level,
                created_at=time.time(), ttl_seconds=self.ttls.get(response.risk_level, 300.0),
            )
            while len(self.entries) > self.max_entries:
                oldest = next(iter(self.entries))
                self._drop(oldest, "lru_evictions")
            self._matrix = None
            return entry_id

    def invalidate_evidence(self, evidence_id: str) -> int:
        with self._lock:
            ids = [e.id for e in self.entries.values() if evidence_id in e.bound_evidence_hashes]
            for eid in ids:
                self._drop(eid, "state_invalidations")
            return len(ids)

    def invalidate_all(self):
        with self._lock:
            self.entries.clear()
            self._matrix = None

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.stats["total_queries"]
            return {**self.stats, "active_cached_entries": len(self.entries),
                    "hit_rate_pct": round(100.0 * self.stats["hits"] / total, 2) if total else 0.0}


_global_semantic_cache: Optional[EvidenceStateSemanticCache] = None


def get_semantic_cache() -> EvidenceStateSemanticCache:
    global _global_semantic_cache
    if _global_semantic_cache is None:
        from edge.qdrant.client import get_qdrant_manager
        _global_semantic_cache = EvidenceStateSemanticCache(hash_resolver=get_qdrant_manager().current_hashes)
    return _global_semantic_cache


def reset_semantic_cache():
    global _global_semantic_cache
    _global_semantic_cache = None
