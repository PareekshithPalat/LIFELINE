# Lifeline

> **Risk-Aware Adaptive Emergency Memory for Edge Devices**  
> *"Your emergency memory. Even when the network isn't there."*

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Qdrant](https://img.shields.io/badge/Qdrant-Edge%20Embedded-dc2626.svg)](https://qdrant.tech/)
[![React](https://img.shields.io/badge/React-19%20%2B%20Vite-61dafb.svg)](https://reactjs.org/)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-v4-38bdf8.svg)](https://tailwindcss.com/)
[![Tests](https://img.shields.io/badge/Tests-18%20Passing-brightgreen.svg)]()

---

## 1. Executive Summary

**Lifeline** is an offline-first, risk-aware personal emergency memory system designed to run on resource-constrained edge devices (smartphones, field tablets, ambulance consoles, search-and-rescue nodes).

The core principle:
> **THE CLOUD SHOULD ENHANCE THE DEVICE.**  
> **THE CLOUD MUST NOT BE REQUIRED FOR BASIC EMERGENCY MEMORY.**

During network blackout, disaster events, or remote terrain emergencies, Lifeline stores personal medical profiles, retrieves certified clinical guidelines, detects life-threatening contraindications, and guides first responders—entirely locally with zero cloud dependencies.

---

## 2. Core Architectural Innovations

### 1. Three-Tier Memory Architecture
- **Trusted Clinical Memory (`lifeline_trusted_memory`)**: Preloaded certified medical guidelines (AHA CPR/AED, Anaphylaxis Epinephrine, Severe Arterial Bleeding, Asthma Exacerbation, Burns, FAST Stroke, Toxic Poisoning).
- **Personal Vault Memory (`lifeline_personal_memory`)**: Private patient profile with confirmed blood group, severe allergies, active medications, chronic conditions, and ICE emergency contacts.
- **Incident Timeline Memory (`lifeline_incident_memory`)**: Real-time temporal stream of on-scene vital signs (Heart rate, SpO2), observed symptoms, and actions taken.

### 2. Qdrant Edge Multi-Vector Retrieval
- **Dense 384-dimensional vectors** (`BAAI/bge-small-en-v1.5` ONNX) capturing semantic clinical concepts.
- **Sparse BM25 vectors** capturing exact drug names, dosages, and emergency keywords (*"EpiPen 0.3mg"*, *"Aspirin"*, *"AED"*, *"Tourniquet"*, *"Albuterol"*).
- Fused using **Reciprocal Rank Fusion (RRF)**:
  $$RRF\_Score(d) = \sum_{m \in \{dense, sparse\}} \frac{1.0}{k + \text{rank}_m(d)}$$

### 3. Risk-Aware Evidence-State Semantic Cache
Prevents hazardous medical hallucinations by binding each cached entry to the **exact SHA-256 content hashes** of grounding evidence and patient state versions.
- If the patient's allergy profile changes, or a new incident observation is recorded, the cache automatically invalidates stale entries.
- Sub-10ms cache latency for rapid repeat inquiries under stress.

### 4. Three-State Evidence Validator
- **`SUFFICIENT`**: Clear, uncontradicted evidence found. Generates grounded action checklists with source citations.
- **`CONFLICT`**: Active contraindication detected (e.g. Heart attack protocol suggests Aspirin, but personal vault records an Aspirin allergy or bleeding ulcer). Triggers immediate **STOP** warning banner and safe alternative actions.
- **`INSUFFICIENT`**: Off-domain or ambiguous query. System **ABSTAINS** from guessing and surfaces 911/112 dispatch protocols.

### 5. Intelligent Sync Controller & Conflict Strategies
- Buffers offline mutations in an append-only log with **Vector Clocks**.
- **Safety Maximum**: When merging conflicting personal records, never drops an allergy or condition (union of safety constraints).
- **Trusted Authority**: Upstream verified clinical protocols supersede local edits.
- **Monotonic Append**: Incident timeline follows CRDT append-only semantics.

### 6. Media Integration (Local Disk + Cloudinary)
- Emergency scene photos (wounds, prescription bottles, rash) are stored on local edge disk for offline inspection.
- Automatically queued and synced to Cloudinary when network connectivity is restored.

---

## 3. Repository Structure

```
lifeline/
├── apps/
│   ├── api/                  # FastAPI backend server
│   │   ├── main.py           # Application entrypoint & static mount
│   │   └── routes/           # Emergency, Memory, Cache, Sync, Media routes
│   └── web/                  # React + Vite + Tailwind CSS Web Console
│       ├── src/
│       │   ├── App.tsx       # Emergency Dashboard & Tabs
│       │   ├── api.ts        # API client
│       │   └── types.ts      # TypeScript definitions
├── edge/
│   ├── qdrant/               # Qdrant Edge local storage & collections
│   ├── embeddings/           # FastEmbed local dense & sparse ONNX engine
│   ├── retrieval/            # Hybrid retrieval & Reciprocal Rank Fusion (RRF)
│   ├── cache/                # Evidence-State Semantic Cache
│   ├── runtime/              # Router, Reranker, Validator, Adaptive SLM Pipeline
│   ├── sync/                 # Vector Clock Sync Controller & Conflict Resolvers
│   └── media.py              # Offline-first media manager & Cloudinary sync
├── models/
│   ├── enums.py              # Domain enums (RiskLevel, MemoryTier, Verdicts)
│   └── schemas.py            # Pydantic schemas for queries, responses, profiles
├── data/
│   ├── trusted_protocols.json # Certified clinical protocols
│   └── default_personal.json  # Demo patient emergency vault profile
├── scripts/
│   ├── seed_data.py          # Seeds Qdrant Edge with protocols & vault
│   └── demo_scenario.py      # End-to-end clinical demonstration
├── tests/                    # 18 automated unit and integration tests
├── docs/
│   ├── ARCHITECTURE.md       # Technical architecture specification & diagrams
│   └── RUNBOOK.md            # Operator runbook & API reference
├── docker/
│   └── Dockerfile            # Multi-stage production container build
├── .env.example              # Environment configuration template
├── requirements.txt          # Python dependencies
└── docker-compose.yml        # Compose configuration
```

---

## 4. Quickstart Guide

### 1. Setup Environment
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r requirements.txt
```

### 2. Build Web Console
```powershell
cd apps/web
npm install
npm run build
cd ../..
```

### 3. Seed Edge Database
```powershell
python scripts/seed_data.py
```

### 4. Start Lifeline Server
```powershell
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```
Open **`http://localhost:8000`** in any web browser.

---

## 5. Verification & Testing

Run the automated test suite (18 unit & integration tests covering embeddings, hybrid retrieval, cache invalidation, conflict resolution, and API endpoints):

```powershell
.\.venv\Scripts\python.exe -m pytest -v tests/
```

Run the clinical demonstration scenarios:
```powershell
python scripts/demo_scenario.py
```

---

## 6. Docker Deployment

Deploy with Docker Compose:
```bash
docker-compose up --build
```
The server will be available at `http://localhost:8000`.

---

## 7. License
MIT License.
