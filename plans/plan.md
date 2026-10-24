# New project — public GST law RAG with visible quality measurement

## Context

LERAGS was built on 62 private GST writ petitions. Those files can't go public, so they can't drive a portfolio project or a deployed tool. The git history also contains a committed identifier leak (commit 28f40a5), so the LERAGS repo itself can never be made public. The skills and the code carry over; the corpus doesn't.

Goal: a new public project, live within **15 days**. It answers GST questions from official public law, with page or section citations. It shows component, pipeline, application and online eval results on a public quality page. It's built to stay useful afterwards: the corpus keeps updating and documents carry their validity status.

The user is still discussing this, so nothing here is final until approved.

## Corpus (v1)

| Source | Size | Format | Official location |
|---|---|---|---|
| CGST Act, 2017 (as amended) | 1 doc, about 174 sections | HTML on the CBIC tax-information portal; PDF compilations | taxinformation.cbic.gov.in, cbic-gst.gov.in/pdf/ |
| CGST Rules, 2017 (as amended) | 1 doc, Part A rules + Part B forms | PDF | cbic-gst.gov.in/pdf/ |
| CBIC CGST circulars | **about 256** (1/1/2017-GST of 26-06-2017 → 256/02/2026-GST of 25-07-2026) | PDF, mostly digital text | cbic-gst.gov.in/pdf/, gstcouncil.gov.in/cgst-circulars |

Gaps to close on day 1:
- The newest official consolidated Act and Rules I found are dated 2022. Amendments since then come through Finance Acts and notifications. Check whether the CBIC portal's HTML version is current.
- Check the circular count against the official list. Aggregators show 256; the GST Council list has 314 rows, including duplicates.
- **Reuse:** s.52(1)(q) of the Copyright Act allows reproducing Gazette matter, but the GST Council site footer says "All rights reserved". So the safe design shows **excerpts with an official link**, not full-document re-hosting.

Deferred:
- **Tariffs** → v1.1 as a structured HSN→rate lookup. Notification 9/2025-CT(Rate) replaced 1/2017 from 22-09-2025.
- **HC judgments** → v2.
- **Bring your own PDFs, a router to the right tax area, more tax areas (income tax, state commercial tax)** → after v1 ships. See `plans/fde_plan.md`.

## Key design decisions

1. **Validity status per circular.** Ingest all circulars. Detect "withdrawn / rescinded / in supersession of Circular No. X" in the text, which gives a graph of which circular withdrew which. Each document gets `status` ∈ {in_force, withdrawn, partly_modified} plus `withdrawn_by`. Search filters to `status=in_force` by default (the existing `where=` filter in `search()`), and answers mention the history. Hand-verify the detected withdrawals and report the detector's precision and recall.
2. **Chunk by legal structure, not by character count.** One chunk per section, rule or circular paragraph, with metadata `{doc_type, number, date, section/para, official_url, status}`. This replaces the plain/hybrid arms comparison as the chunking experiment.
3. **Incremental ingest.** A new circular is added without rebuilding the store (reuse `store.has_source()` / `sources()`).
4. **LLM choice decided by measurement.** Run the same evalset through a local 7B model (Ollama) and one cloud model. Compare answer correctness, p50/p95 latency and cost. The data picks the demo model, and the comparison is itself a result to publish.
5. **New repo, public from the first commit.** Nothing from LERAGS `data/` is ever copied.

## Reuse from LERAGS (copy, then adapt)

- `src/similarity/metrics.py`: recall@k, MRR, nDCG. Copy unchanged; the user wrote it.
- `src/store.py`: Chroma client, `add_chunks`, `clean_metadata`, `has_source`, `sources`, `drop`.
- `src/similarity/search.py`: `search(query, arm, k, where=)`.
- `src/embeddings/models.py`: bge-small with the query prefix.
- `src/config.py`: the `num_ctx` lesson and `lru_cache` on the embedder.
- `scripts/23_eval.py`: the structure of the runner (splits, per-arm summary, timestamped JSON output).
- `docs/evalset_design.md`: conventions (dev/test split, frozen test checksum, unanswerable questions).
- **Not reused:** `hc_lookup/`, `metadata/`, OCR scripts, `loaders/corpus.py` (written around OCR JSON).

## 15-day schedule

| Day | Work | Eval level |
|---|---|---|
| 1 | New repo, check sources, download script for circulars + Act + Rules | — |
| 2 | Parse into structural chunks with metadata; ingest | — |
| 3 | Withdrawal detector + hand-verification | Component (detector P/R) |
| 4–5 | Evalset of about 50 questions: user writes the test split; include withdrawn-circular traps and unanswerable questions. Retrieval baseline. | Component (retrieval) |
| 6–7 | `answer.py`: grounded answer + citations + refusal when the evidence is weak | — |
| 8–9 | Answer correctness, citation support, LLM judge calibrated against about 20 user labels; safety set (out-of-scope, advice requests, injection); latency and cost; local vs cloud comparison | Pipeline + application |
| 10 | One measured improvement (BM25 hybrid search or a reranker) | Component + pipeline, compared |
| 11–13 | API + simple UI; deploy; CI runs the eval → public quality page; query/latency/feedback logging | Online |
| 14–15 | Buffer, README led by the numbers, write-up | — |

**User writes:** the evalset test split, the adapted eval runner, the judge rubric. **Claude builds:** download/parse plumbing, deployment, CI.

## Verification

- Ingest: chunk count per doc_type; every chunk has `official_url` and `status`; spot-check 10 chunks against the source PDFs.
- Withdrawal detector: precision and recall against a hand-checked list.
- Retrieval: `eval` produces recall@5, MRR and nDCG per config into a timestamped JSON; the test split checksum stays unchanged.
- End to end: an answer to a known question cites the right section or circular, and a withdrawn-circular question doesn't cite the withdrawn one as current.
- Deploy: the public URL answers a query; the quality page shows the latest CI eval row.
