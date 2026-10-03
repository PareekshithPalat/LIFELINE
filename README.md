# LIFELINE

> **Risk-Aware Adaptive Emergency Memory for Edge Devices**  
> *"Your emergency memory. Even when the network isn't there."*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Qdrant](https://img.shields.io/badge/Qdrant-Edge%200.8-dc2626.svg)](https://qdrant.tech/documentation/edge/)
[![Flutter](https://img.shields.io/badge/Flutter-Android%20%7C%20iOS-02569B.svg)](apps/mobile)
[![React](https://img.shields.io/badge/React-19%20%2B%20Vite-61dafb.svg)](https://reactjs.org/)

---

## 1. Executive Summary

**LIFELINE** is an offline-first, risk-aware personal emergency memory and decision-support system that runs
entirely on the device: a phone (Flutter app), a field laptop or an ambulance console (FastAPI node + web console).

> **THE CLOUD SHOULD ENHANCE THE DEVICE.**  
> **THE CLOUD MUST NOT BE REQUIRED FOR BASIC EMERGENCY MEMORY.**

Lifeline stores the patient's medical vault, retrieves verified first-aid protocols with an embedded
[Qdrant Edge](https://qdrant.tech/documentation/edge/) engine, removes protocol steps that are unsafe for *this*
patient, and refuses to guess when no protocol clearly applies. Every instruction it shows is a verbatim step
from a trusted protocol - nothing is generated.

---

## 2. Core Design

### 1. Three memory tiers, one Qdrant Edge shard each

| Tier | Source of truth | Purpose | Conflict strategy |
| :--- | :--- | :--- | :--- |
| **Trusted** | `data/trusted_protocols.json` + signed revisions | Verified first-aid protocols (CPR, bleeding, anaphylaxis, asthma, choking, burns, seizure, stroke, heart attack, poisoning, hypoglycaemia) | **TRUSTED_AUTHORITY** - only a strictly newer version replaces a protocol; protocols only flow *down* from a hub and need the admin key |
| **Personal** | profile store | Blood group, allergies, medications, conditions, ICE contacts | **SAFETY_MAXIMUM** - allergies, conditions and medications are unioned on merge, never dropped |
| **Incident** | incident store | On-scene vitals, symptoms and actions, per incident id | **MONOTONIC_APPEND** - append-only, de-duplicated by id |

The JSON stores are the source of truth (atomic writes); the Qdrant Edge shards are a derived index that is
reconciled at start-up and rebuilt automatically if the schema or embedding model changes.

### 2. Hybrid retrieval with a calibrated relevance gate
- Each protocol is indexed as **chunks** - its title, lay-language *trigger* phrases ("my dad collapsed and isn't
  breathing") and every individual step - each with a 384-d `BAAI/bge-small-en-v1.5` vector. A query is scored
  by its best-matching chunk (max-sim), not an averaged whole-document embedding.
- A **BM25** sparse vector over the full text (Qdrant Edge's own `Bm25` model, shard modifier `IDF`) captures exact
  drug names and keywords.
- The two signals are fused into a calibrated confidence
  `dense_max_sim + 0.015 * min(bm25, 10)`; a protocol is used only above the thresholds in
  [`data/retrieval_config.json`](data/retrieval_config.json). Otherwise the system **abstains**.
- Calibrated and regression-tested on a labelled set ([`tests/eval/retrieval_eval.json`](tests/eval/retrieval_eval.json))
  of 40 real emergencies, 11 off-domain questions and 9 medical questions with no matching protocol (snake bite,
  fever, heat stroke…): **60/60 correct** on the backend and on the phone.

### 3. Patient safety screening (SUFFICIENT / CONFLICT / INSUFFICIENT)
- Allergies are normalised and expanded (`"NSAIDs (Ibuprofen, Naproxen)"` → nsaid, ibuprofen, naproxen, aspirin, …;
  `"Peanuts"` → peanut, peanut butter, …). Conditions and medications add rules (GI bleeding / anticoagulants →
  no aspirin or NSAIDs; pregnancy → no abdominal thrusts).
- Age is taken from the request or the query ("my 8 month old") and adds rules: no aspirin for children or
  adolescents; infants get back blows and chest thrusts instead of the adult choking technique.
- Any protocol step that violates a rule is **withheld** (and shown struck through with the reason); a question
  that asks to *give* something unsafe ("can I give aspirin?") gets an explicit **DO NOT GIVE** warning.
- The owner's allergies are not applied to someone else ("my father has chest pain") - the answer tells the
  responder to ask about allergies instead.

### 4. Evidence-state semantic cache
An answer is reused only if **all** of these hold: cosine similarity ≥ the risk-adaptive threshold (0.96 critical
… 0.90 low), *identical safety-relevant words* (negations, age, drugs, allergens - so "is breathing" never reuses
"is not breathing" and "aspirin" never reuses "ibuprofen"), same age group, TTL alive, unchanged profile version,
unchanged incident-timeline version and unchanged content hash of every cited protocol. Abstentions are never
cached; the cache is LRU-bounded and scanned with one vectorised product.

### 5. Offline-first replication
Every change is appended to a durable mutation log. `POST /api/sync/trigger` (or the app's sync button, or the
background loop) pushes pending entries to the upstream hub and pulls what other nodes produced, applying the
strategies above. **Every Lifeline API is also a hub** (`/api/sync/hub/push|pull`), which is how the phone syncs.

### 6. Mobile app with the same engine on the phone
[`apps/mobile`](apps/mobile) is a Flutter app that runs the full pipeline on-device: Qdrant Edge (Dart bindings),
the same ONNX embedding model via ONNX Runtime, a bit-exact Dart port of Qdrant's BM25, the safety engine, the
semantic cache, triage, the vault, the incident log and hub sync. Protocol vectors ship precomputed in a
knowledge pack. See [`apps/mobile/README.md`](apps/mobile/README.md).

### 7. Security
- `LIFELINE_API_KEY` protects every `/api` route (`X-API-Key`); CORS is limited to configured origins.
- Publishing a trusted protocol requires `LIFELINE_ADMIN_KEY` (`X-Admin-Key`); client-supplied hashes are ignored.
- Uploaded media are stored under server-generated names with type and size limits (no path traversal).

---

## 3. Repository Structure

```
lifeline/
├── apps/
│   ├── api/                 # FastAPI node: routes, API-key/admin security, static web console
│   ├── web/                 # React 19 + Vite + Tailwind web console
│   └── mobile/              # Flutter app: on-device Qdrant Edge + ONNX + safety engine
├── edge/
│   ├── config.py            # Settings (env vars) + calibrated retrieval config
│   ├── stores.py            # Source-of-truth JSON stores (profile, incidents, trusted)
│   ├── bootstrap.py         # Reconciles the Qdrant Edge index with the stores
│   ├── memory_service.py    # Single write path: store -> index -> cache -> sync log
│   ├── qdrant/client.py     # Qdrant Edge shards (chunked dense + BM25/IDF)
│   ├── embeddings/          # bge-small dense (FastEmbed) + Qdrant Edge Bm25
│   ├── retrieval/hybrid.py  # Hybrid search + calibrated fusion
│   ├── cache/               # Evidence-state semantic cache
│   ├── runtime/             # router, validator (gate), safety, responder, triage, pipeline
│   ├── sync/controller.py   # Mutation log, hub + client replication, conflict strategies
│   └── media.py             # Offline-first media storage (+ optional Cloudinary)
├── models/                  # Pydantic schemas and enums
├── data/
│   ├── trusted_protocols.json   # Verified protocols (+ trigger phrases)
│   ├── default_personal.json    # Seed patient profile
│   ├── retrieval_config.json    # Calibrated thresholds shared by backend and app
│   └── bm25_stopwords_en.json   # Qdrant's English stopwords (used by the Dart BM25 port)
├── scripts/
│   ├── seed_data.py             # Index the stores into Qdrant Edge
│   ├── demo_scenario.py         # End-to-end demonstration
│   └── build_mobile_pack.py     # Knowledge pack + model + parity fixtures for the app
├── tests/                   # pytest suite incl. the labelled eval set and a two-node sync test
├── docs/                    # ARCHITECTURE.md, RUNBOOK.md
└── docker/, docker-compose.yml
```

---

## 4. Quickstart (backend + web console)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows   |   source .venv/bin/activate (Linux/macOS)
pip install -r requirements.txt

cd apps/web && npm install && npm run build && cd ../..

python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```
Open **`http://localhost:8000`** (API docs at `/docs`). On first start the embedding model (~66 MB) is downloaded
into `data/models/` and the protocols are indexed; after that the node needs no network at all.

For the mobile app see [`apps/mobile/README.md`](apps/mobile/README.md).

---

## 5. Environment Configuration

Copy `.env.example` to `.env`.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `LIFELINE_NODE_ID` | `edge_device_alpha` | Node identity in the replication log |
| `LIFELINE_API_KEY` | *(unset)* | Required `X-API-Key` for every `/api` route - **set it before exposing the node** |
| `LIFELINE_ADMIN_KEY` | *(unset)* | Required `X-Admin-Key` to publish trusted protocols (editing disabled when unset) |
| `LIFELINE_CORS_ORIGINS` | localhost dev origins | Comma-separated allowed browser origins |
| `LIFELINE_SERVER_URL` / `LIFELINE_SERVER_API_KEY` | *(unset)* | Upstream hub for replication |
| `LIFELINE_DATA_DIR` / `LIFELINE_RUNTIME_DIR` | `data/`, `data/runtime/` | Seeds and mutable state |
| `QDRANT_STORAGE_PATH` | `data/edge_shards/` | Qdrant Edge shard directory |
| `FASTEMBED_CACHE_PATH` | `data/models/` | Embedding model cache (kept for offline use) |
| `QDRANT_MEMORY_MODE` | `false` | Ephemeral shards (tests) |
| `LIFELINE_ENABLE_LLM_SUMMARY`, `OLLAMA_URL`, `OLLAMA_MODEL` | off | Optional one-line summary from a local model; it never changes the steps |
| `LIFELINE_MAX_UPLOAD_MB` | `15` | Media upload limit |
| `CLOUDINARY_*` | *(unset)* | Optional media upload when online |

---

## 6. API Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/system/health` | GET | Liveness, shard stats, model readiness (no patient data, no key needed) |
| `/api/emergency/query` | POST | Emergency question → grounded answer (`query`, `incident_id`, `age_category`, `allow_cache`) |
| `/api/emergency/triage` | POST | Age- and vault-aware rapid triage |
| `/api/memory/personal` | GET / PUT | Patient vault (version always increases) |
| `/api/memory/incident` | GET / POST | Incident timeline (`?incident_id=`), append-only |
| `/api/memory/trusted` | GET / POST | Protocols; POST needs `X-Admin-Key` and a newer version |
| `/api/cache/stats`, `/api/cache/clear` | GET / POST | Cache statistics / purge |
| `/api/sync/status`, `/trigger`, `/pending`, `/toggle-network` | GET / POST | Replication client |
| `/api/sync/hub/push`, `/api/sync/hub/pull` | POST / GET | Hub endpoints used by other nodes (e.g. the phone) |
| `/api/media/upload`, `/api/media/file/{media_id}` | POST / GET | Offline-first media |

---

## 7. Verification & Testing

```bash
pytest -q tests/                      # backend: unit, eval set, API, two-node sync over HTTP
python scripts/demo_scenario.py       # walkthrough of the main behaviours

cd apps/mobile
flutter test                          # Dart engine on real Qdrant Edge: BM25/tokenizer parity + eval set
flutter test integration_test -d <device>   # on a phone/emulator: ONNX parity, eval set, UI smoke test
```

---

## 8. Docker Deployment

```bash
echo "LIFELINE_API_KEY=$(openssl rand -hex 16)" >> .env
docker compose up --build
```
The image bakes in the embedding model, so the container works with no network. State and shards live in named
volumes.

---

## 9. Medical disclaimer

Lifeline supports trained and untrained responders with verified first-aid protocols. It does not diagnose,
does not replace professional medical care, and always directs the user to call emergency services. Protocol
content must be reviewed by a qualified clinician before deployment.

## 10. License

This project is licensed under the [MIT License](LICENSE).
