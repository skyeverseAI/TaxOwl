# archive

Experiments and notes from building the PDF extractor. Nothing here is used by the pipeline; it is kept because `plans/extraction_journey.md` cites it as evidence for its decisions.

Some of these scripts import code that has since been removed (the old `extract()` loop in `src/taxowl/extract.py`). To run one, check out the last commit where it ran: `git checkout df78166`.

## experiments/

| File | What it was |
|---|---|
| `compare_tables.py`, `table_compare/` | PyMuPDF vs Docling tables on the 9 hardest files; set the table rules in `tables.py` |
| `find_nested.py`, `nested_report.csv` | Found tables nested inside table cells across the corpus |
| `gate_test.py` | Tested the cheap gate that decides which table pages go to the vision model |
| `vlm_tables.py`, `vlm_nested.py` | First vision-model table trials, before the grid-only + snap design in `vlm.py` |
| `review_flagged.py`, `flagged_review/` | Checked flagged pages by eye; the verdicts (page images are git-ignored) |

## notes/

| File | What it was |
|---|---|
| `ingestion_pipeline.md` | The first pipeline design; the built version is in `plans/extraction_journey.md` |
| `table_gate_feasibility.md` | The gate and vision-model numbers |
| `table-rag-recommendation.md` | How to store tables for retrieval: early research |
| `pymupdf_examples.md`, `paddle_results.md` | PyMuPDF output samples; the PaddleOCR trial (not chosen) |
| `doing_now.md` | Old working notes |
