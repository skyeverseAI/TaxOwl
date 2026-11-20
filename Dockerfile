# The recipe Google Cloud Run follows to run taxowl (Docker, because the project needs Python 3.14).
# Built by Cloud Build (amd64, not on the ARM Mac). Run: streamlit on $PORT, the port Cloud Run gives (8080).
# The store (data/chroma) is NOT in the image: app.py downloads it at start (store.ensure_store).

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

# Not root: a plain user 1000 runs the app, and owns the app folder (the store is written there)
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
RUN chown user:user /home/user/app
USER user

# No Streamlit file watcher on the server: it walks every imported module (all of transformers)
# on each run, which was slow and logged errors. Code never changes in a running container.
ENV HOME=/home/user \
    PATH=/home/user/app/.venv/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TAXOWL_LOCAL=0 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 1. Libraries only: the app's, not ingest / eval / local (--no-default-groups). Linux gets CPU-only torch.
#    A layer of its own, so a code-only push doesn't reinstall them.
COPY --chown=user pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-default-groups --no-install-project

# 2. bge-m3 (~2.2 GB) downloaded now, into the image: otherwise every cold start (Cloud Run scales to 0)
#    downloads it again (the first question took 101 s). Same loader the embedder uses.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', device='cpu')"

# 3. Our code last: it changes most often, and steps 1-2 stay cached
COPY --chown=user . .
RUN uv sync --frozen --no-default-groups

# Shell form, so ${PORT} is filled in; 8080 when run by hand
CMD streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true
