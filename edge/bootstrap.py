import logging
from models.enums import MemoryTier
from edge.qdrant.client import get_qdrant_manager
from edge.stores import (get_trusted_store, get_profile_store, get_incident_store,
                         profile_to_evidence, observation_to_evidence)

logger = logging.getLogger("lifeline.bootstrap")


def ensure_indexed() -> dict:
    """
    Reconciles the Qdrant Edge index with the source-of-truth stores. Only items
    whose content hash changed are re-embedded, so a warm start is near-instant.
    """
    qdrant = get_qdrant_manager()
    report = {"trusted_indexed": 0, "trusted_removed": 0, "personal_indexed": 0, "incident_indexed": 0}

    trusted = {i.id: i for i in get_trusted_store().all()}
    stale = [i for i in trusted.values()
             if (cur := qdrant.get_evidence(MemoryTier.TRUSTED, i.id)) is None or cur.hash != i.hash
             or cur.triggers != i.triggers or cur.metadata != i.metadata]
    report["trusted_indexed"] = qdrant.upsert_many(stale)
    for item in qdrant.list_evidence(MemoryTier.TRUSTED):
        if item.id not in trusted and qdrant.delete_evidence(MemoryTier.TRUSTED, item.id):
            report["trusted_removed"] += 1

    profile_item = profile_to_evidence(get_profile_store().get())
    cur = qdrant.get_evidence(MemoryTier.PERSONAL, profile_item.id)
    if cur is None or cur.hash != profile_item.hash:
        report["personal_indexed"] = qdrant.upsert_many([profile_item])

    missing = [observation_to_evidence(o) for o in get_incident_store().list()
               if qdrant.get_evidence(MemoryTier.INCIDENT, o.id) is None]
    report["incident_indexed"] = qdrant.upsert_many(missing)

    logger.info("Index reconciled: %s", report)
    return report


def shutdown():
    """Flushes and closes the shards and drops every singleton that references them."""
    from edge.qdrant.client import reset_qdrant_manager
    from edge.retrieval.hybrid import reset_hybrid_retriever
    from edge.cache.semantic_cache import reset_semantic_cache
    from edge.runtime.pipeline import reset_pipeline
    reset_pipeline()
    reset_hybrid_retriever()
    reset_semantic_cache()
    reset_qdrant_manager()
