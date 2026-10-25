"""Compare two ways of reading tables, on the 9 hardest table files (plans/plan_ingestion.md, section C).

The only thing that differs between the two arms is how the table CELLS are read:
  pymupdf   PyMuPDF finds the table grid; each cell's text = the words whose centre lies inside it.
            (Taking words, not raw characters, is meant to fix "Officerof" and "1000000 , ,".)
  docling   Docling's table model (TableFormer) reads the cells.
Everything after that is shared, so it can't favour either arm:
  - join a table split across pages (same column count, bottom of one page -> top of the next);
  - drop repeated headings and "(1) (2) (3)" column-number rows on the continuation page;
  - a row cut by the page break (empty first cell, not a heading) is joined to the row above;
  - two-row headings are combined ("Amount" over "CGST" -> "Amount CGST");
  - each row is written as "Heading: value | Heading: value".

Steps (Docling isn't installed in taxowl; LERAGS's environment has it, and only reads our PDFs):
    uv run ingestion/compare_tables.py extract-pymupdf
    /Users/aakash/Desktop/LERAGS/.venv/bin/python ingestion/compare_tables.py extract-docling
    uv run ingestion/compare_tables.py render
Output: ingestion/table_compare/<file>.md, both arms one after the other, to compare by eye.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = Path(__file__).resolve().parent / "table_compare"

HARD_SET = [
    "circulars/2024/238-32-2024-GST.pdf",   # Q&A split over pages 8-14
    "circulars/2018/75-49-2018-GST.pdf",    # split over pages 23-27
    "circulars/2025/254-11-2025-GST.pdf",   # Table III split over pages 5-6
    "circulars/2020/133-03-2020-GST.pdf",   # nested + split; numbers damaged by plain extraction
    "circulars/2020/136-06-2020-GST.pdf",   # nested + split
    "circulars/2019/123-42-2019--GST.pdf",  # nested + split
    "circulars/2018/41-15-2018-GST.pdf",    # blank forms
    "circulars/2019/99-18-2019-GST.pdf",    # blank form
    "circulars/2022/182-14-2022-GST.pdf",   # two-row headings
]

# Raw table format shared by both arms:
#   {"page": 1-based, "top": 0-1, "bottom": 0-1 (fractions of page height), "rows": [[cell text or None]]}


# ---------- arm 1: PyMuPDF ----------

def extract_pymupdf(path):
    import pymupdf

    tables = []
    with pymupdf.open(path) as pdf:
        for page in pdf:
            height = page.rect.height
            words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
            for t in page.find_tables().tables:
                rows = []
                for row in t.rows:
                    cells = []
                    for box in row.cells:
                        if box is None:  # covered by a merged cell
                            cells.append(None)
                            continue
                        x0, y0, x1, y1 = box
                        inside = [w for w in words
                                  if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
                        inside.sort(key=lambda w: (w[5], w[6], w[7]))  # reading order
                        cells.append(" ".join(w[4] for w in inside))
                    rows.append(cells)
                tables.append({"page": page.number + 1, "top": t.bbox[1] / height,
                               "bottom": t.bbox[3] / height, "rows": rows})
    return tables


# ---------- arm 2: Docling ----------

def make_docling_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption
    try:
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    except ImportError:
        from docling.datamodel.pipeline_options import AcceleratorDevice, AcceleratorOptions

    opts = PdfPipelineOptions()
    opts.do_ocr = False  # these PDFs have real text; OCR would only add errors
    opts.do_table_structure = True
    opts.table_structure_options.mode = TableFormerMode.ACCURATE
    opts.table_structure_options.do_cell_matching = True
    # CPU: Docling's layout model uses float64, which the Apple GPU (MPS) can't do (LERAGS finding).
    opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def extract_docling(path, converter):
    doc = converter.convert(str(path)).document
    tables = []
    for t in doc.tables:
        prov = t.prov[0]
        height = doc.pages[prov.page_no].size.height
        box = prov.bbox.to_top_left_origin(page_height=height)
        rows = [[cell.text for cell in row] for row in t.data.grid]
        tables.append({"page": prov.page_no, "top": box.t / height, "bottom": box.b / height, "rows": rows})
    return tables


# ---------- shared rules ----------

SERIAL = re.compile(r"^\(?([0-9]{1,3}|[a-zA-Z]|[ivxIVX]{1,5})[.)]?\)?\.?$")   # "1.", "(a)", "iv", "a ."
COLUMN_NUMBER = re.compile(r"^\(?\d{1,2}\)?$")                              # "(1)", "2"
NUMERIC = re.compile(r"[\d,.%\s()₹/-]*\d[\d,.%\s()₹/-]*")                     # "70%", "10,00,000"


def tidy(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\b(S|Sl|Sr)\s*\.\s*No\s*\.?", r"\1. No.", text)  # "S . No ." -> "S. No."
    return re.sub(r"\s+([.,;:)])", r"\1", text)                      # "a ." -> "a."


def is_column_numbers(row):
    filled = [c for c in row if c]
    return bool(filled) and all(COLUMN_NUMBER.fullmatch(c) for c in filled)


def is_data_row(row):
    # "(1)" fits SERIAL too, so rule out the "(1) (2) (3)" column-number row first.
    return bool(row and row[0] and SERIAL.fullmatch(row[0])) and not is_column_numbers(row)


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def looks_like_heading(row, headings):
    """A continuation-page row that repeats (part of) the headings: most of its words appear in them."""
    row_words = words(" ".join(c for c in row if c))
    head_words = words(" ".join(headings))
    return bool(row_words) and len(row_words & head_words) / len(row_words) >= 0.6


def split_headings(rows):
    """Return (headings per column, body rows). Row 0 is a heading row; row 1 is too when row 0 has
    merged (empty) cells and row 1 isn't data. A merged heading cell is carried to the right, so
    "Amount" over "CGST | SGST" becomes "Amount CGST", "Amount SGST"."""
    head_rows = [rows[0]]
    # A row holding values like "70%" or "10,00,000" is data, never a heading (circular 133/2020).
    has_values = len(rows) > 1 and any(c and NUMERIC.fullmatch(c) for c in rows[1])
    if (len(rows) > 1 and any(not c for c in rows[0]) and not is_data_row(rows[1])
            and not is_column_numbers(rows[1]) and not has_values):
        head_rows.append(rows[1])
    ncols = max(len(r) for r in rows)
    columns = [[] for _ in range(ncols)]
    for hr in head_rows:
        carry = ""
        for j in range(ncols):
            cell = hr[j] if j < len(hr) else ""
            if cell:
                carry = cell
            elif hr is head_rows[0]:
                cell = carry  # merged cell spanning to the right
            if cell and (not columns[j] or columns[j][-1] != cell):
                columns[j].append(cell)
    headings = [" ".join(parts) or f"Column {j + 1}" for j, parts in enumerate(columns)]
    body = rows[len(head_rows):]
    while body and is_column_numbers(body[0]):
        body = body[1:]
    return headings, body


def fill_merged(rows):
    """PyMuPDF marks a cell covered by a merged cell from above as None. Copy the value down, so
    each row carries it: in 254/11/2025 Table I, one "Functions" cell covers officers a, b and c.
    (Docling already repeats merged cells, so this changes nothing for it.)"""
    for i in range(1, len(rows)):
        for j, cell in enumerate(rows[i]):
            if cell is None and j < len(rows[i - 1]):
                rows[i][j] = rows[i - 1][j]
    return rows


def join_tables(raw):
    """Turn raw per-page tables into logical tables, joining ones split across pages."""
    joined = []
    for t in raw:
        rows = [[tidy(c) for c in r] for r in fill_merged([list(r) for r in t["rows"]]) if any(r)]
        if not rows:
            continue
        prev = joined[-1] if joined else None
        continues = (prev and t["page"] == prev["last_page"] + 1 and prev["last_bottom"] > 0.7
                     and t["top"] < 0.3 and len(rows[0]) == len(prev["headings"]))
        if continues:
            # Leading rows of the continuation: drop repeated headings and column numbers;
            # a row cut by the page break (empty first cell) is joined to the row above.
            while rows and not is_data_row(rows[0]):
                row = rows.pop(0)
                if is_column_numbers(row) or looks_like_heading(row, prev["headings"]):
                    continue
                if prev["body"]:
                    above = prev["body"][-1]
                    for j, cell in enumerate(row):
                        if cell and j < len(above):
                            above[j] = f"{above[j]} {cell}".strip()
                else:
                    prev["body"].append(row)
            prev["body"].extend(rows)
            prev["pages"].append(t["page"])
            prev["last_page"], prev["last_bottom"] = t["page"], t["bottom"]
        else:
            headings, body = split_headings(rows)
            joined.append({"headings": headings, "body": body, "pages": [t["page"]],
                           "last_page": t["page"], "last_bottom": t["bottom"]})
    return joined


def render_table(t):
    lines = [f"**Table on page(s) {', '.join(map(str, sorted(set(t['pages']))))}** "
             f"— {len(t['body'])} rows; headings: {' / '.join(t['headings'])}", ""]
    for row in t["body"]:
        parts = [f"{h}: {c}" for h, c in zip(t["headings"], row) if c]
        lines.append("- " + " | ".join(parts) if parts else "- (empty row)")
    return "\n".join(lines)


# ---------- commands ----------

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    OUT.mkdir(exist_ok=True)
    if command == "extract-pymupdf":
        raw = {f: extract_pymupdf(DOCS / f) for f in HARD_SET}
        (OUT / "raw_pymupdf.json").write_text(json.dumps(raw, ensure_ascii=False))
    elif command == "extract-docling":
        converter = make_docling_converter()
        raw = {}
        for f in HARD_SET:
            print("docling:", f, flush=True)
            raw[f] = extract_docling(DOCS / f, converter)
        (OUT / "raw_docling.json").write_text(json.dumps(raw, ensure_ascii=False))
    elif command == "render":
        arms = {arm: json.loads((OUT / f"raw_{arm}.json").read_text())
                for arm in ("pymupdf", "docling") if (OUT / f"raw_{arm}.json").exists()}
        for f in HARD_SET:
            parts = [f"# {f}"]
            for arm, raw in arms.items():
                tables = join_tables(raw[f])
                parts.append(f"\n## {arm}: {len(tables)} tables\n")
                parts += [render_table(t) + "\n" for t in tables]
            (OUT / (Path(f).stem + ".md")).write_text("\n".join(parts))
        print(f"wrote {len(HARD_SET)} files to {OUT.relative_to(ROOT)}/ (arms: {', '.join(arms)})")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
