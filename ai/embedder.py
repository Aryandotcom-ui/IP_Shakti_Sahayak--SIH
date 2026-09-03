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


def get_embedder(
    model_name: str = DEFAULT_MODEL,
    *,
    allow_fallback: bool = False,
    device: str | None = None,
) -> Embedder:
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
