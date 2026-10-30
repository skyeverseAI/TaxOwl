# Ingestion pipeline: any PDF in, one ExtractedDoc out (design, 2026-10-29)

Goal: one function that works on **any** PDF, a corpus file or a user's upload, with no
precomputed lists. Today the run leans on three things only our corpus has:
`docs/manifest.jsonl` (sha256, doc number), `ingestion/scan_report.csv` (which files are scans),
and `docs/ocr/*.txt` (OCR made ahead of time). The table path (PyMuPDF, gate, Gemini) lives in
`evals/` and `ingestion/` scripts, not in the package.

## Flow

```
PDF path (+ optional metadata)
 │
 ├─ 1. Open + basic checks: opens? encrypted? page count; sha256 of the bytes
 │
 ├─ 2. Per page: what kind of page is it?
 │      text  → PyMuPDF words
 │      scan  → OCR (ocrmac) → text lines, ocr=True        (check_scans' rules, per page)
 │      hindi → kept, flagged (v1 is English only)
 │
 ├─ 3. Tables on text pages: PyMuPDF reads them (tables.py), joins across pages
 │
 ├─ 4. Gate per page: merged / nested / colour / white_boxes / scan / broken
 │      flagged pages + every page of a table that touches one = "model pages"
 │
 ├─ 5. Model pages → Gemini (grid only) → snapped to PDF words (vlm_tables' code)
 │      no key / offline / model fails → keep PyMuPDF's tables, flag "vlm_failed"
 │
 ├─ 6. Page text = words outside the table boxes; headers/footers stripped
 │
 └─ 7. Self-check (as today) + which reader made each table + why the gate sent it
        → ExtractedDoc
```

## Decisions and why

| Decision | Why |
|---|---|
| Scan or text is decided **per page**, not per file | An upload can mix typed pages with a scanned annexure. Per file, one scanned page would push the whole file to OCR, or be missed. |
| OCR runs inside the pipeline (ocrmac, the same engine as `ingestion/ocr_scans.py`) | An upload has no precomputed `docs/ocr/` file. ocrmac only runs on a Mac; behind one function, so a server can swap in Tesseract or a cloud OCR later. |
| A whole table "chain" goes to one reader | A table over pages 6-7 can't be half PyMuPDF and half Gemini, because the two join pages differently. If the gate flags one of its pages, all of them go to the model. |
| The gate goes into the package (`src/taxowl/gate.py`); `evals/gate_test.py` then imports it | One copy of the rules. The test measures exactly what the pipeline runs. |
| Gemini code goes into the package (`src/taxowl/vlm.py`); `ingestion/vlm_tables.py` becomes a thin bake-off script, or is removed | Same reason. |
| The model cache is keyed by **file hash + page**, not path | An upload has no stable path. The same PDF uploaded twice costs nothing the second time. |
| Without a model (no key, or `model=None` for private uploads) it still runs | PyMuPDF only, with flagged tables marked. A table that may be wrong is never passed off as fine. |
| Metadata is optional | The doc id comes from the manifest when the file is in it, else from the file name. sha256 is computed from the bytes. |

## Interface

```python
from taxowl.ingestion_pipeline import ingest
doc = ingest("some.pdf")                       # metadata from the manifest if known
doc = ingest("upload.pdf", model=None)         # no data leaves the machine
```
```
uv run python -m taxowl.ingestion_pipeline docs/circulars/2025/254-11-2025-GST.pdf
uv run python -m taxowl.ingestion_pipeline --corpus      # all 314, writes data/extracted/
```

## Known gaps (not in this step)

- **Tables PyMuPDF doesn't see at all.** For example a table with no lines (251/08/2025). The gate
  can only judge tables PyMuPDF found. In the 45 test cases this never happened, but it can.
- **Hindi pages** are flagged, not read.
- **Upload limits** (size, page count) belong to the upload feature, not here.

## Then: the test

1. A fresh held-out set, seed 2034 (`evals/draw_heldout.py`), with gold written from page images
   as before. No rule has seen it.
2. The pipeline on it, scored by `evals/check_ingestion.py`, and compared with PyMuPDF alone.
3. One or two PDFs from **outside** the corpus (not in the manifest), to show that it runs with no
   precomputed anything.
