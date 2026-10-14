FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=/app HF_HOME=/opt/hf

# CPU-only torch first: the default wheel drags in several GB of CUDA libraries.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY mcrag ./mcrag
RUN pip install --no-cache-dir ".[index,scoring,service]"

# Bake the two models into the image so a restart does not re-download ~0.5 GB.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-base-en-v1.5'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

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
