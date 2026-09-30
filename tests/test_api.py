import pytest
from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/system/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert "collections" in data

def test_emergency_query_cpr():
    payload = {
        "query": "Adult is unresponsive and not breathing. Start CPR",
        "allow_cache": False
    }
    response = client.post("/api/emergency/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "CRITICAL"
    assert len(data["immediate_actions"]) > 0
    assert len(data["citations"]) > 0

def test_emergency_query_contraindication_alert():
    payload = {
        "query": "Can I give the patient Aspirin for chest pain?",
        "allow_cache": False
    }
    response = client.post("/api/emergency/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "CONFLICT"
    assert data["escalation_needed"] is True
    assert len(data["contraindications_and_warnings"]) > 0

def test_rapid_triage_assessment():
    payload = {
        "consciousness": False,
        "breathing": False,
        "severe_bleeding": False,
        "chest_pain": False,
        "allergic_swelling": False
    }
    response = client.post("/api/emergency/triage", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["triage_color"] == "RED"
    assert data["call_emergency_services_now"] is True

def test_cache_stats_and_clear():
    # Get stats
    res1 = client.get("/api/cache/stats")
    assert res1.status_code == 200
    # Clear cache
    res2 = client.post("/api/cache/clear")
    assert res2.status_code == 200
    assert "cleared successfully" in res2.json()["message"]

def test_sync_status_and_network_toggle():
    # Toggle to online
    t_res = client.post("/api/sync/toggle-network", json={"online": True})
    assert t_res.status_code == 200
    assert t_res.json()["is_online"] is True

    # Status check
    s_res = client.get("/api/sync/status")
    assert s_res.status_code == 200
    assert s_res.json()["is_online"] is True

    # Toggle back to offline
    client.post("/api/sync/toggle-network", json={"online": False})
