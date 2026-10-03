import os
import uuid
import threading
from datetime import datetime, timezone
import logging
from typing import Dict, Any, List, Optional, Tuple
import httpx
from models.enums import SyncStatus
from models.schemas import SyncLogEntry, PersonalProfile, IncidentObservation, EvidenceItem, utc_now
from edge.config import get_settings
from edge.stores import (atomic_write_json, read_json, get_profile_store, get_incident_store, get_trusted_store,
                         profile_to_evidence, observation_to_evidence)

logger = logging.getLogger("lifeline.sync")

SAFETY_LIST_FIELDS = ("allergies", "chronic_conditions", "current_medications")


def _union(a: List[str], b: List[str]) -> List[str]:
    seen, out = set(), []
    for x in a + b:
        key = x.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(x.strip())
    return out


def _ts(value: str) -> datetime:
    """Parses ISO timestamps from any node (Python '+00:00' or Dart 'Z' style)."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def merge_profiles(local: PersonalProfile, remote: PersonalProfile) -> PersonalProfile:
    """
    SAFETY_MAXIMUM: allergies, conditions and medications are unioned so no safety
    constraint is ever lost; contacts are unioned by phone number; descriptive fields
    come from whichever side was edited most recently.
    """
    newer, older = (remote, local) if _ts(remote.last_updated) > _ts(local.last_updated) else (local, remote)
    merged = newer.model_copy(deep=True)
    for f in SAFETY_LIST_FIELDS:
        setattr(merged, f, _union(getattr(newer, f), getattr(older, f)))
    phones = {c.phone for c in newer.emergency_contacts}
    merged.emergency_contacts = newer.emergency_contacts + [c for c in older.emergency_contacts
                                                            if c.phone not in phones]
    merged.version = max(local.version, remote.version)
    return merged


def safety_fields_equal(a: PersonalProfile, b: PersonalProfile) -> bool:
    norm = lambda xs: sorted(x.strip().lower() for x in xs)
    return all(norm(getattr(a, f)) == norm(getattr(b, f)) for f in SAFETY_LIST_FIELDS)


class SyncController:
    """
    Offline-first replication of the mutation log.

    * Every local change is appended to a durable log as PENDING_PUSH.
    * trigger_sync() pushes pending entries to the upstream hub (LIFELINE_SERVER_URL)
      and pulls entries other nodes produced, applying the conflict strategies:
        personal -> SAFETY_MAXIMUM, trusted -> TRUSTED_AUTHORITY, incident -> MONOTONIC_APPEND
    * Every node can also act as a hub (hub_receive / hub_entries_since), which is how
      the mobile app syncs with this API.
    """

    def __init__(self, node_id: Optional[str] = None, sync_log_path: Optional[str] = None,
                 server_url: Optional[str] = None, on_change=None):
        s = get_settings()
        self.node_id = node_id or s.node_id
        self.sync_log_path = sync_log_path or os.path.join(s.runtime_path, "sync_log.json")
        self.state_path = os.path.join(os.path.dirname(self.sync_log_path), "sync_state.json")
        self.remote_url = (server_url if server_url is not None else s.server_url) or None
        self.remote_api_key = s.server_api_key
        # Hook used to re-index and invalidate the cache after remote changes are applied.
        self.on_change = on_change
        self._lock = threading.RLock()
        self.sync_log: List[SyncLogEntry] = [SyncLogEntry.model_validate(x)
                                             for x in read_json(self.sync_log_path, [])]
        state = read_json(self.state_path, {})
        self.sequence_num = max([state.get("seq", 0)] + [e.seq for e in self.sync_log])
        self.origin_seq = state.get("origin_seq", sum(1 for e in self.sync_log if e.origin_node == self.node_id))
        self.last_pulled_seq = state.get("last_pulled_seq", 0)
        self.last_synced_at: Optional[str] = state.get("last_synced_at")
        self.last_error: Optional[str] = None
        # Manual network switch ("airplane mode" for drills); real reachability is
        # detected on each sync attempt.
        self.is_online = state.get("is_online", bool(self.remote_url))
        self._ids = {e.id for e in self.sync_log}

    # ------------------------------------------------------------------ persistence
    def _save(self):
        atomic_write_json(self.sync_log_path, [e.model_dump(mode="json") for e in self.sync_log])
        atomic_write_json(self.state_path, {
            "seq": self.sequence_num, "origin_seq": self.origin_seq, "last_pulled_seq": self.last_pulled_seq,
            "last_synced_at": self.last_synced_at, "is_online": self.is_online,
        })

    def _append(self, entry: SyncLogEntry):
        self.sequence_num += 1
        entry.seq = self.sequence_num
        self.sync_log.append(entry)
        self._ids.add(entry.id)

    # ------------------------------------------------------------------ local writes
    def record_mutation(self, entity_type: str, entity_id: str, operation: str,
                        payload: Dict[str, Any]) -> SyncLogEntry:
        with self._lock:
            self.origin_seq += 1
            entry = SyncLogEntry(
                id=str(uuid.uuid4()), entity_type=entity_type, entity_id=entity_id, operation=operation,
                origin_node=self.node_id, vector_clock={self.node_id: self.origin_seq},
                status=SyncStatus.PENDING_PUSH, payload=payload,
            )
            self._append(entry)
            self._save()
            logger.info("Recorded %s %s:%s (seq %d)", operation, entity_type, entity_id, entry.seq)
            return entry

    def set_online_status(self, online: bool):
        with self._lock:
            self.is_online = online
            self._save()
        logger.info("Network mode: %s", "ONLINE" if online else "OFFLINE")

    def get_pending_sync(self) -> List[SyncLogEntry]:
        with self._lock:
            return [e for e in self.sync_log if e.status == SyncStatus.PENDING_PUSH]

    # ------------------------------------------------------------------ applying remote changes
    def apply_entry(self, entry: SyncLogEntry, from_downstream: bool) -> Tuple[bool, Optional[SyncLogEntry]]:
        """
        Applies one remote entry to the local stores. Returns (applied, rebroadcast)
        where rebroadcast is a new local entry the hub must publish because merging
        changed the data (e.g. the hub knew an allergy the pushing node did not).
        """
        kind = entry.entity_type
        if kind == "personal":
            remote = PersonalProfile.model_validate(entry.payload)
            store = get_profile_store()
            local = store.get()
            merged = merge_profiles(local, remote)
            if (merged.model_dump(exclude={"version", "last_updated", "synced"})
                    == local.model_dump(exclude={"version", "last_updated", "synced"})):
                return False, None
            merged.synced = True
            saved = store.save(merged)
            self._notify(profile_to_evidence(saved))
            rebroadcast = None
            if from_downstream and not safety_fields_equal(saved, remote):
                rebroadcast = self._new_entry("personal", saved.user_id, "MERGE", saved.model_dump(mode="json"))
            return True, rebroadcast
        if kind == "trusted":
            if from_downstream:
                logger.warning("Rejected trusted protocol %s pushed by node %s: trusted memory only flows "
                               "down from the hub.", entry.entity_id, entry.origin_node)
                return False, None
            item = EvidenceItem.model_validate(entry.payload)
            if get_trusted_store().put(item):
                self._notify(get_trusted_store().get(item.id))
                return True, None
            return False, None
        if kind == "incident":
            obs = IncidentObservation.model_validate(entry.payload)
            obs.synced = True
            saved = get_incident_store().append(obs)
            if saved is not None:
                self._notify(observation_to_evidence(saved))
                return True, None
            return False, None
        if kind == "media":
            return True, None
        logger.warning("Unknown entity type in sync entry: %s", kind)
        return False, None

    def _new_entry(self, entity_type, entity_id, operation, payload) -> SyncLogEntry:
        self.origin_seq += 1
        return SyncLogEntry(id=str(uuid.uuid4()), entity_type=entity_type, entity_id=entity_id,
                            operation=operation, origin_node=self.node_id,
                            vector_clock={self.node_id: self.origin_seq},
                            status=SyncStatus.PENDING_PUSH, payload=payload)

    def _notify(self, item: Optional[EvidenceItem]):
        if item is not None and self.on_change:
            try:
                self.on_change(item)
            except Exception as e:
                logger.error("Re-index after sync failed for %s: %s", item.id, e)

    # ------------------------------------------------------------------ hub role
    def hub_receive(self, node_id: str, entries: List[SyncLogEntry]) -> Dict[str, Any]:
        accepted, applied = [], 0
        with self._lock:
            for entry in entries:
                if entry.id in self._ids:
                    accepted.append(entry.id)  # idempotent re-push after a lost ack
                    continue
                entry = entry.model_copy(deep=True)
                entry.origin_node = entry.origin_node or node_id
                ok, rebroadcast = self.apply_entry(entry, from_downstream=True)
                applied += int(ok)
                entry.status = SyncStatus.PENDING_PUSH if self.remote_url else SyncStatus.SYNCED
                self._append(entry)
                if rebroadcast is not None:
                    self._append(rebroadcast)
                accepted.append(entry.id)
            self._save()
        return {"accepted_ids": accepted, "applied": applied, "hub_seq": self.sequence_num,
                "hub_node_id": self.node_id}

    def hub_entries_since(self, node_id: str, since: int, limit: int = 500) -> Dict[str, Any]:
        """Entries after `since` that the caller did not originate, plus the next cursor."""
        with self._lock:
            out, cursor = [], max(since, 0)
            for e in self.sync_log:
                if e.seq <= since:
                    continue
                if len(out) >= limit:
                    break
                cursor = e.seq
                if e.origin_node != node_id:
                    out.append(e)
            return {"entries": [e.model_dump(mode="json") for e in out], "cursor": cursor,
                    "hub_seq": self.sequence_num, "hub_node_id": self.node_id,
                    "more": cursor < self.sequence_num}

    # ------------------------------------------------------------------ client role
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.remote_api_key} if self.remote_api_key else {}

    def trigger_sync(self) -> Dict[str, Any]:
        pending = self.get_pending_sync()
        if not self.remote_url:
            return {"success": False, "status": "NO_UPSTREAM", "pending_count": len(pending),
                    "message": "No upstream hub configured (LIFELINE_SERVER_URL). Changes stay on this device."}
        if not self.is_online:
            return {"success": False, "status": "OFFLINE", "pending_count": len(pending),
                    "message": "Device is offline. Changes are buffered on local storage.",
                    "pending_items": [p.model_dump(mode="json") for p in pending[:5]]}
        base = self.remote_url.rstrip("/")
        pushed = pulled = 0
        try:
            with httpx.Client(timeout=10.0, headers=self._headers()) as client:
                if pending:
                    res = client.post(f"{base}/api/sync/hub/push", json={
                        "node_id": self.node_id, "entries": [p.model_dump(mode="json") for p in pending]})
                    res.raise_for_status()
                    acked = set(res.json().get("accepted_ids", []))
                    with self._lock:
                        for e in pending:
                            if e.id in acked:
                                e.status = SyncStatus.SYNCED
                                pushed += 1
                        self._save()
                more = True
                while more:
                    res = client.get(f"{base}/api/sync/hub/pull",
                                     params={"node_id": self.node_id, "since": self.last_pulled_seq})
                    res.raise_for_status()
                    body = res.json()
                    with self._lock:
                        for raw in body.get("entries", []):
                            entry = SyncLogEntry.model_validate(raw)
                            if entry.id in self._ids:
                                continue
                            ok, _ = self.apply_entry(entry, from_downstream=False)
                            pulled += int(ok)
                            entry.status = SyncStatus.SYNCED
                            self._append(entry)
                        self.last_pulled_seq = body.get("cursor", self.last_pulled_seq)
                        self._save()
                    more = bool(body.get("more"))
        except Exception as e:
            self.last_error = str(e)
            logger.warning("Sync with %s failed: %s", base, e)
            return {"success": False, "status": "UNREACHABLE", "pending_count": len(self.get_pending_sync()),
                    "message": f"Upstream hub unreachable; changes remain buffered. ({e.__class__.__name__})"}

        with self._lock:
            self.last_synced_at = utc_now()
            self.last_error = None
            self._save()
        return {"success": True, "status": "ONLINE_SYNCED", "pushed": pushed, "pulled": pulled,
                "message": f"Pushed {pushed} and applied {pulled} change(s).",
                "pending_count": len(self.get_pending_sync()), "total_log_entries": len(self.sync_log)}

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "node_id": self.node_id,
                "is_online": self.is_online,
                "pending_sync_count": sum(1 for e in self.sync_log if e.status == SyncStatus.PENDING_PUSH),
                "total_mutation_log_count": len(self.sync_log),
                "last_synced_at": self.last_synced_at,
                "last_error": self.last_error,
                "remote_server_configured": bool(self.remote_url),
                "remote_server_url": self.remote_url,
                "hub_seq": self.sequence_num,
            }


_global_sync_controller: Optional[SyncController] = None
_lock = threading.Lock()


def get_sync_controller() -> SyncController:
    global _global_sync_controller
    with _lock:
        if _global_sync_controller is None:
            from edge.memory_service import on_evidence_changed
            _global_sync_controller = SyncController(on_change=on_evidence_changed)
        return _global_sync_controller


def reset_sync_controller():
    global _global_sync_controller
    with _lock:
        _global_sync_controller = None
