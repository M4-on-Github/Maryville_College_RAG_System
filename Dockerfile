# Free-tier image: no torch at runtime. The two models are exported to int8
# ONNX in a build stage and only onnxruntime ships (see mcrag/retrieval/onnx_models.py).
# The full-precision torch image is Dockerfile.torch (needs ~2 GB RAM).

FROM python:3.11-slim AS export
WORKDIR /build
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=/build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "transformers<5" onnx onnxruntime
COPY scripts/export_onnx.py ./scripts/export_onnx.py
RUN python scripts/export_onnx.py --out /build/onnx_models

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=/app MCRAG_ONNX_DIR=/app/onnx_models MCRAG_ONNX_ONE_AT_A_TIME=1

# Runtime deps only -- deliberately not ".[index]", which pulls sentence-transformers and torch.
RUN pip install --no-cache-dir onnxruntime tokenizers numpy lancedb rank-bm25 fastapi "uvicorn[standard]" httpx
COPY pyproject.toml ./
COPY mcrag ./mcrag
RUN pip install --no-cache-dir .
COPY --from=export /build/onnx_models ./onnx_models

COPY scripts/serve_chat.py ./scripts/serve_chat.py
COPY clients/chat.html ./clients/chat.html
COPY configs ./configs
COPY data ./data
# The exact data the served pipeline loads (see mcrag/retrieval/frozen_pipeline.py).
COPY deploy/data/baseline_chunks_no_boilerplate.jsonl ./corpus/baseline_chunks_no_boilerplate.jsonl
COPY deploy/data/baseline_dense_no_boilerplate ./indexes/baseline_dense_no_boilerplate

# OLLAMA_API_KEY comes from the host's environment, never from the image.
# PORT is set by the host (Render uses 10000).
CMD ["python", "scripts/serve_chat.py", "--host", "0.0.0.0"]
