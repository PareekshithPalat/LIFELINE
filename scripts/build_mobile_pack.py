"""
Builds everything the mobile app needs to run the same engine on-device:

  apps/mobile/assets/knowledge/pack.json   trusted protocols + precomputed chunk vectors
                                           (bge-small) + BM25 document vectors + the
                                           calibrated retrieval config + stopwords
  apps/mobile/assets/models/               the exact ONNX model + tokenizer the backend uses
  apps/mobile/test/fixtures/parity.json    tokenizer / BM25 / query-vector fixtures that the
                                           Dart unit tests compare against this Python engine

Run after changing data/trusted_protocols.json or data/retrieval_config.json:
    python scripts/build_mobile_pack.py
"""
import os
import re
import sys
import json
import glob
import base64
import shutil
import hashlib

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("QDRANT_MEMORY_MODE", "true")

from models.schemas import EvidenceItem  # noqa: E402
from edge.config import get_retrieval_config, get_settings  # noqa: E402
from edge.embeddings.engine import get_embedding_engine  # noqa: E402
from edge.qdrant.client import evidence_chunks, evidence_fulltext  # noqa: E402

MOBILE = os.path.join(ROOT, "apps", "mobile")
PACK_PATH = os.path.join(MOBILE, "assets", "knowledge", "pack.json")
MODEL_DIR = os.path.join(MOBILE, "assets", "models")
FIXTURE_PATH = os.path.join(MOBILE, "test", "fixtures", "parity.json")
DEVICE_FIXTURE_PATH = os.path.join(MOBILE, "integration_test", "fixtures.g.dart")


def b64_f32(vec) -> str:
    return base64.b64encode(np.asarray(vec, dtype="<f4").tobytes()).decode("ascii")


def sparse_dict(sv) -> dict:
    return {"indices": [int(i) for i in sv.indices], "values": [float(v) for v in sv.values]}


def find_model_files():
    base = get_settings().models_path
    snaps = glob.glob(os.path.join(base, "models--Qdrant--bge-small-en-v1.5-onnx-Q", "snapshots", "*"))
    for snap in snaps:
        onnx = os.path.join(snap, "model_optimized.onnx")
        tok = os.path.join(snap, "tokenizer.json")
        if os.path.exists(onnx) and os.path.exists(tok):
            return onnx, tok
    raise SystemExit("Embedding model not found in the model cache. Start the API once (it downloads the model) "
                     "or set FASTEMBED_CACHE_PATH.")


def file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def build_pack(engine, model_path: str) -> dict:
    cfg = get_retrieval_config()
    stop = json.load(open(os.path.join(ROOT, "data", "bm25_stopwords_en.json"), encoding="utf-8"))["words"]
    # The Dart BM25 port relies on this list being exactly Qdrant's: verify against the engine.
    leaked = [w for w in stop if len(engine.embed_sparse_query(w).indices) > 0]
    if leaked:
        raise SystemExit(f"Stopword list does not match qdrant-edge: {leaked[:10]}")

    raw = json.load(open(os.path.join(ROOT, "data", "trusted_protocols.json"), encoding="utf-8"))
    protocols = []
    for p in raw:
        item = EvidenceItem.model_validate(p).rehash()
        chunks = evidence_chunks(item)
        vectors = engine.embed_texts([c["text"] for c in chunks])
        protocols.append({
            # Timestamps are excluded so identical content always yields the same pack version.
            "item": item.model_dump(mode="json", exclude={"created_at", "updated_at"}),
            "chunks": [{"kind": c["kind"], "text": c["text"], "vector": b64_f32(v)} for c, v in zip(chunks, vectors)],
            "bm25": sparse_dict(engine.embed_sparse_document(evidence_fulltext(item))),
        })

    body = {
        "schema_version": cfg["schema_version"],
        "dense_model": cfg["dense_model"],
        "dense_dim": cfg["dense_dim"],
        "model_version": file_digest(model_path),
        "retrieval_config": cfg,
        "stopwords": stop,
        "protocols": protocols,
        "default_profile": json.load(open(os.path.join(ROOT, "data", "default_personal.json"), encoding="utf-8")),
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"pack_version": digest, **body}


def build_fixtures(engine, tokenizer_path: str) -> dict:
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(tokenizer_path)
    tok.enable_truncation(max_length=512)

    eval_cases = json.load(open(os.path.join(ROOT, "tests", "eval", "retrieval_eval.json"), encoding="utf-8"))["cases"]
    protocols = json.load(open(os.path.join(ROOT, "data", "trusted_protocols.json"), encoding="utf-8"))
    extra_queries = [
        "Can I give the patient Aspirin for chest pain?", "my 8 month old baby is choking on a grape",
        "my father has crushing chest pain", "where do I inject the epipen",
        "adult collapsed and is not breathing", "Adult collapsed and is not breathing.",
        "can I give aspirin for chest pain", "can I give ibuprofen for chest pain",
        "the patient is unconscious and breathing", "the patient is unconscious and not breathing",
        "how do I stop heavy bleeding from a deep cut", "severe bleeding from the leg", "burn on hand",
        "seizure on floor", "choking on food", "baby not breathing", "how do I cook rice", "x",
        "what is my blood type", "my 8 month old baby is choking", "can I give him a peanut butter sandwich",
    ]
    queries = list(dict.fromkeys([c["q"] for c in eval_cases] + extra_queries))

    text_corpus = " ".join(queries + [p["title"] + " " + p["content"] + " " + " ".join(p["triggers"])
                                      for p in protocols])
    words = sorted(set(re.findall(r"[^\W_]+", text_corpus.lower())))
    tricky = ["EpiPen 0.3mg", "e-mail", "911/112", "children's", "isn't", "can't breathe", "Café naïve",
              "running runs ran", "the and of", "Heimlich", "anti-inflammatory", "x" * 30, "ÉMERGENCE",
              "COVID-19 2nd-degree burns", "don't stop", "it's 3:45pm"]

    sample_texts = tricky + queries[:20] + [protocols[0]["content"]]
    return {
        "tokenizer": [{"text": t, "ids": tok.encode(t).ids} for t in sample_texts],
        "bm25_words": {w: sorted(int(i) for i in engine.embed_sparse_query(w).indices) for w in words},
        "bm25_queries": [{"text": t, "indices": sorted(int(i) for i in engine.embed_sparse_query(t).indices)}
                         for t in tricky + queries],
        "bm25_documents": [{"text": t, **sparse_dict(engine.embed_sparse_document(t))}
                           for t in [protocols[0]["content"], "the cardiac cardiac arrest", tricky[0] + " " + tricky[3]]],
        "query_vectors": {q: b64_f32(v) for q, v in zip(queries, engine.embed_texts(queries))},
        "eval_cases": eval_cases,
    }


def main():
    engine = get_embedding_engine()
    if not engine.dense_available:
        raise SystemExit("Dense model unavailable; cannot build the mobile pack.")
    onnx_path, tokenizer_path = find_model_files()

    os.makedirs(os.path.dirname(PACK_PATH), exist_ok=True)
    pack = build_pack(engine, onnx_path)
    with open(PACK_PATH, "w", encoding="utf-8") as f:
        json.dump(pack, f, separators=(",", ":"), ensure_ascii=False)
    print(f"pack {pack['pack_version']}: {len(pack['protocols'])} protocols, "
          f"{sum(len(p['chunks']) for p in pack['protocols'])} chunks -> {os.path.relpath(PACK_PATH, ROOT)} "
          f"({os.path.getsize(PACK_PATH) // 1024} KB)")

    os.makedirs(MODEL_DIR, exist_ok=True)
    shutil.copyfile(onnx_path, os.path.join(MODEL_DIR, "bge-small-en-v1.5.onnx"))
    shutil.copyfile(tokenizer_path, os.path.join(MODEL_DIR, "tokenizer.json"))
    print(f"model -> {os.path.relpath(MODEL_DIR, ROOT)}")

    os.makedirs(os.path.dirname(FIXTURE_PATH), exist_ok=True)
    fixtures = build_fixtures(engine, tokenizer_path)
    with open(FIXTURE_PATH, "w", encoding="utf-8") as f:
        json.dump(fixtures, f, separators=(",", ":"), ensure_ascii=False)
    print(f"fixtures -> {os.path.relpath(FIXTURE_PATH, ROOT)} ({os.path.getsize(FIXTURE_PATH) // 1024} KB)")

    # On-device integration tests cannot read host files: embed what they need as Dart source.
    os.makedirs(os.path.dirname(DEVICE_FIXTURE_PATH), exist_ok=True)
    sample = [c["q"] for c in fixtures["eval_cases"]][::6]
    with open(DEVICE_FIXTURE_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("// GENERATED by scripts/build_mobile_pack.py - do not edit.\n")
        f.write("// ignore_for_file: lines_longer_than_80_chars\n\n")
        f.write(f"const evalCasesJson = r'''{json.dumps(fixtures['eval_cases'], ensure_ascii=False)}''';\n\n")
        f.write("const backendQueryVectors = <String, String>{\n")
        for q in sample:
            f.write(f"  {json.dumps(q)}: '{fixtures['query_vectors'][q]}',\n")
        f.write("};\n")
    print(f"device fixtures -> {os.path.relpath(DEVICE_FIXTURE_PATH, ROOT)}")


if __name__ == "__main__":
    main()
