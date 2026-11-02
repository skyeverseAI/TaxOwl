# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["docling==2.99.0", "rapidocr", "onnxruntime", "ocrmac; sys_platform == 'darwin'"]
# ///
"""Run 3 on the private petition set: Docling + OcrMac, the setup LERAGS used, scored by the same checker.

Why: on the petitions our pipeline reads words from the scanner's hidden OCR layer, and that layer
is wrong on numbers ("Section SO" for 50). Gemini only fixes the grid, never the words. LERAGS threw
that layer away and re-OCRed every page (force_full_page_ocr) and let Docling build the tables. This
tests that setup on the 25 gold pages, so the three runs can be compared on one scale.

Independent of the pipeline on purpose: its own env (the block above; uv builds it, the project's
venv is not touched), no import from taxowl. It writes the ExtractedDoc shape as plain JSON, which is
all the checker reads.

How a Docling table becomes our Table:
  - headings: the top rows Docling marks as column headers, joined per column ("Amount CGST").
    If it marks none, the headings are empty ("") and every row counts as a row.
  - rows: every row below. A merged cell's text is repeated in each row it covers, as in our convention.
  - page text: Docling's body text on the page, outside tables. Page headers/footers are left out,
    because Docling puts them in a separate layer.

Only the gold pages are converted (one convert() per page); every other page is left "".
Defaults: gold data/private/gold/ingestion_petitions.json, PDFs in data/private/petitions/, output data/private/runs/run_docling/
(<pdf path>.json, and markdown/<case id>.md to read by eye).

--ocr rapid swaps OcrMac for RapidOCR and changes nothing else, so the score difference is the OCR
engine alone. RapidOCR runs on Linux (OcrMac is Mac-only), so this is the setup a server would have.
Its default output is data/private/runs/run_docling_rapid/.

--scans-only keeps the cases whose pages are all scans (fewer than 100 letters in the text layer, the
pipeline's rule), and writes them to <out>/scan_gold.json, so the pipeline (ocrmac) can be scored on
exactly the same cases.

Usage (any Python with docling 2.99, e.g. LERAGS' venv, or `uv run --script`):
    python eval_results/docling_trial.py
    uv run eval_results/check_ingestion.py data/private/runs/run_docling --gold data/private/gold/ingestion_petitions.json

    # the corpus scans in every gold set: Docling vs the pipeline's ocrmac
    python eval_results/docling_trial.py --gold eval_results/gold/ingestion_*.json --pdfs docs --out data/runs/docling_scans --scans-only
    uv run eval_results/check_ingestion.py data/runs/docling_scans --gold data/runs/docling_scans/scan_gold.json

    # the same two runs with RapidOCR
    python eval_results/docling_trial.py --ocr rapid
    python eval_results/docling_trial.py --ocr rapid --gold eval_results/gold/ingestion_*.json --pdfs docs --out data/runs/docling_scans_rapid --scans-only
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "private" / "gold" / "ingestion_petitions.json"
PDFS = ROOT / "data" / "private" / "petitions"
OUT = ROOT / "data" / "private" / "runs" / "run_docling"
EMPTY_PAGE_CHARS = 100  # as in ingestion_pipeline.py: fewer letters than this is a scan


def args_after(flag):
    """The values after a flag, up to the next flag (so a shell glob gives many)."""
    if flag not in sys.argv:
        return []
    rest = sys.argv[sys.argv.index(flag) + 1:]
    return rest[:next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))]


def is_scan(pdf, page):
    import pypdfium2  # comes with docling

    text = pypdfium2.PdfDocument(pdf)[page - 1].get_textpage().get_text_range()
    return len(re.sub(r"\s", "", text)) < EMPTY_PAGE_CHARS


def make_converter(ocr):
    """The LERAGS settings (its scripts/07 and 09): full-page OCR, table structure on, CPU.
    ocr is "mac" (OcrMac, as LERAGS) or "rapid" (RapidOCR); only that line differs."""
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import OcrMacOptions, PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    engine = {"mac": OcrMacOptions, "rapid": RapidOcrOptions}[ocr]
    opts.ocr_options = engine(force_full_page_ocr=True)
    opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=8)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def to_table(item, table_id, page):
    grid = item.data.grid
    if not grid:
        return None
    n = 0
    while n < len(grid) and any(c.column_header for c in grid[n]):
        n += 1
    # No header row marked: the table has none (a list carried over from the last page, a key-value
    # box), so the headings stay empty and every row is a row. (Taking the first row as headings
    # here cost Run 3 a row on 6 such tables.)
    headings = []
    for j in range(len(grid[0])):
        parts = []
        for r in range(n):
            text = grid[r][j].text.strip()
            if text and (not parts or parts[-1] != text):  # a spanning heading repeats in each column row
                parts.append(text)
        headings.append(" ".join(parts))
    rows = [[c.text.strip() for c in row] for row in grid[n:]]
    return {"table_id": table_id, "headings": headings, "rows": rows,
            "row_pages": [page] * len(rows), "reader": "docling", "html": ""}


def read_page(converter, pdf, page, file):
    """Text outside tables, the tables, and the markdown of one page."""
    from docling_core.types.doc import ListItem, TableItem

    doc = converter.convert(pdf, page_range=(page, page)).document
    text, tables = [], []
    for item, _ in doc.iterate_items():
        if isinstance(item, TableItem):
            t = to_table(item, f"{file}:p{page}-table-{len(tables) + 1}", page)
            if t:
                tables.append(t)
        elif getattr(item, "text", ""):
            # Docling keeps a numbered para's number ("2.1", "15.", "(a)") in .marker, not .text; put it
            # back. Bullets ("-", "•") have no letter or digit and are skipped.
            marker = item.marker if isinstance(item, ListItem) else ""
            text.append(f"{marker} {item.text}" if re.search(r"\w", marker or "") else item.text)
    return "\n".join(text), tables, doc.export_to_markdown()


def main():
    import pypdfium2  # comes with docling

    golds = [Path(g) for g in args_after("--gold")] or [GOLD]
    pdfs = Path(args_after("--pdfs")[0]) if "--pdfs" in sys.argv else PDFS
    ocr = args_after("--ocr")[0] if "--ocr" in sys.argv else "mac"
    out = Path(args_after("--out")[0]) if "--out" in sys.argv else OUT.with_name(OUT.name + ("" if ocr == "mac" else f"_{ocr}"))
    gold = [c for g in golds for c in json.loads(g.read_text())["pages"]]
    if "--scans-only" in sys.argv:
        gold = [c for c in gold if all(is_scan(pdfs / c["file"], p) for p in c["pages"])]
        out.mkdir(parents=True, exist_ok=True)
        (out / "scan_gold.json").write_text(json.dumps(
            {"_about": "Cases from " + ", ".join(g.name for g in golds) + " whose pages are all scans.",
             "pages": gold}, ensure_ascii=False, indent=1))
    (out / "markdown").mkdir(parents=True, exist_ok=True)
    converter = make_converter(ocr)

    by_file = {}
    for case in gold:
        by_file.setdefault(case["file"], []).append(case)

    started = time.time()
    for file, cases in by_file.items():
        pdf = pdfs / file
        n_pages = len(pypdfium2.PdfDocument(pdf))
        doc = {"file": file, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
               "pages": [""] * n_pages, "tables": [], "ocr": True, "quality": {}}
        for case in cases:
            for page in case["pages"]:
                t0 = time.time()
                text, tables, markdown = read_page(converter, pdf, page, file)
                doc["pages"][page - 1] = text
                doc["tables"] += tables
                (out / "markdown" / f"{case['id']}.md").write_text(markdown)
                print(f"{case['id']:<45} {len(tables)} table(s)  {time.time() - t0:5.1f}s")
        path = out / f"{file}.json"
        path.parent.mkdir(parents=True, exist_ok=True)  # corpus files sit in sub-folders: circulars/2024/...
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    print(f"\n[{ocr}] {sum(len(c['pages']) for c in gold)} pages in {time.time() - started:.0f}s -> {out}/")


if __name__ == "__main__":
    main()
