import logging
import hashlib
import numpy as np
from typing import List, Tuple, Dict, Any, Optional

logger = logging.getLogger("lifeline.embeddings")

class EmbeddingEngine:
    """
    Edge embedding engine providing:
    1. Local dense 384-dimensional ONNX vectors (bge-small-en-v1.5)
    2. Local sparse BM25 vectors for exact keyword matching (drug names, dosages, AED/CPR terms)
    3. Deterministic offline fallback if neural weights cannot be loaded
    """
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", sparse_model_name: str = "Qdrant/bm25"):
        self.model_name = model_name
        self.sparse_model_name = sparse_model_name
        self.dense_dim = 384
        self._dense_model = None
        self._sparse_model = None
        self._init_models()

    def _init_models(self):
        try:
            from fastembed import TextEmbedding, SparseTextEmbedding
            logger.info("Initializing local FastEmbed dense model (%s)...", self.model_name)
            self._dense_model = TextEmbedding(model_name=self.model_name)
            logger.info("Initializing local FastEmbed sparse BM25 model (%s)...", self.sparse_model_name)
            self._sparse_model = SparseTextEmbedding(model_name=self.sparse_model_name)
            logger.info("FastEmbed dense and sparse models ready.")
        except Exception as ex:
            logger.warning("Failed to initialize FastEmbed (%s). Falling back to deterministic vectorizer.", ex)
            self._dense_model = None
            self._sparse_model = None

    def embed_text(self, text: str) -> List[float]:
        """Generates a normalized 384-dim dense vector."""
        if not text:
            return [0.0] * self.dense_dim

        if self._dense_model is not None:
            try:
                embeddings = list(self._dense_model.embed([text]))
                if embeddings:
                    vec = embeddings[0]
                    # Normalize vector
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                    return vec.tolist()
            except Exception as e:
                logger.error("Dense embedding generation error: %s. Using fallback.", e)

        return self._fallback_dense_vector(text)

    def embed_sparse(self, text: str) -> Tuple[List[int], List[float]]:
        """Generates sparse BM25 indices and values."""
        if not text:
            return [], []

        if self._sparse_model is not None:
            try:
                sparse_embeddings = list(self._sparse_model.embed([text]))
                if sparse_embeddings:
                    se = sparse_embeddings[0]
                    return se.indices.tolist(), se.values.tolist()
            except Exception as e:
                logger.error("Sparse embedding generation error: %s. Using fallback.", e)

        return self._fallback_sparse_vector(text)

    def embed_query_hybrid(self, text: str) -> Tuple[List[float], Tuple[List[int], List[float]]]:
        """Returns both dense and sparse representations for hybrid retrieval."""
        dense = self.embed_text(text)
        sparse = self.embed_sparse(text)
        return dense, sparse

    def _fallback_dense_vector(self, text: str) -> List[float]:
        """Deterministic pseudo-dense projection for offline zero-dependency safety."""
        vec = np.zeros(self.dense_dim, dtype=np.float32)
        words = text.lower().split()
        for idx, word in enumerate(words):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            pos = h % self.dense_dim
            sign = 1.0 if (h >> 4) % 2 == 0 else -1.0
            vec[pos] += sign * (1.0 / (idx + 1)**0.5)

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def _fallback_sparse_vector(self, text: str) -> Tuple[List[int], List[float]]:
        """Deterministic bag-of-words sparse representation."""
        import re
        tokens = re.findall(r'\b[a-zA-Z0-9_\-]{2,}\b', text.lower())
        token_freq: Dict[int, float] = {}
        for tok in tokens:
            idx = int(hashlib.sha256(tok.encode()).hexdigest()[:8], 16) % 100000
            token_freq[idx] = token_freq.get(idx, 0.0) + 1.0

        indices = sorted(token_freq.keys())
        values = [token_freq[i] for i in indices]
        return indices, values

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

_global_embedding_engine: Optional[EmbeddingEngine] = None

def get_embedding_engine() -> EmbeddingEngine:
    global _global_embedding_engine
    if _global_embedding_engine is None:
        _global_embedding_engine = EmbeddingEngine()
    return _global_embedding_engine
