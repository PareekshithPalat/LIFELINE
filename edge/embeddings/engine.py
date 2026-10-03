import os
import threading
import logging
from typing import List, Tuple, Optional
import numpy as np
from qdrant_edge import Bm25, Bm25Config, SparseVector
from edge.config import get_settings, get_retrieval_config

logger = logging.getLogger("lifeline.embeddings")


class EmbeddingEngine:
    """
    Edge embedding engine:
    1. Dense 384-d vectors from the local ONNX bge-small-en-v1.5 model (FastEmbed).
    2. Sparse BM25 vectors from Qdrant Edge's own Bm25 model, so the token ids match
       the shard's IDF index exactly (and the mobile implementation, which is tested
       for parity against this one).

    There is deliberately no pseudo-dense fallback: vectors from a different space
    would silently corrupt similarity scores. If the dense model cannot be loaded the
    engine reports dense_available=False and retrieval runs in a stricter
    lexical-only mode.
    """

    def __init__(self, model_name: Optional[str] = None, cache_dir: Optional[str] = None):
        cfg = get_retrieval_config()
        self.model_name = model_name or cfg["dense_model"]
        self.dense_dim = cfg["dense_dim"]
        self.cache_dir = cache_dir or get_settings().models_path
        bm = cfg["bm25"]
        self._bm25 = Bm25(Bm25Config(language=bm["language"], k=bm["k"], b=bm["b"], avg_len=bm["avg_len"]))
        self._dense_model = None
        self._lock = threading.Lock()
        self._init_dense()

    def _init_dense(self):
        try:
            from fastembed import TextEmbedding
            os.makedirs(self.cache_dir, exist_ok=True)
            logger.info("Loading dense model %s (cache: %s)", self.model_name, self.cache_dir)
            self._dense_model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
        except Exception as ex:
            logger.error("Dense model unavailable (%s). Running in lexical-only mode.", ex)
            self._dense_model = None

    @property
    def dense_available(self) -> bool:
        return self._dense_model is not None

    @property
    def model_id(self) -> str:
        return self.model_name if self.dense_available else "none"

    def embed_text(self, text: str) -> Optional[List[float]]:
        return self.embed_texts([text])[0] if text else None

    def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        if not self.dense_available:
            return [None] * len(texts)
        with self._lock:
            vecs = list(self._dense_model.embed(texts))
        out = []
        for v in vecs:
            norm = float(np.linalg.norm(v))
            out.append((v / norm).tolist() if norm > 0 else v.tolist())
        return out

    def embed_sparse_query(self, text: str) -> SparseVector:
        return self._bm25.embed_query(text)

    def embed_sparse_document(self, text: str) -> SparseVector:
        return self._bm25.embed_document(text)

    def embed_query_hybrid(self, text: str) -> Tuple[Optional[List[float]], SparseVector]:
        return self.embed_text(text), self.embed_sparse_query(text)

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        a = np.asarray(v1, dtype=np.float32)
        b = np.asarray(v2, dtype=np.float32)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))


_global_embedding_engine: Optional[EmbeddingEngine] = None
_engine_lock = threading.Lock()


def get_embedding_engine() -> EmbeddingEngine:
    global _global_embedding_engine
    with _engine_lock:
        if _global_embedding_engine is None:
            _global_embedding_engine = EmbeddingEngine()
        return _global_embedding_engine
