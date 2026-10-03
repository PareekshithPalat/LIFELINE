import io
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from edge.config import get_settings


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    data = client.get("/api/system/health").json()
    assert data["status"] == "HEALTHY"
    assert data["collections"]["engine"] == "qdrant-edge"
    assert data["collections"]["TRUSTED"]["documents"] == 12
    assert data["dense_model_ready"] is True


def test_cpr_query_returns_every_step(client):
    data = client.post("/api/emergency/query", json={
        "query": "Adult is unresponsive and not breathing. Start CPR", "allow_cache": False}).json()
    assert data["risk_level"] == "CRITICAL" and data["verdict"] == "SUFFICIENT"
    assert len(data["immediate_actions"]) == 6
    assert any("100-120 compressions per minute" in a for a in data["immediate_actions"])
    assert data["citations"][0]["evidence_id"] == "cpr-adult-01"


def test_contraindication_conflict(client):
    data = client.post("/api/emergency/query", json={
        "query": "Can I give the patient Aspirin for chest pain?", "allow_cache": False}).json()
    assert data["verdict"] == "CONFLICT" and data["escalation_needed"] is True
    assert data["withheld_actions"]


def test_off_domain_abstains(client):
    data = client.post("/api/emergency/query", json={"query": "best laptop for gaming"}).json()
    assert data["verdict"] == "INSUFFICIENT" and data["citations"] == []


def test_profile_question_answered_from_vault(client):
    data = client.post("/api/emergency/query", json={"query": "what is my blood type"}).json()
    assert data["retrieval_mode"] == "profile"
    assert any("O-" in a for a in data["immediate_actions"])


def test_triage_is_age_and_profile_aware(client):
    base = {"consciousness": True, "breathing": True, "severe_bleeding": False, "chest_pain": False,
            "allergic_swelling": False}
    infant = client.post("/api/emergency/triage", json={**base, "breathing": False, "age_category": "infant"}).json()
    assert infant["triage_color"] == "RED" and any("2 fingers" in s for s in infant["action_checklist"])
    owner = client.post("/api/emergency/triage", json={**base, "chest_pain": True}).json()
    assert any("DO NOT GIVE ASPIRIN" in c for c in owner["contraindications"])
    assert not any("aspirin to chew" in s for s in owner["action_checklist"])
    stranger = client.post("/api/emergency/triage",
                           json={**base, "chest_pain": True, "patient_is_profile_owner": False}).json()
    assert any("aspirin to chew" in s for s in stranger["action_checklist"])
    child = client.post("/api/emergency/triage", json={**base, "chest_pain": True, "age_category": "child",
                                                        "patient_is_profile_owner": False}).json()
    assert not any("aspirin to chew" in s for s in child["action_checklist"])


def test_api_key_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_key", "s3cret")
    assert client.get("/api/memory/personal").status_code == 401
    assert client.get("/api/memory/personal", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/memory/personal", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/system/health").status_code == 200


def test_trusted_protocols_require_admin_and_newer_version(client, monkeypatch):
    item = client.get("/api/memory/trusted").json()[0]
    assert client.post("/api/memory/trusted", json=item).status_code == 403
    monkeypatch.setattr(get_settings(), "admin_key", "adm")
    hdr = {"X-Admin-Key": "adm"}
    assert client.post("/api/memory/trusted", json=item, headers=hdr).status_code == 409
    item["version"] += 1
    item["content"] += "\nStep 99: Reassess every 2 minutes."
    item["hash"] = "client-supplied-hash-is-ignored"
    res = client.post("/api/memory/trusted", json=item, headers=hdr)
    assert res.status_code == 200
    assert res.json()["hash"] != "client-supplied-hash-is-ignored"


def test_profile_version_never_moves_backwards(client):
    current = client.get("/api/memory/personal").json()
    stale = {**current, "version": 1, "allergies": current["allergies"] + ["Latex"]}
    saved = client.put("/api/memory/personal", json=stale).json()
    assert saved["version"] == current["version"] + 1
    assert "Latex" in saved["allergies"]


def test_incident_log_and_filter(client):
    obs = {"incident_id": "api-test", "vital_signs": {"pulse": 110}, "observed_symptoms": ["wheeze"]}
    first = client.post("/api/memory/incident", json=obs).json()
    second = client.post("/api/memory/incident", json=obs).json()
    assert (first["version"], second["version"]) == (1, 2)
    listed = client.get("/api/memory/incident", params={"incident_id": "api-test"}).json()
    assert [o["id"] for o in listed] == [second["id"], first["id"]]


def test_media_upload_and_path_traversal_is_rejected(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    res = client.post("/api/media/upload", files={"file": ("../../evil.png", io.BytesIO(png), "image/png")})
    assert res.status_code == 200
    meta = res.json()
    assert meta["filename"] == "evil.png" and ".." not in meta["media_id"]
    assert client.get(meta["local_url"]).content == png
    for bad in ["..%5C..%5C.env", "..%2F..%2F.env", "notours.png"]:
        assert client.get(f"/api/media/file/{bad}").status_code == 404
    assert client.post("/api/media/upload",
                       files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")}).status_code == 400


def test_cache_stats_and_clear(client):
    assert client.get("/api/cache/stats").status_code == 200
    assert "cleared" in client.post("/api/cache/clear").json()["message"]
