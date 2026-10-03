import numpy as np
from edge.embeddings.engine import get_embedding_engine, EmbeddingEngine


def test_dense_embedding_is_normalised_384d():
    vec = get_embedding_engine().embed_text("Cardiac arrest chest compressions")
    assert len(vec) == 384 and abs(np.linalg.norm(vec) - 1.0) < 1e-3


def test_bm25_query_and_document_vectors():
    e = get_embedding_engine()
    q = e.embed_sparse_query("EpiPen 0.3mg auto-injector")
    d = e.embed_sparse_document("EpiPen EpiPen 0.3mg auto-injector")
    assert len(q.indices) > 0 and all(v == 1.0 for v in q.values)
    assert set(q.indices) <= set(d.indices)


def test_cosine_similarity():
    assert abs(EmbeddingEngine.cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-6
    assert abs(EmbeddingEngine.cosine_similarity([1, 0, 0], [0, 1, 0])) < 1e-6
