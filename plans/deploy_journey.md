# Deploy journey (v1, 2026-11-19)

How taxowl went online: what was built, the choices made and why, and what went wrong on the way.
For the walkthrough. Checklist written earlier: `plans/deploy_checklist.md`.

## The shape

```
 git repo (code only)                       private HF dataset stark7039/taxowl-store
      │ gcloud run deploy --source .              (data/chroma, 124 MB)
      ▼                                                 │
 Cloud Build: Dockerfile → image (~5 GB)               │ downloaded at start
      ▼                                                 ▼
 Artifact Registry ──▶ Cloud Run service "taxowl" (us-central1) ──▶ streamlit app.py
                          4 GiB, 2 CPU, 0..1 instances      keys from Secret Manager
```

## Decisions (and why)

| decision | why |
|---|---|
| Docker | the project needs Python 3.14; a Docker image fixes the version, whatever the host offers |
| store NOT in git or the image; private HF dataset, downloaded at start (`store.ensure_store()`) | the chunks hold the source text, including the ICAI Rules book, which we don't re-host. Updating the store = re-upload, no rebuild |
| dataset name from env `TAXOWL_STORE_REPO`, not in code | no person-specific values in code; anyone can point it at their own store |
| `huggingface_hub` directly, not LangChain | it's a file download; LangChain has nothing for that |
| bge-m3 downloaded at BUILD time, baked into the image | otherwise every cold start downloads 2.2 GB (the first question once took 101 s) |
| model loads on page open, not on "Ask" | it loads while the user types |
| kept bge-m3, not bge-small | it won on the test set (hit@5 0.81 vs 0.69, "leans, not proven"); the only reason to drop it was RAM, and the host has enough. Hinglish was NOT fixed by it (1/3 both) |
| `uv sync --no-default-groups` + CPU-only torch on Linux | no ingest/eval/Ollama libraries and no NVIDIA packages on the server |
| app runs as a non-root user | standard container practice |
| keys in Secret Manager, a separate OpenRouter key with a $5 limit, a READ-only HF token | a leaked server key can cost at most $5 and can't change the HF repos |
| `--max-instances 1`, `--min-instances 0` | a hard cost cap; nothing runs (or bills) when nobody visits |
| `--session-affinity`, `--timeout 3600` | Streamlit keeps a websocket open per user |
| region us-central1 | the free tier's free outbound data is from North America only |
| `.dockerignore` + `.gcloudignore` | gcloud uploads by `.gcloudignore`, Docker copies by `.dockerignore`: both keep out data/, PDFs, .env and notes |

## Host: how we ended on Cloud Run

1. **Hugging Face Spaces (free CPU, 16 GB)** was the plan. On the day, HF's free tier allowed only
   Gradio + ZeroGPU: Docker Spaces need PRO ($9/month). Lesson: check the provider's page on the day.
2. Options weighed: HF PRO ($9/month, zero extra work), Oracle Always Free (free, run your own VM),
   Streamlit Cloud (free, but too little RAM for bge-m3 without an embedding API).
3. **Chosen: Google Cloud Run.** Free trial ($300, 90 days, no auto-charge after) + always-free tier
   (360,000 GiB-seconds and 180,000 vCPU-seconds a month, 2,500 Cloud Build minutes). Same Dockerfile.
   Cloud Build builds the image on Google (amd64), so the ARM Mac's architecture doesn't matter.
   Expected cost after the trial: ~$0.5/month for image storage, if traffic stays in the free tier.

## Steps done

1. HF account + write token, `hf auth login` (in a separate terminal: the in-chat `!` can't take input).
2. `hf repos create stark7039/taxowl-store --repo-type dataset --private`, then `hf upload` of data/chroma.
3. Code: `ensure_store()`, app.py, Dockerfile, ignore files (commit 6604f4d).
4. Privacy check of git history before any upload: no data/, PDFs, .env, keys or large files ever
   committed. Old commits carry a personal email; already public on GitHub, accepted.
5. Google Cloud: project `taxowl-515202`, budget alert, gcloud CLI, enabled run, cloudbuild,
   artifactregistry, secretmanager.
6. Secrets `openrouter-key`, `tavily-key`, `hf-token` (entered with `read -s`, never on the command line,
   so they aren't in shell history). The compute service account got `secretmanager.secretAccessor`.
7. `gcloud run deploy taxowl --source . ...` (command in the README / below).

## What went wrong, and the fix

| problem | fix |
|---|---|
| an HF token was pasted into the chat | treated as leaked: deleted, a new one made and entered only in the terminal |
| `! hf auth login` → "Aborted!" | the in-chat shell has no keyboard input; ran it in a normal terminal |
| HF free tier: Docker is paid | moved to Cloud Run (above) |
| the HF token went into `tavily-key` by mistake | `gcloud secrets versions add` with the right key, then `versions destroy 1` |
| `--set-secrets: expected one argument` | the long line broke while pasting; the three secrets went into shell variables S1-S3 |
| Cloud Build 403 `storage.objects.get` | new projects don't give the compute service account build rights: granted `roles/cloudbuild.builds.builder` |
| live app: `cloud model failed: User not found` | OpenRouter's "bad key" error. The stored key was 46 characters, not 73: cut short while copying. New key (copied with the Copy button), new secret version, v1 destroyed, `gcloud run services update` for a new revision. Check without printing the key: its length and prefix |
| logs full of `ModuleNotFoundError: torchvision` tracebacks; first search 26-31 s | Streamlit's file watcher walks every imported module (all of `transformers`) on each run. Off on the server: `STREAMLIT_SERVER_FILE_WATCHER_TYPE=none` (set with `--update-env-vars`, and in the Dockerfile for the next build) |
| `gcloud run services update` asked "Service name:" | the pasted line broke again; env values went into shell variables E1, E2 |

## The deploy command

```
S1=OPENROUTER_API_KEY=openrouter-key:latest
S2=TAVILY_API_KEY=tavily-key:latest
S3=HF_TOKEN=hf-token:latest
gcloud run deploy taxowl \
  --source . --region us-central1 \
  --memory 4Gi --cpu 2 --cpu-boost \
  --min-instances 0 --max-instances 1 \
  --timeout 3600 --session-affinity \
  --allow-unauthenticated \
  --set-env-vars TAXOWL_STORE_REPO=stark7039/taxowl-store \
  --set-secrets "$S1,$S2,$S3"
```

## First run (2026-11-19, revision taxowl-00003)

Build: ~11 min on Cloud Build. URL: https://taxowl-l5bv4gb4wa-uc.a.run.app (health check 200).

| question | sources found in | answer | checks |
|---|---|---|---|
| What does section 16(4) say about the time limit for ITC? | 31.2 s | right: 30 November limit, quotes [S1] s16(4), adds the RCM point | passed |
| Do I need an e-way bill to move goods? | 95.6 s | partly: the exceptions are right, but the main condition (value over ₹50,000, rule 138(1)) is missing; that sub-rule was not retrieved | passed |
| What is the GST rate on cement? | 3.7 s | right (18%, web + official), but wrote "S1" instead of "[S1]" | failed: cites_or_refuses (the check caught it) |
| What is the income tax rate for companies? | 5.6 s | refused, as it should | passed |

The model part is fast everywhere (0.8-4.1 s, first word 0.6-2.2 s, about ₹0.06 a question).

What this shows:
- **Search time swings from 4 s to 96 s.** Cause not found yet; to look into next (logs: CPU, memory, first query after start).
- Retrieval gap on broad questions (e-way bill): the main sub-rule is missed. For v1.1 (parent doc retrieval).
- On web answers the model can drop the [S#] format. The check flags it; the prompt may need a firmer rule.
- An out-of-scope question (income tax) still ran a web search: costs a little, the answer is still right.

## Cold start (why the first question was slow)

Revision 00003, from the logs: instance start 04:33:41 → Streamlit ready 04:35:18 (97 s) → store
download 2 s → bge-m3 loaded 04:36:27 (53 s) → first search 95.6 s. Later searches 1.8-5.6 s, and a
whole answer about 5 s. Cloud Run pulls files from the 5 GB image only when they are first read, so
everything "first" is slow. It happens after a deploy and after ~15 min with no visitors
(`--min-instances 0`).

Not a free-vs-paid problem: it's the trade-off we chose (pay nothing when idle, wait when waking up),
made worse by a heavy app (torch + a 2.2 GB model). A light app wakes in seconds on the same setup.

| option | effect | decision |
|---|---|---|
| warm-up query at page open | moves the wait, doesn't shorten it | dropped |
| `--min-instances 1` always | no cold start, ~$115/month | no |
| `--min-instances 1` only around a demo | no cold start while it's on, about ₹13 an hour from the trial credit | yes |
| a lighter model / embedding API | shorter cold start; needs the retriever eval again | v1.1 |

Done in app.py: a caption warns that the first visit can take minutes, and one `[taxowl]` log line per
step (load time, sources time, answer time, failed checks, errors). The question text is never logged.

Before a demo, then after it:
```
gcloud run services update taxowl --region us-central1 --min-instances 1
gcloud run services update taxowl --region us-central1 --min-instances 0
```
Read the log lines:
```
gcloud logging read 'textPayload:"[taxowl]"' --limit 20 --format="value(timestamp,textPayload)"
```

## Still to do

- Deploy the app.py change (caption + log) and check the log lines.
- Auto-deploy from GitHub (CI step).
- Later: rotate the Tavily key (its value showed up in an editor selection shared with the assistant).
