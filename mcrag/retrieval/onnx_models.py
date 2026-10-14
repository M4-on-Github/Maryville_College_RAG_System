"""int8 ONNX versions of the two local models, for hosts too small for torch.

The served pipeline's query embedder (`BAAI/bge-base-en-v1.5`) and refusal
gate (`cross-encoder/ms-marco-MiniLM-L-6-v2`) need ~1.7 GB with torch loaded.
These classes run the same two networks, exported by `scripts/export_onnx.py`
and quantized to int8, in onnxruntime -- no torch, no sentence-transformers.

They are NOT numerically identical to the torch models (int8 rounding), so the
torch path stays the default; a process opts in by setting `MCRAG_ONNX_DIR`
to the export directory. `scripts/compare_onnx.py` measures the difference.
"""

from __future__ import annotations

import contextlib
import ctypes
import gc
import os
import threading
from pathlib import Path

import numpy as np

from mcrag.interfaces import Embedder

ENV_VAR = "MCRAG_ONNX_DIR"
# "1" = hold at most one model in memory: load it for a call, release it after.
# Costs a model load per question; buys ~the smaller model's footprint back.
ONE_AT_A_TIME_VAR = "MCRAG_ONNX_ONE_AT_A_TIME"
_ONE_AT_A_TIME_LOCK = threading.Lock()
MAX_LENGTH = 512
# Batches stay small so a long candidate list never inflates activation memory
# the way one 50x512 batch would.
BATCH = 8


def onnx_dir() -> Path | None:
    """The export directory if this process opted in, else None (use torch)."""
    raw = os.environ.get(ENV_VAR, "").strip()
    return Path(raw) if raw else None


class _Session:
    """One ONNX model plus its tokenizer, loaded on first use."""

    def __init__(self, directory: Path, stem: str) -> None:
        self._directory = directory
        self._stem = stem
        self._session = None
        self._tokenizer = None

    def _load(self):
        if self._session is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            options = ort.SessionOptions()
            # The arena keeps freed activation buffers around for reuse; on a
            # 512 MB host that retained memory is worth more than the speed.
            options.enable_cpu_mem_arena = False
            options.intra_op_num_threads = 1
            self._session = ort.InferenceSession(
                str(self._directory / f"{self._stem}.onnx"), options, providers=["CPUExecutionProvider"]
            )
            tokenizer = Tokenizer.from_file(str(self._directory / f"{self._stem}.tokenizer.json"))
            tokenizer.enable_truncation(MAX_LENGTH)
            tokenizer.enable_padding()
            self._tokenizer = tokenizer
        return self._session, self._tokenizer

    def _release(self) -> None:
        self._session = None
        self._tokenizer = None
        gc.collect()
        try:  # hand freed heap pages back to the OS (glibc only)
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except OSError:
            pass

    @contextlib.contextmanager
    def held(self):
        """Hold this model for a whole embed/score call; in one-at-a-time mode,
        serialize against the other model and release this one on exit, so a
        50-pair call loads the model once, not once per batch."""
        if os.environ.get(ONE_AT_A_TIME_VAR) != "1":
            yield
            return
        with _ONE_AT_A_TIME_LOCK:
            try:
                yield
            finally:
                self._release()

    def run(self, items) -> np.ndarray:
        session, tokenizer = self._load()
        encodings = tokenizer.encode_batch(items)
        features = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
        }
        wanted = {i.name for i in session.get_inputs()}
        return session.run(None, {k: v for k, v in features.items() if k in wanted})[0]


class OnnxBgeEmbedder(Embedder):
    """bge-base-en-v1.5: CLS token, L2-normalized -- what sentence-transformers does."""

    dim = 768

    def __init__(self, directory: Path) -> None:
        self._model = _Session(directory, "bge")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        with self._model.held():
            for start in range(0, len(texts), BATCH):
                cls = self._model.run(texts[start : start + BATCH])[:, 0]
                norm = np.linalg.norm(cls, axis=1, keepdims=True)
                out.extend((cls / np.maximum(norm, 1e-12)).tolist())
        return out


class OnnxCrossEncoderScorer:
    """Raw relevance logits for (query, passage) pairs -- `score_pairs` only.

    The refusal gate calls nothing else, so this does not implement `rerank`.
    """

    def __init__(self, directory: Path) -> None:
        self._model = _Session(directory, "ce")

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        with self._model.held():
            for start in range(0, len(pairs), BATCH):
                logits = self._model.run(pairs[start : start + BATCH])
                scores.extend(float(s) for s in logits[:, 0])
        return scores
