import pytest
from edge.sync.controller import SyncController
from models.schemas import PersonalProfile, EvidenceItem
from models.enums import SyncStatus, MemoryTier

def test_sync_offline_mutation_logging(tmp_path):
    log_path = str(tmp_path / "sync_log.json")
    sync = SyncController(sync_log_path=log_path)
    sync.set_online_status(False)

    mutation = sync.record_mutation(
        entity_type="personal",
        entity_id="profile-01",
        operation="UPDATE",
        payload={"allergies": ["Penicillin"]}
    )
    assert mutation.status == SyncStatus.PENDING_PUSH
    assert mutation.vector_clock.get(sync.node_id) == 1
    assert len(sync.get_pending_sync()) == 1

def test_safety_maximum_profile_conflict_resolution(tmp_path):
    log_path = str(tmp_path / "sync_log.json")
    sync = SyncController(sync_log_path=log_path)

    local_profile = PersonalProfile(
        full_name="Alice Smith",
        blood_group="A+",
        allergies=["Penicillin"],
        chronic_conditions=["Asthma"],
        version=1
    )
    remote_dict = {
        "allergies": ["Aspirin", "Penicillin"],
        "chronic_conditions": ["Hypertension"],
        "current_medications": ["Lisinopril"],
        "version": 2
    }

    merged = sync.resolve_personal_profile_conflict(local_profile, remote_dict)
    # SAFETY_MAXIMUM guarantees neither allergy is lost
    assert "Penicillin" in merged.allergies
    assert "Aspirin" in merged.allergies
    assert "Asthma" in merged.chronic_conditions
    assert "Hypertension" in merged.chronic_conditions
    assert merged.version >= 3
