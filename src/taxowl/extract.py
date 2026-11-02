"""PDF -> ExtractedDoc: text per page, tables, and a quality report (plans/plan_ingestion.md, C2-C3).

For each PDF in docs/manifest.jsonl:
  1. Text. Born-digital PDFs: PyMuPDF's words, rebuilt into lines, leaving out words that sit
     inside a table (the table has them, so nothing appears twice). The 8 scans: the OCR text in
     docs/ocr/ (saved there by the ingestion pipeline's first read of the file).
  2. Clean-up, with general rules only:
       - normalise characters: Unicode forms, and odd quote marks (circular 164/20/2021 stores
         'restaurant service' with „ and ‟);
       - drop headers and footers: a line at the top or bottom of the page that repeats, numbers
         aside, on at least half the pages and at least 2 ("Page 5 of 6"). Page 1 keeps its top lines, because
         there the "header" is the document's own title ("Circular No. 133/03/2020-GST").
  3. Tables: src/taxowl/tables.py.
  4. Self-check (layer 1 of the harness): did every word of the PDF reach the output, and did
     the output gain any word the PDF doesn't have? Tables without any heading, and sparse
     tables (mostly empty cells: fragments or blank forms), are flagged too.

Output: data/extracted/<pdf path>.json, one ExtractedDoc each. evals/check_ingestion.py scores it.

Usage:
    uv run python -m taxowl.extract            # all documents in the manifest
    uv run python -m taxowl.extract --gold     # only the files in the gold set
    uv run python -m taxowl.extract circulars/2025/254-11-2025-GST.pdf
"""

import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pymupdf

from taxowl.schema import ExtractedDoc
from taxowl.tables import join_tables, read_page_tables, to_tables

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
OCR_DIR = DOCS / "ocr"
MANIFEST = DOCS / "manifest.jsonl"
SCAN_REPORT = ROOT / "ingestion" / "scan_report.csv"
GOLD = ROOT / "evals" / "ingestion_gold.json"
OUT = ROOT / "data" / "extracted"

EDGE_LINES = 2       # how many lines at the top and bottom of a page can be a header or footer
REPEAT_SHARE = 0.5   # ...if they repeat on at least this share of the pages
MISSING_WORDS = 0.01  # flag a document when more than 1% of its words are missing (at least 10)
REPEAT_RUN = 20       # words in a run that, found twice in one cell, flags it (legal text repeats shorter phrases)

QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "­": ""})
TABLE_REF = re.compile(r"\[table [^\]]+\]")


def normalize(text):
    return unicodedata.normalize("NFKC", text).translate(QUOTES)


def tokens(text):
    """Words for the self-check: letters and digits only, so tidying punctuation and spaces
    ("S . No ." -> "S. No.") doesn't count as a change."""
    return re.findall(r"\w+", text)


# ---------- text ----------

def page_lines(words, boxes):
    """Rebuild lines from PyMuPDF's words, leaving out words inside a table, as (y, text) in the
    order the PDF stores them. The text keeps that order (sorting by y scrambles a tilted line,
    56/30/2018); y only tells strip_headers which lines are really at the top and bottom, since the
    stored order can put the footer mid-page (219/13/2024 p.1)."""
    lines = {}
    for w in words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            continue
        lines.setdefault((w[5], w[6]), []).append(w)
    return [(min(w[1] for w in ws), " ".join(w[4] for w in sorted(ws, key=lambda w: w[7])))
            for ws in lines.values()]


def shape(line):
    """A line with its digits blanked out: "Page 5 of 6" and "Page 6 of 6" have the same shape."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", line))


def strip_headers(pages):
    """Drop header and footer lines (see the module docstring). `pages`: per page, (y, text) lines,
    y saying where the line sits on the page. Returns (pages as lists of text, removed lines)."""
    texts = [[text for _, text in lines] for lines in pages]
    if len(pages) < 2:
        return texts, []
    edges = []  # per page: (indices of the top lines, indices of the bottom lines), by position
    for lines in pages:
        by_y = sorted(range(len(lines)), key=lambda k: lines[k][0])
        edges.append((set(by_y[:EDGE_LINES]), set(by_y[-EDGE_LINES:])))
    counts = Counter()
    for lines, (top, bottom) in zip(texts, edges):
        counts.update({shape(lines[k]) for k in top | bottom if shape(lines[k])})
    # At least 2 pages, so in a 2-page document a line must be on both ("Page 1 of 2", 194/06/2023).
    repeated = {s for s, n in counts.items() if n >= max(2, REPEAT_SHARE * len(pages))}
    kept, removed = [], []
    for i, (lines, (top, bottom)) in enumerate(zip(texts, edges)):
        keep = []
        for k, line in enumerate(lines):
            if (k in top or k in bottom) and shape(line) in repeated and not (i == 0 and k in top):
                removed.append(line)
            else:
                keep.append(line)
        kept.append(keep)
    return kept, removed


# ---------- one document ----------

def extract(meta, scans):
    rel = meta["file"]
    doc_id = meta.get("number") or Path(rel).stem
    if rel in scans:
        # Saved by the ingestion pipeline (Docling + RapidOCR); only the text is used here.
        saved = json.loads((OCR_DIR / rel).with_suffix(".json").read_text())
        texts = [normalize(saved["pages"].get(str(p), {}).get("text", "")) for p in range(1, saved["n_pages"] + 1)]
        pages, _ = strip_headers([list(enumerate(t.splitlines())) for t in texts])
        return ExtractedDoc(rel, meta["sha256"], ["\n".join(p) for p in pages], ocr=True)

    pages, raws, source = [], [], []
    with pymupdf.open(DOCS / rel) as pdf:
        for page in pdf:
            words = [(*w[:4], normalize(w[4]), *w[5:]) for w in page.get_text("words")]
            source += [w[4] for w in words]
            page_raws = read_page_tables(page, words)
            raws += page_raws
            pages.append(page_lines(words, [r["box"] for r in page_raws]))
    pages, removed = strip_headers(pages)
    joined, dropped = join_tables(raws)
    doc = ExtractedDoc(rel, meta["sha256"], ["\n".join(p) for p in pages], to_tables(joined, doc_id))
    doc.quality = self_check(doc, source, removed + dropped, raws)
    return doc


def repeated_beyond_source(text, source_text):
    """Does a run of REPEAT_RUN words occur twice in this cell (without overlapping) but not twice
    in the PDF? Circulars often quote a provision and then restate it, so a repeat the PDF has
    too is fine; one the PDF doesn't have is ours. `source_text`: the PDF's tokens, space-joined
    with a space at each end."""
    words = tokens(text)
    first = {}
    for i in range(len(words) - REPEAT_RUN + 1):
        run = tuple(words[i:i + REPEAT_RUN])
        if run in first and i - first[run] >= REPEAT_RUN and source_text.count(f" {' '.join(run)} ") < 2:
            return True
        first.setdefault(run, i)
    return False


def self_check(doc, source, dropped_on_purpose, raws):
    """Layer 1 of the harness. Returns {check: reason} for every check that failed."""
    failed = {}
    out_text = ["\n".join(doc.pages)]
    for t in doc.tables:
        out_text += [h for h in t.headings if not re.fullmatch(r"Column \d+", h)]
        out_text += [TABLE_REF.sub("", c) for row in t.rows for c in row]
    out = Counter(tokens(" ".join(out_text)))
    src = Counter(tokens(" ".join(source))) - Counter(tokens(" ".join(dropped_on_purpose)))

    missing = src - out
    n_missing = sum(missing.values())
    if n_missing > max(10, MISSING_WORDS * sum(src.values())):
        sample = ", ".join(w for w, _ in missing.most_common(8))
        failed["words_missing"] = f"{n_missing} of {sum(src.values())} words, e.g. {sample}"
    invented = set(out) - set(src) - set(tokens(" ".join(dropped_on_purpose)))
    if invented:
        failed["words_invented"] = ", ".join(sorted(invented)[:8])
    # Words all present but some twice in one cell (203/15/2023 before the section-row rule): the
    # counts above can't see this. Only long runs count, and only if the PDF doesn't repeat them too.
    source_text = f" {' '.join(tokens(' '.join(source)))} "
    repeated = sorted({f"{t.table_id} (p.{page})" for t in doc.tables for row, page in zip(t.rows, t.row_pages)
                       if any(repeated_beyond_source(c, source_text) for c in row)})
    if repeated:
        failed["cells_repeated"] = ", ".join(repeated[:5]) + (" ..." if len(repeated) > 5 else "")
    headless = [f"{t.table_id} (p.{t.row_pages[0] if t.row_pages else '?'})" for t in doc.tables
                if all(re.fullmatch(r"Column \d+", h) for h in t.headings)]
    if headless:
        failed["tables_without_headings"] = ", ".join(headless[:5]) + (" ..." if len(headless) > 5 else "")
    # All words present but spread over a grid of mostly empty cells (99/18/2019 before the
    # "lines_strict" retry): the word checks can't see this, so it's checked on its own. Blank
    # forms look the same, so this one means "look at it", not "wrong".
    pages = sorted({r["page"] for r in raws if r["sparse"]})
    if pages:
        failed["tables_sparse"] = "page(s) " + ", ".join(map(str, pages[:10])) + (" ..." if len(pages) > 10 else "")
    return failed


# ---------- all documents ----------

def main():
    manifest = [json.loads(line) for line in MANIFEST.open()]
    scans = {r["file"] for r in csv.DictReader(SCAN_REPORT.open()) if r["status"] == "scan"}
    args = sys.argv[1:]
    if "--gold" in args:
        wanted = {case["file"] for case in json.loads(GOLD.read_text())["pages"]}
    elif args:
        wanted = set(args)
    else:
        wanted = {m["file"] for m in manifest}
    docs = [m for m in manifest if m["file"] in wanted]

    start, flagged, n_tables = time.time(), [], 0
    for i, meta in enumerate(docs, 1):
        print(f"\r[{i}/{len(docs)}] {meta['file'][:70]:<70}", end="", flush=True)
        try:
            doc = extract(meta, scans)
        except Exception as e:  # one bad PDF shouldn't stop the run
            doc = ExtractedDoc(meta["file"], meta["sha256"], [], quality={"error": repr(e)})
        out = OUT / (meta["file"] + ".json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(asdict(doc), ensure_ascii=False))
        n_tables += len(doc.tables)
        if doc.quality:
            flagged.append(doc)
    print(f"\n\n{len(docs)} documents, {n_tables} tables, {time.time() - start:.0f}s. "
          f"Output: {OUT.relative_to(ROOT)}/")
    print(f"Self-check flagged {len(flagged)} document(s):")
    for doc in flagged:
        print(f"  {doc.file}")
        for check, reason in doc.quality.items():
            print(f"      {check}: {reason}")


if __name__ == "__main__":
    main()
