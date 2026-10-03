import uuid
import logging
from typing import Optional
from models.enums import MemoryTier
from models.schemas import EvidenceItem, PersonalProfile, IncidentObservation, utc_now
from edge.qdrant.client import get_qdrant_manager
from edge.cache.semantic_cache import get_semantic_cache
from edge.stores import (get_profile_store, get_incident_store, get_trusted_store,
                         profile_to_evidence, observation_to_evidence)

logger = logging.getLogger("lifeline.memory")


def on_evidence_changed(item: EvidenceItem):
    """Single write path into the index: re-embed the item and drop dependent cache entries."""
    get_qdrant_manager().upsert_evidence(item)
    cache = get_semantic_cache()
    if item.tier == MemoryTier.TRUSTED:
        cache.invalidate_evidence(item.id)
    # Profile and incident changes are caught by version binding in the cache;
    # nothing else to do here.


def update_profile(profile: PersonalProfile) -> PersonalProfile:
    from edge.sync.controller import get_sync_controller
    sync = get_sync_controller()
    profile.synced = False
    saved = get_profile_store().save(profile)
    on_evidence_changed(profile_to_evidence(saved))
    sync.record_mutation("personal", saved.user_id, "UPDATE", saved.model_dump(mode="json"))
    return saved


def log_observation(obs: IncidentObservation) -> IncidentObservation:
    from edge.sync.controller import get_sync_controller
    sync = get_sync_controller()
    obs = obs.model_copy(deep=True)
    obs.id = obs.id or f"obs-{uuid.uuid4().hex[:12]}"
    obs.timestamp = utc_now()
    obs.origin_node = sync.node_id
    obs.synced = False
    saved = get_incident_store().append(obs)
    if saved is None:
        raise ValueError(f"Observation {obs.id} already exists (incident log is append-only)")
    on_evidence_changed(observation_to_evidence(saved))
    sync.record_mutation("incident", saved.id, "CREATE", saved.model_dump(mode="json"))
    return saved


def upsert_trusted(item: EvidenceItem) -> Optional[EvidenceItem]:
    """TRUSTED_AUTHORITY: only a strictly newer version replaces a protocol."""
    from edge.sync.controller import get_sync_controller
    item = item.model_copy(deep=True)
    item.tier = MemoryTier.TRUSTED
    item.verified = True
    if not get_trusted_store().put(item):
        return None
    stored = get_trusted_store().get(item.id)
    on_evidence_changed(stored)
    get_sync_controller().record_mutation("trusted", stored.id, "UPSERT", stored.model_dump(mode="json"))
    return stored
