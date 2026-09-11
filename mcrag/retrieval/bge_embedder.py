"""The production `Embedder`: local `bge-base-en-v1.5` via sentence-transformers.

No models run locally except embedding and reranking (standing project
constraint) — generation is Ollama Cloud. Lazy-loaded: the model is fetched
and put on device the first time `embed` is called, not in `__init__`, so
constructing one (e.g. to read `.dim`) never touches the network or a GPU.
"""

from __future__ import annotations

from mcrag.interfaces import Embedder

MODEL_NAME = "BAAI/bge-base-en-v1.5"


class BgeEmbedder(Embedder):
    dim = 768

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()
