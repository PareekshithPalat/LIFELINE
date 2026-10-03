import os
import sys
import socket
import tempfile
import subprocess
import time
import httpx
import pytest
from models.enums import SyncStatus
from models.schemas import PersonalProfile, IncidentObservation, EmergencyContact
from edge.sync import controller as sync_mod
from edge.sync.controller import SyncController, merge_profiles

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_offline_mutations_are_buffered(tmp_path):
    sync = SyncController(node_id="n1", sync_log_path=str(tmp_path / "log.json"), server_url="http://hub.invalid")
    sync.set_online_status(False)
    entry = sync.record_mutation("personal", "p", "UPDATE", {"allergies": ["Penicillin"]})
    assert entry.status == SyncStatus.PENDING_PUSH and entry.vector_clock == {"n1": 1}
    res = sync.trigger_sync()
    assert res["status"] == "OFFLINE" and res["pending_count"] == 1
    # Durable across restarts
    again = SyncController(node_id="n1", sync_log_path=str(tmp_path / "log.json"), server_url="http://hub.invalid")
    assert len(again.get_pending_sync()) == 1 and again.origin_seq == 1


def test_unreachable_hub_keeps_changes(tmp_path):
    sync = SyncController(node_id="n1", sync_log_path=str(tmp_path / "log.json"), server_url="http://127.0.0.1:9")
    sync.set_online_status(True)
    sync.record_mutation("media", "m", "UPLOAD", {})
    res = sync.trigger_sync()
    assert res["status"] == "UNREACHABLE" and res["pending_count"] == 1


def test_safety_maximum_merge_never_drops_constraints():
    local = PersonalProfile(full_name="Alice", blood_group="A+", allergies=["Penicillin"],
                            chronic_conditions=["Asthma"], version=3, last_updated="2026-01-01T00:00:00+00:00",
                            emergency_contacts=[EmergencyContact(name="Bob", relationship="x", phone="1")])
    remote = PersonalProfile(full_name="Alice Smith", blood_group="A+", allergies=["Aspirin", "penicillin"],
                             chronic_conditions=["Hypertension"], current_medications=["Lisinopril"], version=2,
                             last_updated="2026-02-01T00:00:00+00:00",
                             emergency_contacts=[EmergencyContact(name="Carol", relationship="y", phone="2")])
    merged = merge_profiles(local, remote)
    assert merged.allergies == ["Aspirin", "penicillin"] or set(a.lower() for a in merged.allergies) == {
        "aspirin", "penicillin"}
    assert {"Asthma", "Hypertension"} <= set(merged.chronic_conditions)
    assert merged.full_name == "Alice Smith"  # newer descriptive fields win
    assert {c.phone for c in merged.emergency_contacts} == {"1", "2"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def hub():
    """A second, completely separate Lifeline node acting as the upstream hub."""
    port = _free_port()
    env = {**os.environ, "QDRANT_MEMORY_MODE": "true", "LIFELINE_RUNTIME_DIR": tempfile.mkdtemp(),
           "LIFELINE_NODE_ID": "hub_node", "LIFELINE_ADMIN_KEY": "hub-admin", "PYTHONPATH": ROOT}
    env.pop("LIFELINE_SERVER_URL", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "apps.api.main:app", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/api/system/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("hub did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=20)


@pytest.fixture()
def node(hub, indexed, tmp_path):
    from edge.memory_service import on_evidence_changed
    previous = sync_mod._global_sync_controller
    sync_mod._global_sync_controller = SyncController(
        node_id="phone_a", sync_log_path=str(tmp_path / "log.json"), server_url=hub, on_change=on_evidence_changed)
    sync_mod._global_sync_controller.set_online_status(True)
    yield sync_mod._global_sync_controller
    sync_mod._global_sync_controller = previous


def test_two_node_replication_end_to_end(hub, node):
    from edge import memory_service
    from edge.stores import get_profile_store, get_trusted_store

    # 1. Node -> hub: an on-scene observation recorded offline-first, then pushed.
    obs = memory_service.log_observation(IncidentObservation(incident_id="sync-e2e", vital_signs={"spo2": 91}))
    res = node.trigger_sync()
    assert res["status"] == "ONLINE_SYNCED" and res["pushed"] >= 1 and res["pending_count"] == 0
    hub_obs = httpx.get(f"{hub}/api/memory/incident", params={"incident_id": "sync-e2e"}).json()
    assert [o["id"] for o in hub_obs] == [obs.id]

    # 2. Hub -> node: a new allergy entered on the hub reaches the device...
    hub_profile = httpx.get(f"{hub}/api/memory/personal").json()
    hub_profile["allergies"].append("Latex")
    httpx.put(f"{hub}/api/memory/personal", json=hub_profile).raise_for_status()
    # ...while the device independently adds a different one (concurrent edit).
    local = get_profile_store().get()
    local.allergies.append("Shellfish")
    memory_service.update_profile(local)
    res = node.trigger_sync()
    assert res["status"] == "ONLINE_SYNCED"
    node_allergies = {a.lower() for a in get_profile_store().get().allergies}
    assert {"latex", "shellfish"} <= node_allergies          # SAFETY_MAXIMUM on the device
    hub_allergies = {a.lower() for a in httpx.get(f"{hub}/api/memory/personal").json()["allergies"]}
    assert {"latex", "shellfish"} <= hub_allergies           # ...and on the hub

    # 3. Trusted protocol revision published on the hub flows down (TRUSTED_AUTHORITY).
    proto = next(p for p in httpx.get(f"{hub}/api/memory/trusted").json() if p["id"] == "seizure-convulsion-01")
    proto["version"] += 5
    proto["content"] += "\nStep 7: Hub revision marker."
    httpx.post(f"{hub}/api/memory/trusted", json=proto, headers={"X-Admin-Key": "hub-admin"}).raise_for_status()
    node.trigger_sync()
    assert get_trusted_store().get("seizure-convulsion-01").version == proto["version"]

    # 4. Re-running sync is a no-op (idempotent cursor, nothing echoed back).
    res = node.trigger_sync()
    assert res["pushed"] == 0 and res["pulled"] == 0


def test_hub_rejects_trusted_protocols_from_nodes(hub):
    proto = httpx.get(f"{hub}/api/memory/trusted").json()[0]
    proto["version"] += 100
    entry = {"id": "rogue-1", "entity_type": "trusted", "entity_id": proto["id"], "operation": "UPSERT",
             "origin_node": "rogue", "payload": proto}
    httpx.post(f"{hub}/api/sync/hub/push", json={"node_id": "rogue", "entries": [entry]}).raise_for_status()
    after = next(p for p in httpx.get(f"{hub}/api/memory/trusted").json() if p["id"] == proto["id"])
    assert after["version"] < proto["version"]
