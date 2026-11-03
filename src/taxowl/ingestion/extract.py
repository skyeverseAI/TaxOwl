"""Text helpers for the ingestion pipeline (pipeline.py), and its self-check.

  - normalize: Unicode forms and odd quote marks (circular 164/20/2021 stores 'restaurant
    service' with „ and ‟).
  - page_lines: PyMuPDF's words rebuilt into lines, leaving out words inside a table (the table
    has them, so nothing appears twice). Pieces of one printed line that PyMuPDF split apart (wide
    justified gaps) are joined back (join_spread_lines).
  - strip_headers: drop headers and footers: a line at the top or bottom of the page that repeats,
    numbers aside, on at least half the pages and at least 2 ("Page 5 of 6"). Page 1 keeps its top
    lines, because there the "header" is the document's own title ("Circular No. 133/03/2020-GST").
  - self_check (layer 1 of the harness): did every word of the PDF reach the output, and did the
    output gain any word the PDF doesn't have? Tables without any heading, sparse tables (mostly
    empty cells: fragments or blank forms) and cells repeating text are flagged too.

This file was the first extractor (2026-10-27); the pipeline replaced its document loop, which is
in archive/ (see archive/README.md). Only the shared pieces are left here.
"""

import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
OCR_DIR = DOCS / "ocr"
MANIFEST = DOCS / "manifest.jsonl"

EDGE_LINES = 2       # how many lines at the top and bottom of a page can be a header or footer
REPEAT_SHARE = 0.5   # ...if they repeat on at least this share of the pages
MISSING_WORDS = 0.01  # flag a document when more than 1% of its words are missing (at least 10)
MAX_GAP = 3           # join pieces of one printed line only if the gap is at most 3x the text height
REPEAT_RUN = 20      # words in a run that, found twice in one cell, flags it (legal text repeats shorter phrases)

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
    rows = [sorted(ws, key=lambda w: w[7]) for ws in lines.values()]
    return [(min(w[1] for w in ws), " ".join(w[4] for w in ws)) for ws in join_spread_lines(rows)]


def join_spread_lines(rows):
    """Join the pieces of one printed line that PyMuPDF split up. In a justified line with wide
    gaps it can give every word its own line: the Act's "1[158A. Consent based sharing of ..."
    heading (p.119) came out one word per line, and so did 240 places in 84 corpus files.

    A piece joins the row before it only if all four hold, so two columns, or a header's page
    number and title at the two ends of the page, stay apart:
      - same block (PyMuPDF's paragraph);
      - same height: they overlap by at least half the shorter one's height;
      - it starts to the right of where the row before ends (the stored order, left to right);
      - the gap is at most MAX_GAP times the text height. A justified line's gaps are about 1x
        (158A: 13pt gap, 13pt text); the Rules header "278 ... GST & Indirect Taxes Committee"
        is 16x. Joining that header made it different on every page, so strip_headers stopped
        removing it (held-out text_not checks fell; measured 2026-11-03)."""
    out = []
    for ws in rows:
        if out:
            prev = out[-1]
            top, bottom = max(prev[0][1], ws[0][1]), min(prev[0][3], ws[0][3])
            height = min(prev[0][3] - prev[0][1], ws[0][3] - ws[0][1])
            gap = ws[0][0] - prev[-1][2]
            if (ws[0][5] == prev[-1][5] and height > 0 and bottom - top >= height / 2
                    and 0 <= gap <= MAX_GAP * height):
                out[-1] = prev + ws
                continue
        out.append(ws)
    return out


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


# ---------- self-check ----------

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
