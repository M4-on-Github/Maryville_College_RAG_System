# Deploying the chat bot

`scripts/serve_chat.py` serves `clients/chat.html` and the real pipeline from one
process. GitHub Pages cannot host it (static files only); `render.yaml` and the
`Dockerfile` run it as a container on Render.

## What the container needs

- **`OLLAMA_API_KEY`**, as an environment variable in the host's dashboard. It is
  not in the repo (`.env` is gitignored) and not in the image.
- **~2 GB of RAM**: torch, `BAAI/bge-base-en-v1.5` and the MiniLM cross-encoder.
  Free and 512 MB plans are likely to be killed at startup.
- **The data bundle** in `deploy/data/`: the 2,969 chunks and the LanceDB vector
  table the pipeline loads. It is committed because `corpus/` and `indexes/` are
  gitignored. It is a snapshot; it does not follow the maintenance job's crawl.

## Deploy on Render

1. New > Blueprint > pick this repo; Render reads `render.yaml`.
2. Set `OLLAMA_API_KEY` when prompted.
3. First build downloads the models into the image and takes several minutes.

## Spend protection

`/ask` is public and each question can spend generation quota. `serve_chat.py`
limits it per client (`MCRAG_RATE_PER_MIN`, default 6) and per day across all
clients (`MCRAG_DAILY_CAP`, default 300). The counters are in memory: they reset
on restart and are not shared between replicas, so run one instance.

## Local

    python scripts/serve_chat.py        # http://127.0.0.1:8099/
