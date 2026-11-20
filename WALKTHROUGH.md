# Walkthrough: taxowl v1, stage by stage

A guide to read the whole project in order, in about a day. For each stage:
**read** (files, in order) · **decided** (and why) · **went wrong** · **numbers** · **try** (a command) ·
**change it yourself** (a small edit, to see the stage move).

Built 2026-10-24 → 2026-11-20, 76 commits. `git log --reverse --oneline` is the diary.

```
 0 setup ─► 1 extract ─► 2 split ─► 3 chunk ─► 4 embed+store ─► 5 retrieve ─► 6 validity
                                                                     │
 10 CI/CD ◄─ 9 deploy ◄─ 8 evals ◄─────── 7 answer (generator + checks + web + app) ◄┘
```

Concepts that are new compared to LERAGS / evals_project are marked **NEW**.

---

## 0. Setup and the corpus

**Read:** `plans/plan.md` → `docs/manifest.jsonl` (a few lines) → `scripts/01_download.py`

**Decided:**
- Public law only (CGST Act, Rules, IGST/UTGST Acts, CBIC circulars), so the app and repo can be public.
  Private writ petitions stay in `data/private/` and are used only as a stress test.
- One manifest line per file (source URL, doc_type, number, date): every later stage reads doc_type
  from here, never from the file name.
- Exact versions in `pyproject.toml` + `uv.lock`, installed with `uv sync --frozen`.

**Went wrong:** two library versions underneath Docling changed an OCR score from 84% to 74%. That is
why the pins have comments, and why `uv sync --frozen`.

**Try:** `head -3 docs/manifest.jsonl`

---

## 1. Extraction: PDF → text + tables

**Read:** `plans/extraction_journey.md` (the whole story, 19 steps) → `src/taxowl/schema.py`
(`ExtractedDoc`) → `src/taxowl/ingestion/pipeline.py` → `extract.py` → `tables.py` → `gate.py` →
`ocr.py` → `vlm.py` → `eval_results/check_ingestion.py`

**Decided:**
- PyMuPDF for text pages; our own table finder; a **gate** sends only the hard table pages to a vision
  model (Gemini). Cheaper than a vision model on every page, and more accurate (97.3% vs 95.9%).
- Scans: Docling + RapidOCR (runs on Linux; OcrMac was Mac-only).
- **Held-out sets** (NEW): pages drawn at random by seed, scored once, never used to tune. The gold set
  is what we build against; held-out is the honest score.

**Went wrong:**
- Held-out was 85.6% while gold was 100%: we had over-fit the gold. Tables were the gap.
- "Docling drops paragraph numbers" was our own trial script's bug.
- Private petitions scored 62.6%: scanners put a bad hidden text layer on the page. Fix: re-OCR
  uploads (the corpus's layers are fine).

**Numbers:** held-out 97.3%, fresh held-out 97.7%, corpus scans 94.3%. OCR 3.0 → 1.75 s/page by batching.

**Try:** `uv run eval_results/check_ingestion.py data/ingested` (scores the current output against the gold set)

**Change it yourself:** in `gate.py`, make the gate stricter or looser, re-run the held-out check, and
see the score and the number of vision-model pages move together.

---

## 2. Splitting: ExtractedDoc → Units (one per section, rule, paragraph)

**Read:** `plans/stage2_splitchunk.md` (Part A) → `src/taxowl/splitting/run.py` → `act.py` →
`icai.py` → `circulars.py` → `src/taxowl/config.py`

**Decided:**
- One splitter per document family, chosen by `doc_type`. A legal document has its own structure
  (section → sub-section → clause); a generic text splitter would cut through it.
- Acts from India Code; Rules from the ICAI compilation, whose **footnotes** carry the amendment
  history (used again in stage 6).
- Self-checks on every file (numbers in order, gaps reported as warnings), so a new file can't fail
  silently.

**Went wrong:** omitted rules ("[Omitted]") broke the order; rule 110A needed its own unit; footnotes
had to be found by font size and a rule line, not by text alone.

**Try:** `uv run scripts/03_split_chunk.py` (splits and chunks everything, then prints a summary), then look at one line of `data/units/*.jsonl`.

---

## 3. Chunking: Units → chunks

**Read:** `plans/stage2_splitchunk.md` (Part B) → `src/taxowl/chunking/chunker.py` → `tables.py` → `run.py`

**Decided:**
- At most 400 tokens per chunk (bge reads 510; the heading and labels need room).
- Cut along the law's own lines: dotted paras → sub-sections → clauses → sentences, in that order
  (`LEVELS`). Only a piece with no structure left is cut by length.
- A clause repeats its sub-section's opening words (`LEAD_MAX`), so "(b)" alone still makes sense.
- Tables become Markdown pieces; rows are added until the limit, and the header repeats.

**Numbers:** 4,716 chunks.

**Change it yourself:** set `MAX_TOKENS = 250` in `chunker.py`, re-run the chunker on one Act, and
count the chunks. (Don't rebuild the store with it.)

---

## 4. Embedding and the store

**Read:** `src/taxowl/retrieval/embedder.py` → `store.py` → `scripts/04_embed_store.py`

**Decided:**
- bge-m3 (1024 numbers, multilingual) after a test-set comparison with bge-small (stage 8).
- Chroma via LangChain, cosine, **`ef_search` 500** (NEW: HNSW's search width; the default missed
  chunks that exact search found).
- The model name is in the collection name (`corpus-bge-m3`): vectors from two models can't be mixed,
  and both stores can sit side by side.

**Try:** `uv run python -m taxowl.retrieval.embedder`

---

## 5. Retrieval: exact + by meaning

**Read:** `src/taxowl/retrieval/citations.py` → `lookup.py` → `retriever.py` → `tests/test_citations.py`

```
question ─► read_citations ─► "section 16(4) CGST Act", "Circular 183/15/2022"
               │                    │
               │                    └─► lookup: those chunks, closest first (up to 20)
               └─► by meaning: 8 chunks (withdrawn circulars skipped)
                                    + cited provisions: what the returned circulars cite, current text
```

**Decided:**
- **Exact first.** A lawyer types "section 16(4)"; meaning search alone often ranked it low. A regex
  citation reader is cheap, testable and never makes things up.
- Then always 8 by meaning: the question may need more than what it names. 5 → 8 bought recall
  0.76 → 0.81 for ~700 tokens; 10 bought nothing more.
- "Law assumed": "section 16" with no Act is read as the CGST Act, and the answer says so.

**Went wrong:** the citation reader grew many edge cases (plural sub-sections, "16 to 18", Hinglish
"ke", circular numbers vs dates). Each one became a gold row in `eval_results/gold/citations_*.jsonl`.

**Numbers (TEST set):** hit@5 0.81, MRR 0.65; Hinglish 0.33.

**Try:** `uv run python -c "from taxowl.retrieval.citations import read_citations as r; print(r('sec 16(4) aur rule 36'))"`

**Change it yourself:** add a case to `tests/test_citations.py` that you think should pass, run
`uv run pytest tests/test_citations.py`, and fix `citations.py` if it doesn't.

---

## 6. Validity: is the law still the law?

**Read:** `Evaluations/Validity/Validity.md` → `src/taxowl/validity/detect.py` → `status.py` →
`amended.py` → `answer/pipeline.py` (`label`, `amended_note`)

**Decided:**
- Withdrawn circulars: regex finds "is hereby withdrawn" in circular **bodies**, an LLM judges each
  hit, a person checks. CBIC's own title notes are only the answer key (to measure recall), never input.
- Labels go into chunk metadata; nothing is re-embedded.
- **Code writes the warnings, not the model.** The model ignored the current rule and ignored a "you
  must say" prompt rule, so `amended_note()` adds the ⚠ line itself.

**Numbers:** precision 0.93, recall 0.89; 17 withdrawn, 19 partly modified; traps 1/4.

**Lesson:** where code decides (labels, filters, notes) it works; where the model must reason about
dates, it fails.

---

## 7. Answering: generator, checks, web, app

**Read:** `plans/stage7_generator.md` → `src/taxowl/answer/generator.py` (`SYSTEM_RULES`) →
`pipeline.py` (`answer`) → `check.py` → `web.py` → `app.py` → `owl.py`

```
answer(question)
  get_sources ─► retriever + label() each + web_sources if wants_web()
  generate    ─► gpt-4o-mini, rules in a SYSTEM message, sources as [S1]..[Sn]
  notes       ─► rate_note, amended_note           (code, not model)
  check       ─► every [S#] exists? cites or refuses? no citation the sources lack?
```

**Decided:**
- Refusal is one exact sentence ("The documents I have don't answer this."), so code can recognise it.
- **Free checks** (NEW): `check.py` costs nothing and caught an uncited, self-contradicting answer the
  LLM judge scored 1.0.
- "Keep the exceptions" prompt rule: Completeness 0.89 → 0.99 on gold chunks (cloud). Did nothing for
  the local 7B model.
- Web search (Tavily) only for rate questions: rates live in notifications the corpus doesn't hold.
- Rules moved to a system message after the safety set.
- App: cloud only on the server (`TAXOWL_LOCAL=0`); Ollama is imported only when used.

**Went wrong:** "interest rate" triggers the rate web search; qwen writes "don't answer." without
"this", so `is_refusal()` misses it.

**Try:** `uv run streamlit run app.py` and ask "What does section 16(4) say?", then "GST rate on cement".

**Change it yourself:** add `"interest"` handling to `wants_web()` so "interest kitne rate se" does
NOT search the web; add that question to `tests/test_web.py` first and watch it go red, then green.

---

## 8. Evals: measuring each part, then the whole

**Read:** `QUALITY.md` → `Evaluations/Retriever_Evals/Final.md` → `Generator_Evals/Improvement1.md` →
`Pipeline_Evals/Baseline1.md` → `plans/judge_calibration_plan.md` (Results) → `src/taxowl/evals/`

```
retriever eval   question ─► retriever ─► gold chunk in top 5?           (no LLM needed)
generator eval   GOLD chunks ─► model ─► judge                           (the model alone)
pipeline eval    question ─► whole app ─► judge + blame                  (what the user reads)
safety eval      off-topic / advice / injection
judge calibration  the judge vs Claude vs Codex on 18 hard rows
```

**Decided:**
- Dev set for building, test set touched once. A rule set *before* the test run ("bge-m3 only if 2+
  questions ahead").
- **Blame** (NEW): for each miss, was the gold chunk found? yes → model's fault; no → retriever's.
- DeepEval judge (gpt-4.1-mini), then **calibrate the judge** (NEW): it passed 10 wrong or incomplete
  answers out of 18. So every judge score is an upper bound, and flagged rows are read by hand.

**Numbers:** see QUALITY.md.

**Try:** `uv run python -m taxowl.evals.retriever_eval --gold eval_results/gold/retriever_dev.jsonl --mode full`

---

## 9. Deploy: Cloud Run

**Read:** `plans/deploy_journey.md` (to "Cold start") → `Dockerfile` → `.gcloudignore` → `retrieval/store.py` (`ensure_store`)

**Decided:**
- Cloud Run (scales to zero, pay per use) over a VM; one container from the `Dockerfile`.
- The store is not in the image: it is downloaded at start from a **private** Hugging Face dataset.
  The repo stays public; the data doesn't ship with it.
- Keys in Secret Manager, mounted as env vars. Linux takes CPU-only torch (saves 2–3 GB).
- Dependency groups: the server installs only the app's packages.

**Went wrong:** Cloud Build 403 on the first deploy (missing role); the file watcher on the server;
a slow first question (cold start: loading bge-m3), now shown with the owl and a caption.

---

## 10. CI/CD: tests on every push, deploy on main

**Read:** `tests/` (4 files) → `pyproject.toml` (`[tool.pytest…]`, `[tool.ruff…]`, `[tool.uv]`) →
`.github/workflows/ci.yml` → `plans/deploy_journey.md` "Automatic deploys"

```
push ─► GitHub runner (fresh Ubuntu) ─► uv sync app+dev ─► ruff ─► pytest
                                                                   │ pass + main
                                                                   ▼
                     GitHub ID token ─► Google WIF ─► github-deployer ─► gcloud run deploy
```

**Decided:**
- Tests only for pure functions (citations, labels, checks, web routing): fast, no store, no key.
  Evals stay manual: they cost money and need the private store.
- ruff rules listed out and ruff version pinned, so a new ruff can't turn CI red by itself.
- One uv version (0.13.9) on the Mac, in CI and in the Dockerfile.
- **Workload Identity Federation** (NEW): no key file anywhere; only this repo's `main` can deploy;
  the deployer can only deploy (least privilege).

**Went wrong:** pytest picked up an archived `*_test.py`; ruff's rule groups held rules we didn't
expect (71 errors, not ~10); a pasted gcloud line broke in the middle.

**Change it yourself:** break a test on a branch, push it, and watch the test job go red and the deploy
job not run (branches never deploy).

---

## What's next (v1.1)

- A LangChain-compatible reader/splitter package for legal PDFs; taxowl then uses it and shrinks.
- Hinglish retrieval; `is_refusal()` variants; the "interest rate" web trigger.
- Rewrite stale answers (not just warn); a bigger test set from the live app's questions.
- `zip(strict=)` in 32 places (ruff B905).
