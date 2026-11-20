# taxowl

Ask a question about Indian GST law and get a short answer that cites its sources: the CGST Act, the CGST
Rules, the IGST/UTGST Acts, and CBIC circulars. Every circular is marked in force, withdrawn or
partly modified. Questions about rates also search the web, because rates change by notification.

**Live:** https://taxowl-l5bv4gb4wa-uc.a.run.app (the first question after a quiet spell takes
longer while the server wakes up).

Information, not legal advice.

```
question ──► retrieve ───────────────► answer (gpt-4o-mini) ──► checks + notes ──► answer with [S#]
             exact: "section 16(4)"       cites [S1], [S2]…       citations real?
             by meaning: bge-m3, Chroma   or refuses              ⚠ rule amended later?
             + web, for rate questions                            rate may be old?
```

## How good is it

Short version (dev set unless marked; details and caveats in **[QUALITY.md](QUALITY.md)**):

| | |
|---|---|
| right law in the top 5 (TEST set) | 0.81 (Hinglish only 0.33) |
| answer complete, by an LLM judge | 0.94, an upper bound: the judge is lenient |
| refuses / answers correctly | 0.97 |
| median answer | 4.5 s, ₹0.065 |

## Known limitations

- Hinglish questions and abbreviations ("ITC") often miss the right section.
- It sometimes refuses when the sources do hold the answer.
- A fake "SYSTEM: …" instruction inside a question can make it add a word it was told to (1 of 4 tries).
- With an old circular and a newer rule, the answer can lead with the old rule; a ⚠ note under it warns.
- Rates come from a web search and are only as good as the sites it finds.
- All scores come from small sets (16–40 questions).

## Run it locally

```
uv sync --frozen          # exact versions from uv.lock (uv 0.13.9, see pyproject)
uv run streamlit run app.py
```

Needs the store in `data/` (or `TAXOWL_STORE_REPO` + `HF_TOKEN` to download it) and an
`OPENROUTER_API_KEY`; `TAVILY_API_KEY` for rate questions.

`--frozen` installs exactly the versions in `uv.lock` and changes nothing. That matters here: the
extraction scores in `plans/extraction_journey.md` were measured with these versions. In one test the same
OCR scored 84% or 74% depending only on the versions of two libraries underneath Docling. To upgrade a
library, change it on purpose, re-run the checks, and commit the new `uv.lock` with the scores.

## Tests and deploys

```
uv run pytest            # 16 tests, no store or key needed
uvx ruff@0.17.5 check .
```

Every push runs both on GitHub Actions. On `main`, if they pass, the same workflow deploys to Cloud Run,
logging in with Workload Identity Federation (no key file). See `.github/workflows/ci.yml` and
`plans/deploy_journey.md`.

## Where things are

Each top-level folder has one job: code, steps, grading, docs, input, output.

```
app.py             the UI (Streamlit); owl.py is the loading animation
src/taxowl/        the product (one package; one subfolder per stage)
  schema.py        the shapes every stage shares (ExtractedDoc, Table, Unit)
  ingestion/       PDF -> ExtractedDoc: pipeline.py runs it; ocr, tables, gate, vlm, extract help
  splitting/       ExtractedDoc -> Units (one per section, rule, paragraph), by doc_type
  chunking/        Units -> chunks of at most 400 tokens, cut along the law's own lines
  validity/        which circulars are withdrawn / modified; which rules were amended, and when
  retrieval/       embedder (bge-m3), Chroma store, retriever (exact citations + by meaning)
  answer/          pipeline.py (the whole answer), generator, web search, check.py (free checks)
  evals/           retriever, generator, pipeline, safety evals and judge calibration
tests/             pytest: fast checks of the pure functions (citations, labels, checks, web)
scripts/           steps run by hand, in order: 01_download.py, 02_check_scans.py, 03_split_chunk.py, ...
eval_results/      gold sets, held-out sets, run outputs; grading never changes the output
Evaluations/       the eval reports (Baseline, Improvement, Final), read with QUALITY.md
plans/             the journey docs: extraction, deploy, plans per stage
docs/              input: the law PDFs (git-ignored, linked to the official source), manifest
archive/           old experiments, kept as evidence for the journey docs; nothing live uses them
data/              git-ignored, local only: ingested docs, units, chunks, the store, caches, private data
```

Why it's split this way: `src/` is what the server runs and everything else depends on, so it stays
stable and tested. Scripts and evals are tools around it. Private data sits in one place, so "never
commit `data/`" covers all of it.
