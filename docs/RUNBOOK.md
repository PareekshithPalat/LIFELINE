# Lifeline Runbook

## 1. Prerequisites

| Component | Version used |
| :--- | :--- |
| Python | 3.12 |
| Node.js | 20+ |
| Flutter (mobile) | 3.47 / Dart 3.13 (Dart ≥ 3.12 is required by `qdrant_edge`) |
| Android SDK (mobile) | platform 36, NDK 28.2 |

## 2. Backend node

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd apps/web; npm install; npm run build; cd ../..

copy .env.example .env      # set LIFELINE_API_KEY (and LIFELINE_ADMIN_KEY if protocols are edited here)
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

First start downloads the embedding model into `data/models/` and indexes everything (a few seconds). Later starts
only re-index what changed. `python scripts/seed_data.py` runs the same reconciliation without starting the server.

Runtime state:

| Path | Content |
| :--- | :--- |
| `data/runtime/` | profile, incidents, trusted revisions, sync log, media |
| `data/edge_shards/` | Qdrant Edge shards + `manifest.json` (safe to delete; rebuilt from `data/runtime`) |
| `data/models/` | embedding model cache |

> The old `data/qdrant_storage/` folder from the previous `qdrant-client` build is no longer used and can be deleted.

## 3. Tests

```powershell
python -m pytest -q tests          # ~100 tests, about 40 s
```

| File | Covers |
| :--- | :--- |
| `test_eval_set.py` | all 60 labelled queries route correctly / abstain; off-domain margin |
| `test_safety.py` | allergy expansion, condition rules, age rules, other-person detection, full steps |
| `test_semantic_cache.py` | hits, negation/drug guards, profile/incident/hash invalidation, TTL, LRU |
| `test_qdrant_edge.py` | chunking, idempotent upserts, persistence, manifest-triggered rebuild |
| `test_api.py` | endpoints, API key, admin key, version monotonicity, media path traversal |
| `test_sync.py` | offline buffering, unreachable hub, SAFETY_MAXIMUM, **two-node replication over HTTP** |

## 4. Changing protocols or thresholds

1. Edit `data/trusted_protocols.json` (bump `version` for changed protocols) or `data/retrieval_config.json`.
2. Add representative queries to `tests/eval/retrieval_eval.json` and run `pytest tests/test_eval_set.py`.
3. Rebuild the phone's knowledge pack: `python scripts/build_mobile_pack.py`, then `flutter test` in `apps/mobile`.

Running nodes pick up a newer seed version on restart (TRUSTED_AUTHORITY). To push a revision to connected nodes
without a restart, POST it to `/api/memory/trusted` with `X-Admin-Key`; it replicates through the hub.

## 5. Connecting phones

1. Run the backend reachable from the phones (HTTPS in production; plain HTTP is allowed only in debug builds).
2. In the app: **More → Sync with a Lifeline hub** → hub URL + `LIFELINE_API_KEY` → *Save & sync now*.
3. The app also syncs every 2 minutes while the network switch is on. Pending changes show in the top bar.

## 6. Troubleshooting

| Symptom | Cause / fix |
| :--- | :--- |
| Health shows `dense_model_ready: false` | Model not in `data/models` and no network on first start. Start once online or copy the model cache. |
| Every API call returns 401 | `LIFELINE_API_KEY` is set; send `X-API-Key` (the web console asks for it). |
| `POST /api/memory/trusted` returns 403 / 409 | Admin key missing, or the version is not newer than the stored one. |
| Sync status `UNREACHABLE` | Hub down or wrong URL; changes stay buffered and retry automatically. |
| `ShardLockedEdgeException` | Another process has the shard open (only one process per `QDRANT_STORAGE_PATH`). |
