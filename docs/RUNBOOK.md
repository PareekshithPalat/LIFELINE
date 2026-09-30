# Lifeline Edge Runbook & Developer Operations

This document provides operational instructions for running, testing, and demonstrating the Lifeline Edge system.

---

## 1. Prerequisites

- Python 3.11+ (Python 3.12 verified)
- Node.js 18+ (Node 20 / 24 verified)
- Git

---

## 2. Quickstart Setup

### Step A: Python Virtual Environment & Dependencies
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

### Step B: Build Web Console Frontend
```powershell
cd apps/web
npm install
npm run build
cd ../..
```

### Step C: Seed Qdrant Edge Memory
```powershell
python scripts/seed_data.py
```

### Step D: Launch Lifeline Edge Server
```powershell
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```
Open **`http://localhost:8000`** in your browser to interact with the Lifeline Web Console.

---

## 3. Running Automated Tests

Run the complete 18-test pytest suite:
```powershell
.\.venv\Scripts\python.exe -m pytest -v tests/
```

### Test Coverage Breakdown:
1. `test_embeddings.py`: Validates 384-dimensional dense vectors, BM25 sparse generation, and cosine similarity.
2. `test_hybrid_retrieval.py`: Tests Reciprocal Rank Fusion (RRF) math and multi-tier retrieval.
3. `test_semantic_cache.py`: Verifies sub-10ms cache hits, misses, TTL eviction, and state-based invalidations.
4. `test_validator_and_risk.py`: Tests Intent + Risk routing, allergy conflict detection, and abstain fallbacks.
5. `test_sync.py`: Verifies offline mutation buffering, vector clocks, and Safety Maximum profile merging.
6. `test_api.py`: End-to-end integration tests for all FastAPI endpoints using TestClient.

---

## 4. Running the Demo Scenarios

Execute the standalone clinical demonstration script:
```powershell
python scripts/demo_scenario.py
```

The script exercises:
- **Scenario 1**: Adult Unresponsive / Cardiac Arrest (Critical Risk -> Sufficient Verdict -> CPR & AED Protocol).
- **Scenario 2**: Semantic Cache Acceleration (Sub-10ms repeat response).
- **Scenario 3**: Contraindication Conflict Detection (Aspirin query with recorded patient Aspirin allergy & GI bleeding ulcer -> Escalation & STOP banner).
- **Scenario 4**: State-Based Cache Invalidation (Demonstrates automatic cache invalidation when patient profile version changes).

---

## 5. API Reference Summary

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/system/health` | GET | Edge system status, network mode, and Qdrant collection stats |
| `/api/emergency/query` | POST | Natural-language emergency query pipeline |
| `/api/emergency/triage` | POST | Rapid START triage calculation |
| `/api/memory/personal` | GET / PUT | Inspect and update patient emergency vault |
| `/api/memory/incident` | GET / POST | View and append chronological incident vitals |
| `/api/memory/trusted` | GET / POST | Browse clinical emergency protocols |
| `/api/cache/stats` | GET | Inspect cache hit rate and invalidation counts |
| `/api/cache/clear` | POST | Flush semantic cache |
| `/api/sync/status` | GET | Vector clock status and pending mutation counts |
| `/api/sync/trigger` | POST | Execute edge-to-server sync cycle |
| `/api/sync/toggle-network`| POST | Simulate network disconnect/reconnect |
| `/api/media/upload` | POST | Upload emergency photo (stored on edge disk + Cloudinary queue) |
| `/api/media/file/{file}`| GET | Serve local edge media asset |
