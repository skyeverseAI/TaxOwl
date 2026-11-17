# Deploy checklist (v1)

Written 2026-11-18 while the pipeline eval ran. Read-only survey: nothing below is done yet.
Each item: what the server needs, what we have today, and a suggested fix. The user decides.

## What has to run on the server

```
browser ──▶ Streamlit (app.py)
              ├─ retriever ── bge-m3 embedder (~2.2 GB download, ~2-3 GB RAM)
              │               └─ Chroma store data/chroma (124 MB)
              ├─ web search ── Tavily (TAVILY_API_KEY)
              └─ answer ────── gpt-4o-mini via OpenRouter (OPENROUTER_API_KEY)
                               (qwen via Ollama: NOT on the server)
```

## 1. Where to host

- bge-m3 needs a few GB of RAM. Small free hosts may not fit it, so check the RAM limit before choosing.
- Python is pinned to `>=3.14`. The host must offer 3.14, or we use a Docker image where we pick the version.
- Suggestion: Hugging Face Spaces with Docker (free CPU tier with plenty of RAM; we pick the Python
  version). Second choice: a small VM. Check each one's current limits before deciding.

## 2. The store has to reach the server

- `data/` is in `.gitignore`, so the repo has no `data/chroma` and no `data/chunks.jsonl`.
- **Copyright:** the store holds the full chunk text, including the ICAI Rules book. Plan rule
  (plans/plan.md): show excerpts with an official link, don't re-host whole documents. A PUBLIC
  copy of the store would re-host them.
- Options:
  a. upload `data/chroma` to a PRIVATE place (a private HF dataset, or a bucket) and download it
     when the app starts, using a secret token;
  b. rebuild it on the server from chunks: this still needs the chunks there, and embedding on a
     CPU is slow.
- Suggestion: (a).

## 3. The app runs the local model too

- Today `app.py` always streams cloud, then local, and retrieves once with the LOCAL budget
  (6000 tokens) for both.
- On the server there is no Ollama. Suggestion: an env switch (e.g. `TAXOWL_LOCAL=0`). With it off,
  the app uses cloud only, with the cloud budget (`BUDGET["cloud"]` = no cap), which is what the
  pipeline eval measured. With it on, the app works as it does now on the Mac.

## 4. Secrets and cost guard

- `load_key()` already reads env vars first, so on the server: `OPENROUTER_API_KEY` and
  `TAVILY_API_KEY` as host secrets (never in git).
- A public app spends our money. Steps: a spending limit on the OpenRouter key; a simple
  per-session question limit in the app. Tavily's free tier is 1000 searches a month; after that,
  `web_sources` must fail cleanly, and then `rate_note` covers it.

## 5. Install size

- Runtime needs only: chromadb, langchain-chroma, langchain-core, langchain-huggingface,
  sentence-transformers, langchain-openrouter, langchain-tavily, streamlit.
- Not needed at runtime: docling, rapidocr, onnxruntime, pymupdf, deepeval, typesafe-sdk,
  langchain-ollama.
- Suggestion: move those into uv dependency groups (`ingest`, `eval`) so the server image is
  smaller and builds faster. The pinned versions stay as they are.

## 6. Cold start

- The first pipeline-eval row took 101 s: the embedder loading. `app.py` already caches the
  store with `st.cache_resource`. Also warm the embedder when the app starts, so the first user
  doesn't wait.

## 7. Before the first push (14 commits not pushed)

- `git ls-files` shows no private files (no `data/private`, `sep_docs`, or `.env`). Good.
- Still to check: the repo's visibility on GitHub, and that no commit message or eval run JSON
  holds anything private. Eval runs hold questions and answers only: public law, no petitions.
  Lesson from LERAGS: one leaked identifier made that whole repo unpublishable.

## Order (suggested)

1. Item 3 (local switch) + item 5 (dependency groups): small code changes, testable on the Mac.
2. Item 7 check, then push.
3. Item 2 (private store upload) + item 1 (host) + item 4 (secrets, limits).
4. Item 6 (warm start); then the public URL answers a query = deploy done (plan.md exit check).
5. CD + quality page.
