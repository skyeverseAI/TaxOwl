# taxowl

A question-answering tool over Indian GST law: the CGST Act, the CGST Rules, and the CBIC circulars and instructions. Each circular is marked in force, withdrawn or superseded.

## Install

```
uv sync --frozen
```

`--frozen` installs exactly the versions in `uv.lock` and changes nothing. That matters here: the extraction scores in `plans/extraction_journey.md` were measured with these exact versions. In one test, the same OCR scored 84% or 74% depending only on the versions of two libraries underneath Docling.

To upgrade a library, change it on purpose, re-run the gold and held-out checks (`evals/`), and commit the new `uv.lock` together with the scores.

## Where things are

- `plans/extraction_journey.md`: how the PDF extractor was built, step by step, with the score at each step
- `src/taxowl/ingestion_pipeline.py`: PDF → text and tables, for our own documents and for uploads
- `evals/`: the gold and held-out sets, and the checker
