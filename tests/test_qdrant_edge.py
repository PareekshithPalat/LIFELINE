import json
import os
import tempfile
from models.enums import MemoryTier
from models.schemas import EvidenceItem
from edge.qdrant.client import QdrantEdgeManager, evidence_chunks

SEED = os.path.join(os.path.dirname(__file__), "..", "data", "trusted_protocols.json")


def _items():
    return [EvidenceItem.model_validate(p) for p in json.load(open(SEED, encoding="utf-8"))]


def test_chunks_cover_title_triggers_and_every_step():
    item = _items()[0]
    kinds = [c["kind"] for c in evidence_chunks(item)]
    assert kinds.count("title") == 1
    assert kinds.count("trigger") == len(item.triggers)
    assert kinds.count("step") == item.content.count("Step ")


def test_upsert_is_idempotent_and_shrinking_edit_removes_stale_chunks():
    m = QdrantEdgeManager(memory_mode=True)
    try:
        item = _items()[0]
        m.upsert_evidence(item)
        n = m.get_stats()["TRUSTED"]["points_count"]
        m.upsert_evidence(item)
        assert m.get_stats()["TRUSTED"]["points_count"] == n
        short = item.model_copy(update={"content": "Step 1: Call 911.", "version": 2}).rehash()
        m.upsert_evidence(short)
        # doc point + title + triggers + one step
        assert m.get_stats()["TRUSTED"]["points_count"] == 1 + 1 + len(item.triggers) + 1
        assert m.get_evidence(MemoryTier.TRUSTED, item.id).version == 2
    finally:
        m.close()


def test_persistence_and_rebuild_on_manifest_change():
    path = tempfile.mkdtemp()
    m = QdrantEdgeManager(storage_path=path, memory_mode=False)
    m.upsert_many(_items()[:3])
    m.close()
    m = QdrantEdgeManager(storage_path=path, memory_mode=False)
    assert len(m.list_evidence(MemoryTier.TRUSTED)) == 3
    m.close()
    with open(os.path.join(path, "manifest.json"), "w") as f:
        json.dump({"schema_version": -1, "dense_model": "other"}, f)
    m = QdrantEdgeManager(storage_path=path, memory_mode=False)
    try:
        assert len(m.list_evidence(MemoryTier.TRUSTED)) == 3  # rebuilt from the stored items
        with open(os.path.join(path, "manifest.json")) as f:
            assert json.load(f)["dense_model"] == m.engine.model_id
    finally:
        m.close()
