import logging
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    VectorParams,
    Distance,
    SparseVectorParams,
    PointStruct,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
    PayloadSchemaType
)
from models.enums import MemoryTier, RiskLevel
from models.schemas import EvidenceItem, compute_evidence_hash
from edge.embeddings.engine import get_embedding_engine

logger = logging.getLogger("lifeline.qdrant")

COLLECTIONS = {
    MemoryTier.TRUSTED: "lifeline_trusted_memory",
    MemoryTier.PERSONAL: "lifeline_personal_memory",
    MemoryTier.INCIDENT: "lifeline_incident_memory"
}

def id_to_uuid(raw_id: str) -> str:
    """Converts any string ID deterministically to standard UUID string required by Qdrant."""
    try:
        # Check if already a valid UUID
        return str(uuid.UUID(raw_id))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))

class QdrantEdgeManager:
    """
    Manages local Qdrant Edge instance with multi-vector collections:
    - Dense vector (384-d, Cosine)
    - Sparse BM25 vector
    - Rich metadata payloads and indexing
    """
    def __init__(self, storage_path: str = "./data/qdrant_storage", memory_mode: bool = False):
        self.storage_path = storage_path
        self.memory_mode = memory_mode
        self._init_client()
        self.init_collections()

    def _init_client(self):
        if self.memory_mode:
            logger.info("Initializing Qdrant Edge in-memory mode")
            self.client = QdrantClient(location=":memory:")
        else:
            logger.info("Initializing Qdrant Edge on-disk mode at: %s", self.storage_path)
            self.client = QdrantClient(path=self.storage_path)

    def init_collections(self):
        """Ensures all three memory tier collections exist with dense + sparse vector configs."""
        for tier, col_name in COLLECTIONS.items():
            try:
                collections = self.client.get_collections().collections
                col_names = [c.name for c in collections]
                if col_name not in col_names:
                    logger.info("Creating Qdrant collection: %s (%s)", col_name, tier.value)
                    self.client.create_collection(
                        collection_name=col_name,
                        vectors_config={
                            "dense": VectorParams(size=384, distance=Distance.COSINE)
                        },
                        sparse_vectors_config={
                            "sparse": SparseVectorParams()
                        }
                    )
                    # Local embedded Qdrant does not need explicit payload indexes
                    if not self.memory_mode and not self.storage_path:
                        try:
                            self.client.create_payload_index(
                                collection_name=col_name,
                                field_name="risk_level",
                                field_schema=PayloadSchemaType.KEYWORD
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.error("Failed to initialize collection %s: %s", col_name, e)

    def upsert_evidence(self, item: EvidenceItem, dense_vector: Optional[List[float]] = None, sparse_vector: Optional[SparseVector] = None) -> bool:
        """Upserts an EvidenceItem into its corresponding memory tier collection."""
        engine = get_embedding_engine()
        col_name = COLLECTIONS.get(item.tier, COLLECTIONS[MemoryTier.TRUSTED])

        combined_text = f"{item.title}\n{item.content}\nTags: {', '.join(item.tags)}"
        if item.contraindications:
            combined_text += f"\nContraindications: {'; '.join(item.contraindications)}"

        if dense_vector is None:
            dense_vector = engine.embed_text(combined_text)

        if sparse_vector is None:
            indices, values = engine.embed_sparse(combined_text)
            sparse_vector = SparseVector(indices=indices, values=values)

        point_id = id_to_uuid(item.id)

        # Update hash if needed
        if not item.hash:
            item.hash = compute_evidence_hash(item.content, item.title, item.version)

        payload = item.model_dump()
        payload["evidence_id"] = item.id  # keep original string ID in payload

        vector_data = {
            "dense": dense_vector
        }
        if len(sparse_vector.indices) > 0:
            vector_data["sparse"] = sparse_vector

        try:
            self.client.upsert(
                collection_name=col_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector_data,
                        payload=payload
                    )
                ]
            )
            return True
        except Exception as e:
            logger.error("Error upserting evidence %s to %s: %s", item.id, col_name, e)
            return False

    def get_evidence(self, tier: MemoryTier, evidence_id: str) -> Optional[EvidenceItem]:
        col_name = COLLECTIONS.get(tier)
        if not col_name:
            return None
        point_id = id_to_uuid(evidence_id)
        try:
            records = self.client.retrieve(
                collection_name=col_name,
                ids=[point_id],
                with_payload=True
            )
            if records:
                p = records[0].payload
                p["id"] = p.get("evidence_id", evidence_id)
                return EvidenceItem.model_validate(p)
        except Exception as e:
            logger.error("Error retrieving evidence %s: %s", evidence_id, e)
        return None

    def list_evidence(self, tier: MemoryTier, limit: int = 100) -> List[EvidenceItem]:
        col_name = COLLECTIONS.get(tier)
        if not col_name:
            return []
        try:
            res, _ = self.client.scroll(
                collection_name=col_name,
                limit=limit,
                with_payload=True
            )
            items = []
            for r in res:
                p = r.payload
                p["id"] = p.get("evidence_id", str(r.id))
                items.append(EvidenceItem.model_validate(p))
            return items
        except Exception as e:
            logger.error("Error listing evidence in %s: %s", col_name, e)
            return []

    def delete_evidence(self, tier: MemoryTier, evidence_id: str) -> bool:
        col_name = COLLECTIONS.get(tier)
        if not col_name:
            return False
        point_id = id_to_uuid(evidence_id)
        try:
            self.client.delete(
                collection_name=col_name,
                points_selector=[point_id]
            )
            return True
        except Exception as e:
            logger.error("Error deleting evidence %s: %s", evidence_id, e)
            return False

    def query_dense(
        self,
        tier: MemoryTier,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: float = 0.0,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        col_name = COLLECTIONS.get(tier)
        if not col_name:
            return []

        q_filter = self._build_filter(filter_dict) if filter_dict else None

        try:
            results = self.client.query_points(
                collection_name=col_name,
                query=query_vector,
                using="dense",
                limit=limit,
                score_threshold=score_threshold if score_threshold > 0 else None,
                query_filter=q_filter,
                with_payload=True
            )
            hits = []
            for pt in results.points:
                hits.append({
                    "id": pt.payload.get("evidence_id", str(pt.id)),
                    "score": pt.score,
                    "payload": pt.payload
                })
            return hits
        except Exception as e:
            logger.error("Error querying dense vectors in %s: %s", col_name, e)
            return []

    def query_sparse(
        self,
        tier: MemoryTier,
        indices: List[int],
        values: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        col_name = COLLECTIONS.get(tier)
        if not col_name or not indices:
            return []

        q_filter = self._build_filter(filter_dict) if filter_dict else None

        try:
            sparse_query = SparseVector(indices=indices, values=values)
            results = self.client.query_points(
                collection_name=col_name,
                query=sparse_query,
                using="sparse",
                limit=limit,
                query_filter=q_filter,
                with_payload=True
            )
            hits = []
            for pt in results.points:
                hits.append({
                    "id": pt.payload.get("evidence_id", str(pt.id)),
                    "score": pt.score,
                    "payload": pt.payload
                })
            return hits
        except Exception as e:
            logger.error("Error querying sparse vectors in %s: %s", col_name, e)
            return []

    def _build_filter(self, filter_dict: Dict[str, Any]) -> Optional[Filter]:
        conditions = []
        for k, v in filter_dict.items():
            if isinstance(v, (str, int, bool)):
                conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
        if conditions:
            return Filter(must=conditions)
        return None

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        for tier, col_name in COLLECTIONS.items():
            try:
                info = self.client.get_collection(collection_name=col_name)
                stats[tier.value] = {
                    "points_count": info.points_count,
                    "status": str(info.status),
                    "vectors_count": getattr(info, "vectors_count", info.points_count)
                }
            except Exception as e:
                stats[tier.value] = {"error": str(e), "points_count": 0}
        return stats

_global_qdrant_manager: Optional[QdrantEdgeManager] = None

def get_qdrant_manager(storage_path: str = "./data/qdrant_storage", memory_mode: bool = False) -> QdrantEdgeManager:
    global _global_qdrant_manager
    if _global_qdrant_manager is None:
        _global_qdrant_manager = QdrantEdgeManager(storage_path=storage_path, memory_mode=memory_mode)
    return _global_qdrant_manager
