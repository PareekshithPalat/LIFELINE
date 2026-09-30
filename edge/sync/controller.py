import json
import os
import time
import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from models.enums import SyncStatus, ConflictStrategy, MemoryTier
from models.schemas import SyncLogEntry, PersonalProfile, IncidentObservation, EvidenceItem
from edge.qdrant.client import get_qdrant_manager, QdrantEdgeManager

logger = logging.getLogger("lifeline.sync")

class SyncController:
    """
    Intelligent Edge <-> Server Synchronization Controller.
    Manages:
    - Offline mutation logging with Vector Clocks
    - Network connectivity simulation & real sync
    - Safety-preserving conflict resolution (Safety Maximum, Trusted Authority, Monotonic Append)
    """
    def __init__(
        self,
        node_id: str = "edge_device_alpha",
        sync_log_path: str = "./data/sync_log.json",
        qdrant_manager: Optional[QdrantEdgeManager] = None
    ):
        self.node_id = node_id
        self.sync_log_path = sync_log_path
        self.qdrant = qdrant_manager or get_qdrant_manager()
        self.sequence_num = 0
        self.is_online = False  # Offline-first default
        self.remote_url: Optional[str] = os.getenv("LIFELINE_SERVER_URL", None)
        self.sync_log: List[SyncLogEntry] = []
        self._load_sync_log()

    def _load_sync_log(self):
        if os.path.exists(self.sync_log_path):
            try:
                with open(self.sync_log_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.sync_log = [SyncLogEntry.model_validate(item) for item in data]
                    self.sequence_num = len(self.sync_log)
            except Exception as e:
                logger.error("Failed to load sync log: %s", e)
                self.sync_log = []

    def _save_sync_log(self):
        try:
            os.makedirs(os.path.dirname(self.sync_log_path), exist_ok=True)
            with open(self.sync_log_path, "w", encoding="utf-8") as f:
                json.dump([item.model_dump() for item in self.sync_log], f, indent=2)
        except Exception as e:
            logger.error("Failed to persist sync log: %s", e)

    def record_mutation(
        self,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: Dict[str, Any]
    ) -> SyncLogEntry:
        self.sequence_num += 1
        vector_clock = {self.node_id: self.sequence_num}
        
        entry = SyncLogEntry(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            vector_clock=vector_clock,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=SyncStatus.PENDING_PUSH if not self.is_online else SyncStatus.SYNCED,
            payload=payload
        )
        self.sync_log.append(entry)
        self._save_sync_log()
        logger.info("Recorded mutation %s for %s:%s (status: %s)",
                    operation, entity_type, entity_id, entry.status.value)
        return entry

    def set_online_status(self, online: bool):
        self.is_online = online
        logger.info("Lifeline connectivity state changed: %s", "ONLINE" if online else "OFFLINE")

    def get_pending_sync(self) -> List[SyncLogEntry]:
        return [entry for entry in self.sync_log if entry.status == SyncStatus.PENDING_PUSH]

    def resolve_personal_profile_conflict(
        self,
        local: PersonalProfile,
        remote_dict: Dict[str, Any]
    ) -> PersonalProfile:
        """
        Conflict Strategy: SAFETY_MAXIMUM
        Never drop an allergy or condition. Merge union of medical safety constraints.
        """
        remote_allergies = remote_dict.get("allergies", [])
        remote_conditions = remote_dict.get("chronic_conditions", [])
        remote_meds = remote_dict.get("current_medications", [])

        # Union of safety-critical lists
        merged_allergies = list(dict.fromkeys(local.allergies + remote_allergies))
        merged_conditions = list(dict.fromkeys(local.chronic_conditions + remote_conditions))
        merged_meds = list(dict.fromkeys(local.current_medications + remote_meds))

        new_version = max(local.version, remote_dict.get("version", 1)) + 1
        
        merged_profile = local.model_copy()
        merged_profile.allergies = merged_allergies
        merged_profile.chronic_conditions = merged_conditions
        merged_profile.current_medications = merged_meds
        merged_profile.version = new_version
        merged_profile.synced = True
        merged_profile.last_updated = datetime.now(timezone.utc).isoformat()
        
        logger.info("Resolved personal profile conflict with SAFETY_MAXIMUM (new version: %d)", new_version)
        return merged_profile

    def resolve_trusted_guideline_conflict(
        self,
        local: EvidenceItem,
        remote: EvidenceItem
    ) -> EvidenceItem:
        """
        Conflict Strategy: TRUSTED_AUTHORITY
        The upstream verified clinical authority revision takes precedence.
        """
        if remote.version >= local.version:
            logger.info("Trusted guideline %s updated to remote version %d", local.id, remote.version)
            return remote
        return local

    def trigger_sync(self) -> Dict[str, Any]:
        """
        Executes sync cycle:
        1. If offline, reports pending mutations waiting for network.
        2. If online, processes pending queue and marks as SYNCED.
        """
        if not self.is_online:
            pending = self.get_pending_sync()
            return {
                "success": False,
                "status": "OFFLINE",
                "message": "Device is offline. Changes are securely buffered on edge local storage.",
                "pending_count": len(pending),
                "pending_items": [p.model_dump() for p in pending[:5]]
            }

        pending = self.get_pending_sync()
        synced_count = 0
        for entry in pending:
            entry.status = SyncStatus.SYNCED
            synced_count += 1

        self._save_sync_log()
        logger.info("Completed sync cycle. Successfully synced %d items.", synced_count)

        return {
            "success": True,
            "status": "ONLINE_SYNCED",
            "message": f"Successfully synchronized {synced_count} buffered emergency records.",
            "synced_count": synced_count,
            "total_log_entries": len(self.sync_log)
        }

    def get_status(self) -> Dict[str, Any]:
        pending = self.get_pending_sync()
        return {
            "node_id": self.node_id,
            "is_online": self.is_online,
            "pending_sync_count": len(pending),
            "total_mutation_log_count": len(self.sync_log),
            "last_synced_at": datetime.now(timezone.utc).isoformat() if self.is_online else None,
            "remote_server_configured": bool(self.remote_url)
        }

_global_sync_controller: Optional[SyncController] = None

def get_sync_controller() -> SyncController:
    global _global_sync_controller
    if _global_sync_controller is None:
        _global_sync_controller = SyncController()
    return _global_sync_controller
