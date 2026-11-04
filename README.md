# taxowl

A question-answering tool over Indian GST law: the CGST Act, the CGST Rules, and the CBIC circulars and instructions. Each circular is marked in force, withdrawn or superseded.

## Install

```
uv sync --frozen
```

`--frozen` installs exactly the versions in `uv.lock` and changes nothing. That matters here: the extraction scores in `plans/extraction_journey.md` were measured with these exact versions. In one test, the same OCR scored 84% or 74% depending only on the versions of two libraries underneath Docling.

To upgrade a library, change it on purpose, re-run the gold and held-out checks (`eval_results/`), and commit the new `uv.lock` together with the scores.

## Where things are

Each top-level folder has one job: code, steps, grading, docs, input, output.

```
src/taxowl/        the product (one package; one subfolder per stage)
  schema.py        the shapes every stage shares (ExtractedDoc, Table, Unit)
  ingestion/       PDF -> ExtractedDoc: pipeline.py runs it; ocr, tables, gate, vlm, extract help
  splitting/       ExtractedDoc -> Units (one per section, rule, paragraph): run.py picks the splitter
                   by doc_type: act.py, icai.py (the ICAI Rules), circulars.py
scripts/           steps run by hand, in order: 01_download.py, 02_check_scans.py, 03_split_chunk.py
eval_results/      grading: never changes the output, only scores it
  check_ingestion.py, draw_heldout.py, heldout_runs.md
  gold/            the gold set and the held-out sets (pages checked by hand)
  draws/           which pages were drawn for each held-out set, and the reports the draw uses
  pages/           page images for those sets (git-ignored)
plans/             docs to read; start with extraction_journey.md
docs/              input: the law PDFs (git-ignored, we link to the official source), manifest, saved OCR
archive/           old experiments, kept as evidence for the journey doc; nothing live uses them
data/              git-ignored, local only
  ingested/        the pipeline's output
  units/           the splitters' output: <file>.jsonl (+ <file>.tables.jsonl)
  cache/           saved vision-model answers
  runs/            outputs of one-off trials
  private/         private writ petitions: petitions/, gold/, pages/, runs/. Never committed.
```

Later stages (chunking, retrieval, answers) get their own subfolders next to `ingestion/`, all sharing `schema.py`.

Why it's split this way: `src/` is what the server runs and everything else depends on, so it stays stable and tested. Scripts and evals are tools around it. Private data sits in one place, so "never commit `data/`" covers all of it.
