"""OCR the scanned PDFs (pictures of pages, no text inside) using Apple's built-in OCR (ocrmac).

Which files: the ones marked "scan" in ingestion/scan_report.csv (made by check_scans.py).
Output: docs/ocr/<same path as the PDF>.txt, pages separated by a form-feed character (\f),
so later steps can still say "page 3". The PDFs themselves are not changed.

How it works, per page:
  1. Turn the page into an image (300 dpi, sharp enough for small print).
  2. Apple's OCR returns pieces of text, each with a box saying where it was on the page.
  3. Put the pieces back in reading order: pieces at the same height form one line,
     lines go top to bottom, and pieces within a line go left to right.

Usage:
    uv run ingestion/ocr_scans.py
Files already OCR'd are skipped; delete a .txt to redo it.
"""

import csv
import time
from pathlib import Path

import pymupdf

from taxowl.ocr import page_to_lines

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OCR_DIR = DOCS / "ocr"
SCAN_REPORT = Path(__file__).resolve().parent / "scan_report.csv"


def main():
    scans = [r["file"] for r in csv.DictReader(SCAN_REPORT.open()) if r["status"] == "scan"]
    print(f"{len(scans)} scanned files to OCR\n")
    start = time.time()
    for i, rel in enumerate(scans, 1):
        out = (OCR_DIR / rel).with_suffix(".txt")
        if out.exists():
            print(f"[{i}/{len(scans)}] {rel}  already done")
            continue
        with pymupdf.open(DOCS / rel) as pdf:
            pages, low_total = [], 0
            state = {"last_top": 0}
            for page in pdf:
                text, low = page_to_lines(page, state)
                pages.append(text)
                low_total += low
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\f\n".join(pages))
        words = sum(len(p.split()) for p in pages)
        print(f"[{i}/{len(scans)}] {rel}  {len(pages)} pages, {words} words, {low_total} unsure pieces")
    print(f"\nDone in {time.time() - start:.0f}s. Text is in {OCR_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
