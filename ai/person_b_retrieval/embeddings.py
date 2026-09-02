"""
Embedding abstraction.

NOTE FOR INTEGRATION: this environment can't download Sentence Transformer model
weights (no internet access to huggingface.co), so this stand-in uses TF-IDF +
cosine similarity to build and test the real retrieval/confidence logic offline.

The only thing that needs to change when you swap in the real model is the body
of `Embedder.fit()` and `Embedder.embed()`. Nothing in retrieval.py or
confidence.py needs to change, because they only call `embedder.embed(texts)`
and use cosine similarity on whatever vectors come back.

To swap in the real thing later:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    vectors = model.encode(texts)
"""

from typing import List
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class Embedder:
    """Fit on a corpus once, then embed any text (including new queries) into
    the same vector space. Swap the internals for a real sentence-embedding
    model when one is available; the public interface stays the same."""

    def __init__(self) -> None:
        # Character n-grams (not word-level) so that "patented", "patent",
        # and "patentability" still match each other reasonably well —
        # word-level TF-IDF treats those as unrelated tokens and misses
        # obviously-relevant chunks. Swap for a real sentence-embedding
        # model later; this is just an offline stand-in.
        self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self._fitted = False

    def fit(self, corpus_texts: List[str]) -> None:
        self._vectorizer.fit(corpus_texts)
        self._fitted = True

    def embed(self, texts: List[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("Embedder.fit() must be called before embed().")
        return self._vectorizer.transform(texts).toarray()


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (n, d), b: (m, d) -> similarity matrix (n, m)."""
    return cosine_similarity(a, b)
