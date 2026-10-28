"""Make a review sheet for every table the extractor's self-check flagged (plans/plan_ingestion.md, C2-C3).

Why: the held-out test (2026-10-28) showed a flag can mean lost content: in 56/30/2018 the table is
only a picture, so it came out as "Column 1-3" with no cells. Before choosing a fallback (Docling,
region OCR or a VLM), we count what the flags really are. Each flagged table gets a verdict:
  fine      the table is right; the flag is a false alarm (e.g. the table really has no headings)
  picture   no text behind the table in the PDF -> needs OCR on that region
  broken    text is there but the extraction is wrong (rows, columns or cells)

How:
  - Reads every data/extracted/**/*.json and keeps the documents whose `quality` is not empty.
  - tables_without_headings names tables and their page; tables_sparse names pages, so every table
    on that page gets a line. words_invented is not about tables: one line, no image.
  - empty_share = share of the table's cells that came out empty. Near 100% suggests a picture.
  - Each flagged page is saved as an image, to compare with its line in the sheet.

Usage:
    uv run python -m taxowl.extract       # first, so data/extracted/ is current
    uv run ingestion/review_flagged.py
Writes ingestion/flagged_review/review.csv and one PNG per flagged page; changes nothing else.
"""

import csv
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EXTRACTED = ROOT / "data" / "extracted"
OUT = ROOT / "ingestion" / "flagged_review"

DPI = 120
PREVIEW = 80  # characters of the first row shown in the sheet
COLUMNS = ["n", "file", "page", "flag", "table_id", "headings", "rows", "empty_share",
           "first_row", "image", "verdict", "note"]


def empty_share(table):
    cells = [c for row in table["rows"] for c in row]
    return f"{sum(not c.strip() for c in cells) / len(cells):.0%}" if cells else ""


def table_line(file, page, flag, table):
    first = " | ".join(table["rows"][0]) if table["rows"] else ""
    return {"file": file, "page": page, "flag": flag, "table_id": table["table_id"],
            "headings": " | ".join(table["headings"]), "rows": len(table["rows"]),
            "empty_share": empty_share(table), "first_row": first[:PREVIEW]}


def lines_for(doc):
    """One sheet line per flagged table (or flagged page with no table on it)."""
    file, tables = doc["file"], doc["tables"]
    by_id = {t["table_id"]: t for t in tables}
    for flag, value in doc["quality"].items():
        if flag == "tables_without_headings":
            for table_id, page in re.findall(r"(.+?) \(p\.(\d+)\)(?:, |$)", value):
                yield table_line(file, int(page), flag, by_id[table_id])
        elif flag == "tables_sparse":
            for page in map(int, re.findall(r"\d+", value)):
                on_page = [t for t in tables if page in t["row_pages"]]
                for table in on_page:
                    yield table_line(file, page, flag, table)
                if not on_page:
                    yield {"file": file, "page": page, "flag": flag, "note": "no table on this page"}
        else:
            yield {"file": file, "page": "", "flag": flag, "note": value}


def save_image(file, page):
    name = f"{Path(file).stem}-p{page}.png"
    if not (OUT / name).exists():
        with pymupdf.open(DOCS / file) as pdf:
            pdf[page - 1].get_pixmap(dpi=DPI).save(OUT / name)
    return name


def main():
    OUT.mkdir(exist_ok=True)
    docs = [json.loads(p.read_text()) for p in sorted(EXTRACTED.rglob("*.json"))]
    flagged = [d for d in docs if d["quality"]]

    lines = []
    for doc in flagged:
        for line in lines_for(doc):
            if line["page"]:
                line["image"] = save_image(line["file"], line["page"])
            lines.append(line)
    for n, line in enumerate(lines, 1):
        line["n"] = n

    with open(OUT / "review.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, restval="")
        writer.writeheader()
        writer.writerows(lines)

    tables = [l for l in lines if l.get("table_id")]
    looks_picture = [l for l in tables if l["empty_share"] in ("", "100%")]
    print(f"{len(flagged)} flagged documents -> {len(lines)} lines, {len(tables)} tables, "
          f"{len({(l['file'], l['page']) for l in lines if l['page']})} page images")
    print(f"tables with every cell empty (likely pictures): {len(looks_picture)}")
    for l in looks_picture:
        print(f"   p.{l['page']:<4} {l['table_id']}")
    print(f"\nSheet: {(OUT / 'review.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
