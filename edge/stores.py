import os
import json
import shutil
import threading
import logging
from typing import List, Optional, Dict, Any
from models.enums import MemoryTier, RiskLevel
from models.schemas import EvidenceItem, PersonalProfile, IncidentObservation, utc_now
from edge.config import get_settings, PROJECT_ROOT

logger = logging.getLogger("lifeline.stores")

SEED_TRUSTED = os.path.join(PROJECT_ROOT, "data", "trusted_protocols.json")
SEED_PERSONAL = os.path.join(PROJECT_ROOT, "data", "default_personal.json")


def atomic_write_json(path: str, data: Any):
    """Write-then-rename so a crash or power loss never leaves a half-written file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        logger.error("Unreadable JSON store %s (%s); keeping a backup and starting fresh.", path, e)
        shutil.copy(path, f"{path}.corrupt")
        return default


def profile_to_evidence(profile: PersonalProfile) -> EvidenceItem:
    content = (
        f"Personal Emergency Profile for {profile.full_name}:\n"
        f"Blood Group: {profile.blood_group}\n"
        f"Allergies: {', '.join(profile.allergies) or 'None recorded'}\n"
        f"Current Medications: {', '.join(profile.current_medications) or 'None recorded'}\n"
        f"Chronic Conditions: {', '.join(profile.chronic_conditions) or 'None recorded'}\n"
        f"ICE Instructions: {profile.ice_instructions}\n"
        f"Notes: {profile.medical_notes}"
    )
    return EvidenceItem(
        id=f"profile-{profile.user_id}",
        tier=MemoryTier.PERSONAL,
        title=f"Emergency Profile - {profile.full_name}",
        content=content,
        tags=["profile", "personal", "allergies", "blood group", "medications", "ice"],
        risk_level=RiskLevel.HIGH,
        author="user_personal_vault",
        version=profile.version,
        updated_at=profile.last_updated,
    )


def observation_to_evidence(obs: IncidentObservation) -> EvidenceItem:
    vitals = ", ".join(f"{k}: {v}" for k, v in obs.vital_signs.items()) or "None"
    content = (
        f"Incident Observation [{obs.severity.value}] at {obs.timestamp}:\n"
        f"Vitals: {vitals}\n"
        f"Observed Symptoms: {', '.join(obs.observed_symptoms) or 'None'}\n"
        f"Actions Taken On-Scene: {', '.join(obs.actions_taken) or 'None'}\n"
        f"Reporter: {obs.reporter}"
    )
    return EvidenceItem(
        id=obs.id,
        tier=MemoryTier.INCIDENT,
        title=f"Incident {obs.incident_id} - Observation #{obs.version}",
        content=content,
        tags=["incident", "timeline", "observation", "vitals"],
        risk_level=obs.severity,
        author=obs.reporter,
        version=obs.version,
        created_at=obs.timestamp,
        metadata={"incident_id": obs.incident_id},
    )


class ProfileStore:
    """The patient's personal vault. Seeded once from data/default_personal.json."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(get_settings().runtime_path, "personal_profile.json")
        self._lock = threading.RLock()
        self._profile: Optional[PersonalProfile] = None

    def get(self) -> PersonalProfile:
        with self._lock:
            if self._profile is None:
                data = read_json(self.path, None)
                if data is None:
                    data = read_json(SEED_PERSONAL, None)
                    if data is not None:
                        atomic_write_json(self.path, data)
                self._profile = (PersonalProfile.model_validate(data) if data
                                 else PersonalProfile(full_name="Emergency Patient", blood_group="Unknown"))
            return self._profile.model_copy(deep=True)

    def save(self, profile: PersonalProfile, bump_version: bool = True) -> PersonalProfile:
        """Persists a profile. The version is always derived from the stored one so a
        stale client copy can never move it backwards."""
        with self._lock:
            current = self.get()
            profile = profile.model_copy(deep=True)
            if bump_version:
                profile.version = max(current.version, profile.version) + 1
                profile.last_updated = utc_now()
            atomic_write_json(self.path, profile.model_dump(mode="json"))
            self._profile = profile
            return profile.model_copy(deep=True)


class IncidentStore:
    """Append-only on-scene observation log, versioned per incident."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(get_settings().runtime_path, "incidents.json")
        self._lock = threading.RLock()
        self._items: Optional[List[IncidentObservation]] = None

    def _load(self) -> List[IncidentObservation]:
        if self._items is None:
            self._items = [IncidentObservation.model_validate(x) for x in read_json(self.path, [])]
        return self._items

    def list(self, incident_id: Optional[str] = None) -> List[IncidentObservation]:
        with self._lock:
            items = [o for o in self._load() if incident_id is None or o.incident_id == incident_id]
            return sorted(items, key=lambda o: o.timestamp, reverse=True)

    def version(self, incident_id: str) -> int:
        """Monotonic version of an incident timeline = number of observations."""
        with self._lock:
            return sum(1 for o in self._load() if o.incident_id == incident_id)

    def has(self, obs_id: str) -> bool:
        with self._lock:
            return any(o.id == obs_id for o in self._load())

    def append(self, obs: IncidentObservation) -> Optional[IncidentObservation]:
        """MONOTONIC_APPEND: never edits or removes; duplicate ids are ignored."""
        with self._lock:
            items = self._load()
            if any(o.id == obs.id for o in items):
                return None
            obs = obs.model_copy(deep=True)
            obs.version = self.version(obs.incident_id) + 1
            items.append(obs)
            atomic_write_json(self.path, [o.model_dump(mode="json") for o in items])
            return obs


class TrustedStore:
    """
    Clinical protocols. The repository seed is merged with runtime revisions using
    TRUSTED_AUTHORITY (a higher version always wins), so shipping a newer seed file
    upgrades devices while signed-off runtime revisions are kept.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(get_settings().runtime_path, "trusted_protocols.json")
        self._lock = threading.RLock()
        self._items: Optional[Dict[str, EvidenceItem]] = None

    def _load(self) -> Dict[str, EvidenceItem]:
        if self._items is None:
            items: Dict[str, EvidenceItem] = {}
            for raw in read_json(SEED_TRUSTED, []):
                item = EvidenceItem.model_validate(raw).rehash()
                items[item.id] = item
            changed = False
            for raw in read_json(self.path, []):
                item = EvidenceItem.model_validate(raw).rehash()
                seed = items.get(item.id)
                if seed is None or item.version > seed.version:
                    items[item.id] = item
                elif seed is not None and seed.version > item.version:
                    changed = True  # newer seed shipped; runtime copy is outdated
            self._items = items
            if changed or not os.path.exists(self.path):
                self._persist()
        return self._items

    def _persist(self):
        atomic_write_json(self.path, [i.model_dump(mode="json") for i in self._items.values()])

    def all(self) -> List[EvidenceItem]:
        with self._lock:
            return list(self._load().values())

    def get(self, evidence_id: str) -> Optional[EvidenceItem]:
        with self._lock:
            return self._load().get(evidence_id)

    def put(self, item: EvidenceItem) -> bool:
        """Applies TRUSTED_AUTHORITY. Returns False when the revision is not newer."""
        with self._lock:
            items = self._load()
            current = items.get(item.id)
            if current is not None and item.version <= current.version:
                return False
            item = item.model_copy(deep=True)
            item.tier = MemoryTier.TRUSTED
            item.updated_at = utc_now()
            item.rehash()
            items[item.id] = item
            self._persist()
            return True


_profile_store: Optional[ProfileStore] = None
_incident_store: Optional[IncidentStore] = None
_trusted_store: Optional[TrustedStore] = None
_lock = threading.Lock()


def get_profile_store() -> ProfileStore:
    global _profile_store
    with _lock:
        if _profile_store is None:
            _profile_store = ProfileStore()
        return _profile_store


def get_incident_store() -> IncidentStore:
    global _incident_store
    with _lock:
        if _incident_store is None:
            _incident_store = IncidentStore()
        return _incident_store


def get_trusted_store() -> TrustedStore:
    global _trusted_store
    with _lock:
        if _trusted_store is None:
            _trusted_store = TrustedStore()
        return _trusted_store


def reset_stores():
    global _profile_store, _incident_store, _trusted_store
    with _lock:
        _profile_store = _incident_store = _trusted_store = None
