import os
import re
import json
import uuid
import shutil
import tempfile
import threading
import logging
from typing import List, Dict, Any, Optional, Iterable
from qdrant_edge import (
    EdgeShard,
    EdgeConfig,
    EdgeVectorParams,
    EdgeSparseVectorParams,
    Distance,
    Modifier,
    Point,
    UpdateOperation,
    QueryRequest,
    Query,
    ScrollRequest,
    CountRequest,
    Filter,
    FieldCondition,
    MatchValue,
)
from models.enums import MemoryTier
from models.schemas import EvidenceItem
from edge.config import get_settings, get_retrieval_config
from edge.embeddings.engine import EmbeddingEngine, get_embedding_engine

logger = logging.getLogger("lifeline.qdrant")

DENSE = "dense"
SPARSE = "bm25"

SHARD_DIRS = {
    MemoryTier.TRUSTED: "trusted",
    MemoryTier.PERSONAL: "personal",
    MemoryTier.INCIDENT: "incident",
}

_STEP_PREFIX = re.compile(r"^\s*step\s*\d+\s*[:.)-]\s*", re.IGNORECASE)


def point_uuid(raw_id: str) -> str:
    """Deterministic UUID for any string id (Qdrant point ids must be ints or UUIDs)."""
    try:
        return str(uuid.UUID(raw_id))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))


def split_steps(content: str) -> List[str]:
    """Splits protocol content into individual instruction lines without truncation."""
    steps = []
    for line in content.split("\n"):
        cleaned = _STEP_PREFIX.sub("", line).strip().lstrip("-•*").strip()
        if cleaned:
            steps.append(cleaned)
    return steps


def evidence_chunks(item: EvidenceItem) -> List[Dict[str, str]]:
    """Short, single-idea texts that get their own dense vector (max-sim per evidence)."""
    chunks = [{"kind": "title", "text": item.title}]
    chunks += [{"kind": "trigger", "text": t} for t in item.triggers if t.strip()]
    chunks += [{"kind": "step", "text": s} for s in split_steps(item.content)]
    return chunks


def evidence_fulltext(item: EvidenceItem) -> str:
    return "\n".join([item.title, item.content, " ".join(item.tags), " ".join(item.triggers)])


def _evidence_filter(evidence_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="evidence_id", match=MatchValue(evidence_id))])


_DOC_FILTER = Filter(must=[FieldCondition(key="kind", match=MatchValue("doc"))])


class QdrantEdgeManager:
    """
    Embedded Qdrant Edge storage (one EdgeShard per memory tier).

    Each evidence item is stored as:
      * one "doc" point: BM25 sparse vector over the full text (IDF modifier) + the
        complete item as payload, and
      * N "chunk" points: dense vectors for the title, every trigger phrase and every
        step, so a query is scored by its best-matching single idea instead of an
        averaged whole-document embedding.

    A manifest records the schema version and dense model; if either changes the
    shards are rebuilt from the stored items so vectors from different embedding
    spaces are never mixed.
    """

    def __init__(self, storage_path: Optional[str] = None, memory_mode: Optional[bool] = None,
                 engine: Optional[EmbeddingEngine] = None):
        settings = get_settings()
        self.memory_mode = settings.memory_mode if memory_mode is None else memory_mode
        self._tmpdir = tempfile.mkdtemp(prefix="lifeline_edge_") if self.memory_mode else None
        self.storage_path = self._tmpdir or storage_path or settings.shard_path
        self.engine = engine or get_embedding_engine()
        self.schema_version = get_retrieval_config()["schema_version"]
        self._lock = threading.RLock()
        self.shards: Dict[MemoryTier, EdgeShard] = {}
        # In-memory mirror of every stored item: O(1) hash/version lookups for the
        # cache validator and no payload parsing on the query path.
        self._docs: Dict[MemoryTier, Dict[str, EvidenceItem]] = {t: {} for t in SHARD_DIRS}
        self._open()

    # ------------------------------------------------------------------ lifecycle
    def _config(self) -> EdgeConfig:
        return EdgeConfig(
            vectors={DENSE: EdgeVectorParams(size=self.engine.dense_dim, distance=Distance.Cosine)},
            sparse_vectors={SPARSE: EdgeSparseVectorParams(modifier=Modifier.Idf)},
        )

    def _manifest_path(self) -> str:
        return os.path.join(self.storage_path, "manifest.json")

    def _read_manifest(self) -> Optional[dict]:
        try:
            with open(self._manifest_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_manifest(self, dense_model: str):
        with open(self._manifest_path(), "w", encoding="utf-8") as f:
            json.dump({"schema_version": self.schema_version, "dense_model": dense_model}, f)

    def _open_shard(self, tier: MemoryTier) -> EdgeShard:
        path = os.path.join(self.storage_path, SHARD_DIRS[tier])
        if os.path.isdir(path) and os.listdir(path):
            return EdgeShard.load(path, self._config())
        os.makedirs(path, exist_ok=True)
        return EdgeShard.create(path, self._config())

    def _open(self):
        os.makedirs(self.storage_path, exist_ok=True)
        manifest = self._read_manifest()
        needs_rebuild = manifest is not None and (
            manifest.get("schema_version") != self.schema_version
            or (self.engine.dense_available and manifest.get("dense_model") != self.engine.model_id)
        )
        preserved: Dict[MemoryTier, List[EvidenceItem]] = {}
        if needs_rebuild:
            logger.warning("Index manifest %s does not match (schema %s, model %s); rebuilding shards.",
                           manifest, self.schema_version, self.engine.model_id)
            preserved = self._export_and_wipe()
        elif manifest is None and any(
            os.path.isdir(os.path.join(self.storage_path, d)) for d in SHARD_DIRS.values()
        ):
            # Shards without a manifest come from an unknown build; start clean.
            self._export_and_wipe()

        for tier in SHARD_DIRS:
            self.shards[tier] = self._open_shard(tier)
            self._load_docs(tier)

        if manifest is None or needs_rebuild:
            self._write_manifest(self.engine.model_id)
        for tier, items in preserved.items():
            self.upsert_many(items)

    def _export_and_wipe(self) -> Dict[MemoryTier, List[EvidenceItem]]:
        preserved: Dict[MemoryTier, List[EvidenceItem]] = {}
        for tier, dirname in SHARD_DIRS.items():
            path = os.path.join(self.storage_path, dirname)
            if not os.path.isdir(path):
                continue
            try:
                shard = EdgeShard.load(path)
                preserved[tier] = [EvidenceItem.model_validate(r.payload["item"])
                                   for r in self._scroll_docs(shard) if r.payload and "item" in r.payload]
                shard.close()
            except Exception as e:
                logger.error("Could not export %s shard during rebuild: %s", tier.value, e)
            shutil.rmtree(path, ignore_errors=True)
        return preserved

    @staticmethod
    def _scroll_docs(shard: EdgeShard) -> Iterable:
        offset = None
        while True:
            records, offset = shard.scroll(ScrollRequest(offset=offset, limit=256, filter=_DOC_FILTER,
                                                         with_payload=True))
            yield from records
            if offset is None:
                break

    def _load_docs(self, tier: MemoryTier):
        docs = {}
        for r in self._scroll_docs(self.shards[tier]):
            try:
                item = EvidenceItem.model_validate(r.payload["item"])
                docs[item.id] = item
            except Exception as e:
                logger.error("Skipping unreadable point in %s: %s", tier.value, e)
        self._docs[tier] = docs

    def close(self):
        with self._lock:
            for shard in self.shards.values():
                try:
                    shard.flush()
                    shard.close()
                except Exception:
                    pass
            self.shards.clear()
            if self._tmpdir:
                shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------ writes
    def _points_for(self, item: EvidenceItem) -> List[Point]:
        points = []
        payload_item = item.model_dump(mode="json")
        sparse = self.engine.embed_sparse_document(evidence_fulltext(item))
        doc_vectors = {SPARSE: sparse} if len(sparse.indices) > 0 else {}
        points.append(Point(point_uuid(f"{item.id}#doc"), doc_vectors, {
            "evidence_id": item.id, "kind": "doc", "tier": item.tier.value, "item": payload_item,
        }))
        if self.engine.dense_available:
            chunks = evidence_chunks(item)
            vectors = self.engine.embed_texts([c["text"] for c in chunks])
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                points.append(Point(point_uuid(f"{item.id}#c{i}"), {DENSE: vec}, {
                    "evidence_id": item.id, "kind": chunk["kind"], "text": chunk["text"],
                }))
        return points

    def upsert_evidence(self, item: EvidenceItem) -> bool:
        return self.upsert_many([item]) == 1

    def upsert_many(self, items: List[EvidenceItem]) -> int:
        written = 0
        with self._lock:
            touched = set()
            for item in items:
                try:
                    shard = self.shards[item.tier]
                    # Remove stale chunks first: an edited protocol can have fewer steps.
                    shard.update(UpdateOperation.delete_points_by_filter(_evidence_filter(item.id)))
                    shard.update(UpdateOperation.upsert_points(self._points_for(item)))
                    self._docs[item.tier][item.id] = item
                    touched.add(item.tier)
                    written += 1
                except Exception as e:
                    logger.error("Error upserting evidence %s: %s", item.id, e)
            for tier in touched:
                self.shards[tier].flush()
        return written

    def delete_evidence(self, tier: MemoryTier, evidence_id: str) -> bool:
        with self._lock:
            try:
                self.shards[tier].update(UpdateOperation.delete_points_by_filter(_evidence_filter(evidence_id)))
                self.shards[tier].flush()
                self._docs[tier].pop(evidence_id, None)
                return True
            except Exception as e:
                logger.error("Error deleting evidence %s: %s", evidence_id, e)
                return False

    # ------------------------------------------------------------------ reads
    def get_evidence(self, tier: MemoryTier, evidence_id: str) -> Optional[EvidenceItem]:
        return self._docs[tier].get(evidence_id)

    def list_evidence(self, tier: MemoryTier) -> List[EvidenceItem]:
        return sorted(self._docs[tier].values(), key=lambda i: i.title)

    def current_hashes(self, evidence_ids: Iterable[str]) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        for ev_id in evidence_ids:
            found = None
            for docs in self._docs.values():
                if ev_id in docs:
                    found = docs[ev_id].hash
                    break
            out[ev_id] = found
        return out

    def search(self, tier: MemoryTier, dense_vector: Optional[List[float]], sparse_vector,
               limit: int = 8) -> List[Dict[str, Any]]:
        """
        Hybrid search returning one candidate per evidence item with both raw signals:
          dense_score  - max cosine similarity over the item's chunks
          bm25_score   - BM25 (IDF-weighted) score of the full text
        Calibrated fusion of the two happens in the validator.
        """
        shard = self.shards[tier]
        docs = self._docs[tier]
        if not docs:
            return []
        candidates: Dict[str, Dict[str, Any]] = {}

        if dense_vector is not None:
            hits = shard.query(QueryRequest(limit=min(400, 30 * max(limit, 1)),
                                            query=Query.Nearest(dense_vector, using=DENSE),
                                            with_payload=["evidence_id", "kind", "text"]))
            for h in hits:
                ev_id = h.payload["evidence_id"]
                if ev_id in candidates:
                    continue  # results are sorted, the first hit is the max
                candidates[ev_id] = {"evidence_id": ev_id, "dense_score": float(h.score),
                                     "matched_chunk": h.payload.get("text", ""),
                                     "matched_kind": h.payload.get("kind", ""), "bm25_score": 0.0}
                if len(candidates) >= limit:
                    break

        if sparse_vector is not None and len(sparse_vector.indices) > 0:
            hits = shard.query(QueryRequest(limit=limit, query=Query.Nearest(sparse_vector, using=SPARSE),
                                            with_payload=["evidence_id"]))
            for h in hits:
                ev_id = h.payload["evidence_id"]
                cand = candidates.setdefault(ev_id, {"evidence_id": ev_id, "dense_score": 0.0,
                                                     "matched_chunk": "", "matched_kind": ""})
                cand["bm25_score"] = float(h.score)

        out = []
        for ev_id, cand in candidates.items():
            item = docs.get(ev_id)
            if item is None:
                continue
            cand.setdefault("bm25_score", 0.0)
            cand["item"] = item
            cand["tier"] = tier
            out.append(cand)
        return out

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        for tier, shard in self.shards.items():
            try:
                stats[tier.value] = {
                    "documents": len(self._docs[tier]),
                    "points_count": shard.count(CountRequest(exact=True)),
                    "status": "ready",
                }
            except Exception as e:
                stats[tier.value] = {"error": str(e), "documents": 0, "points_count": 0}
        stats["engine"] = "qdrant-edge"
        stats["dense_model"] = self.engine.model_id
        return stats


_global_qdrant_manager: Optional[QdrantEdgeManager] = None
_manager_lock = threading.Lock()


def get_qdrant_manager() -> QdrantEdgeManager:
    global _global_qdrant_manager
    with _manager_lock:
        if _global_qdrant_manager is None:
            _global_qdrant_manager = QdrantEdgeManager()
        return _global_qdrant_manager


def reset_qdrant_manager():
    """Closes and forgets the global manager (used by tests and shutdown)."""
    global _global_qdrant_manager
    with _manager_lock:
        if _global_qdrant_manager is not None:
            _global_qdrant_manager.close()
        _global_qdrant_manager = None
