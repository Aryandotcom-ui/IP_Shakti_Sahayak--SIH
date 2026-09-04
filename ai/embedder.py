"""Embedding backends.

`SentenceTransformerEmbedder` is what ships. `HashingEmbedder` exists so
the pipeline, its tests and CI can run on a machine with no model
weights and no network — it produces stable vectors of the right shape
but is *not* semantically meaningful, so `get_embedder` refuses to fall
back to it unless explicitly allowed.

Model choice: bge-small-en-v1.5 (384-dim, ~130MB). It is close to
e5-small on retrieval benchmarks, runs on CPU, and its asymmetric
query/passage prefixes matter for us — documents are indexed with
`passage: ` and queries with `query: ` at search time. Whatever you
pick, the retrieval service must use the *same* model and the *same*
prefix convention or the vectors are meaningless.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Protocol, Sequence

log = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


class Embedder(Protocol):
    name: str
    dimension: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Real embeddings. Imports torch lazily so the rest of the package
    stays importable on machines without it."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = 32,
        device: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        self.dimension = int(
            self._model.get_sentence_embedding_dimension()
        )
        log.info("loaded %s (%d-dim)", model_name, self.dimension)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [PASSAGE_PREFIX + t for t in texts]

        vectors = self._model.encode(
            prefixed,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(prefixed) > 200,
            convert_to_numpy=True,
        )

        return [v.tolist() for v in vectors]

    def encode_query(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [QUERY_PREFIX + t for t in texts]
        vectors = self._model.encode(
            prefixed,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]

class HashingEmbedder:
    """Deterministic bag-of-words hashing. Offline stand-in only."""

    def __init__(self, dimension: int = 384) -> None:
        self.name = f"hashing-{dimension}"
        self.dimension = dimension

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dimension
            for token in text.lower().split():
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                idx = struct.unpack("<Q", digest)[0] % self.dimension
                vec[idx] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out

    def encode_query(self, texts: Sequence[str]) -> list[list[float]]:
        # BUG FIX: VectorStore.query() (store.py) always calls
        # embedder.encode_query(), but this class previously only
        # implemented encode(). That meant the retrieval/query path had
        # no offline fallback at all, even though ingestion already
        # supports --allow-fallback-embeddings. HashingEmbedder has no
        # query/passage asymmetry (unlike the real model's prefixes), so
        # this is just an alias — it exists so retrieval plumbing can be
        # exercised without network access, same as ingestion already
        # allows. Never use this for a real answer — see the module
        # docstring.
        return self.encode(texts)


class TfidfEmbedder:
    """Offline embeddings that are actually about the words in the text.

    Why this exists alongside HashingEmbedder: the hashing fallback is
    deliberately meaningless, so an index built with it cannot be used to
    answer anything. On a machine that cannot reach the model host — an
    air-gapped deployment, a demo venue, a sandbox with an egress policy —
    that leaves no way to build a *usable* index at all. TF-IDF over
    character n-grams is crude next to a sentence-transformer, but it is
    directionally semantic: it puts "patentability" near "patented", which
    is enough to retrieve the right section far more often than chance.
    ai/person_b_retrieval/embeddings.py already relies on that property.

    The catch, and the reason this class carries state the others do not:
    TF-IDF has no fixed vector space. The vocabulary is learned from the
    corpus, so a query can only be compared against the index if it is
    transformed by the *same fitted vectorizer*. Fit once at ingest, save
    it beside the Chroma index, and load it at query time. Encoding a
    query against a differently-fitted vectorizer silently produces
    coordinates in another space and retrieval degrades to noise without
    raising anything — so `encode`/`encode_query` refuse to run unfitted
    rather than let that happen.

    Not the shipping default. `SentenceTransformerEmbedder` remains that;
    this is what you reach for when the weights are genuinely unreachable.
    """

    #: Where the fitted vectorizer is persisted, relative to the Chroma dir.
    ARTIFACT_NAME = "tfidf-vectorizer.joblib"

    def __init__(self, dimension: int = 384) -> None:
        self.name = f"tfidf-{dimension}"
        self.dimension = dimension
        self._vec = None
        self._svd = None

    # -- lifecycle ------------------------------------------------------

    @property
    def fitted(self) -> bool:
        return self._vec is not None and self._svd is not None

    def fit(self, texts: Sequence[str]) -> "TfidfEmbedder":
        """Learn the vocabulary, then project to a fixed width.

        Chroma needs every vector in a collection to have the same
        dimension, and a raw TF-IDF matrix is as wide as the vocabulary.
        TruncatedSVD reduces it to `dimension` — that is latent semantic
        analysis, which also buys a little synonym tolerance over raw
        term matching.
        """
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        # min_df=2 drops terms seen in only one document, which is useful
        # noise control on a real corpus and destructive on a small one —
        # on a handful of texts it can strip the vocabulary to a single
        # feature, below what TruncatedSVD will accept. Only filter once
        # there is enough corpus for "rare" to mean anything.
        self._vec = TfidfVectorizer(
            analyzer="char_wb",      # survives the morphology of legal English
            ngram_range=(3, 5),
            min_df=2 if len(texts) >= 50 else 1,
            max_features=60000,
            sublinear_tf=True,
        )
        matrix = self._vec.fit_transform(texts)
        # SVD cannot ask for more components than the matrix has rows or
        # columns. On a tiny corpus min_df can collapse the vocabulary to
        # almost nothing, so floor at 1 rather than letting a computed 0
        # reach TruncatedSVD as an opaque parameter error.
        n = max(1, min(self.dimension, matrix.shape[1] - 1, matrix.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=n, random_state=0)
        self._svd.fit(matrix)
        self.dimension = n
        self.name = f"tfidf-{n}"
        log.info("fitted TF-IDF embedder on %d texts -> %d dims", len(texts), n)
        return self

    def save(self, directory) -> None:
        import joblib
        from pathlib import Path

        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vec": self._vec, "svd": self._svd, "dim": self.dimension},
                    path / self.ARTIFACT_NAME)
        log.info("saved TF-IDF vectorizer to %s", path / self.ARTIFACT_NAME)

    @classmethod
    def load(cls, directory) -> "TfidfEmbedder":
        import joblib
        from pathlib import Path

        blob = joblib.load(Path(directory) / cls.ARTIFACT_NAME)
        emb = cls(dimension=blob["dim"])
        emb._vec, emb._svd = blob["vec"], blob["svd"]
        emb.name = f"tfidf-{blob['dim']}"
        return emb

    # -- encoding -------------------------------------------------------

    def _transform(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.fitted:
            raise RuntimeError(
                "TfidfEmbedder used before fit(). A query encoded against an "
                "unfitted vectorizer lands in a different vector space than "
                "the index, which degrades retrieval to noise silently. Call "
                "fit() during ingest and load() the saved artifact at query time."
            )
        reduced = self._svd.transform(self._vec.transform(texts))
        out = []
        for row in reduced:
            norm = float((row @ row) ** 0.5) or 1.0
            out.append([float(v) / norm for v in row])
        return out

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return self._transform(texts)

    def encode_query(self, texts: Sequence[str]) -> list[list[float]]:
        # No query/passage asymmetry here: unlike bge-*, there are no
        # prefixes to honour, and the same fitted space serves both sides.
        return self._transform(texts)


def get_embedder(
    model_name: str = DEFAULT_MODEL,
    *,
    allow_fallback: bool = False,
    device: str | None = None,
) -> Embedder:
    # An explicit request for the offline backend is not a "fallback" and
    # should not warn like one — it is a deliberate choice for a machine
    # that cannot reach the model host.
    if model_name == "tfidf":
        return TfidfEmbedder()
    try:
        return SentenceTransformerEmbedder(model_name, device=device)
    except Exception as exc:
        if not allow_fallback:
            raise RuntimeError(
                f"could not load embedding model {model_name!r} ({exc}). "
                "Install sentence-transformers and download the weights, or pass "
                "--allow-fallback-embeddings to run with placeholder vectors "
                "(useful for schema/plumbing tests, useless for retrieval)."
            ) from exc
        log.warning(
            "FALLING BACK to hashing embeddings (%s unavailable: %s). "
            "Retrieval quality will be meaningless — do not ship this index.",
            model_name, exc,
        )
        return HashingEmbedder()
