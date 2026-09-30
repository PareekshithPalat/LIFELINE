import pytest
from edge.embeddings.engine import get_embedding_engine, EmbeddingEngine

def test_dense_embedding_shape():
    engine = get_embedding_engine()
    vec = engine.embed_text("Cardiac arrest chest compressions")
    assert isinstance(vec, list)
    assert len(vec) == 384
    # Check normalization
    import numpy as np
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 0.05

def test_sparse_embedding_generation():
    engine = get_embedding_engine()
    indices, values = engine.embed_sparse("Epinephrine EpiPen 0.3mg auto-injector")
    assert isinstance(indices, list)
    assert isinstance(values, list)
    assert len(indices) == len(values)
    assert len(indices) > 0

def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert abs(EmbeddingEngine.cosine_similarity(v1, v2) - 1.0) < 1e-4
    assert abs(EmbeddingEngine.cosine_similarity(v1, v3) - 0.0) < 1e-4
