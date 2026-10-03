# Lifeline Mobile

Flutter app that runs the complete Lifeline engine **on the phone**, with no network required:

| Layer | Implementation |
| :--- | :--- |
| Vector memory | [Qdrant Edge](https://pub.dev/packages/qdrant_edge) (embedded Rust engine via UniFFI): trusted / personal / incident shards, dense + BM25 with IDF |
| Dense embeddings | `bge-small-en-v1.5` ONNX (the exact file the backend uses) through `flutter_onnxruntime`, CLS pooling + L2 norm |
| Sparse embeddings | `lib/engine/bm25.dart`: bit-exact port of Qdrant Edge's `Bm25` (word tokenizer, Qdrant stopwords, Snowball English, murmur3) |
| Tokenizer | `lib/engine/wordpiece.dart`: BERT uncased WordPiece matching the HuggingFace tokenizer |
| Knowledge | `assets/knowledge/pack.json`: protocols + precomputed chunk vectors + calibrated config |
| Engine | router, calibrated gate, safety screening, grounded responder, evidence-state semantic cache, triage (`lib/engine/`) |
| Data | atomic JSON stores for profile, incidents, protocol revisions, settings, sync log (`lib/data/`) |
| Sync | push/pull to any Lifeline API acting as hub (`/api/sync/hub/*`) with SAFETY_MAXIMUM / TRUSTED_AUTHORITY / MONOTONIC_APPEND |

Screens: **Assist** (question + one-tap scenarios + one-tap emergency call), **Triage**, **Vault**, **Incident**
timeline and **More** (protocols, hub sync, engine diagnostics).

## Build

```bash
# 1. From the repo root: generate the knowledge pack, copy the model, write test fixtures
python scripts/build_mobile_pack.py

# 2. Build / run
cd apps/mobile
flutter pub get
flutter run                     # or: flutter build apk --release
```

* Android: arm64-v8a and x86_64 only - the Qdrant Edge engine has no 32-bit build, so 32-bit devices are excluded
  instead of crashing. minSdk 24.
* iOS: supported by every dependency (Qdrant Edge ships iOS device + simulator libraries; ONNX Runtime needs iOS 16+).
  Build on macOS with `flutter build ios`.
* The `qdrant_edge` build hook downloads SHA-256-pinned prebuilt engine libraries on the first build.
* Release builds only talk to HTTPS hubs; debug builds also allow plain HTTP on a LAN.

## Tests

```bash
flutter test                                  # host: Dart engine on the real Qdrant Edge library
flutter test integration_test -d <device-id>  # device/emulator: real ONNX Runtime + Qdrant Edge + UI
```

| Test | What it proves |
| :--- | :--- |
| `test/bm25_parity_test.dart` | identical BM25 token ids/weights to the Python engine for every vocabulary word |
| `test/tokenizer_parity_test.dart` | identical WordPiece ids to the HuggingFace tokenizer |
| `test/pipeline_eval_test.dart` | all 60 labelled eval queries + safety + cache behaviour, on Qdrant Edge |
| `integration_test/app_test.dart` | on-device embeddings match the backend (cosine > 0.999), eval set on-device, cache, UI |
