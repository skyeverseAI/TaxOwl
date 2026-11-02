"""Find tables that sit inside another table's cell ("nested tables"), in every PDF with tables.

Why: a nested table can't be written as a Markdown table, so these need HTML (plans/plan_ingestion.md, C2).
They're also where table readers break, so we want the full list, not just the 3 we found by eye.

How PyMuPDF shows a nested table: NOT as two tables. The inner table's lines are merged into the
outer table's grid, so one table comes back with extra columns (circular 133/03/2020, page 5:
the real table has 3 columns, PyMuPDF returns 10). Per row, cells are either real or "covered"
(hidden under a merged cell):

    ###.......   outer row: 3 cells, the third one spans the whole right side
    ...######.   inner row: real cells only inside that big third cell, the rest covered

Rule: a table is nested if some row has 2+ real cells that all lie inside ONE wide cell of
another row (by position on the page). Two exceptions have the same shape but are not nested:
  - the wide cell is in the first row: a two-row heading ("Amount" over "CGST | SGST", 182/14/2022);
  - the wide cell spans the full table width: a section heading row ("During CIRP period", 134/04/2020).
A false alarm only costs a little (that table is written as HTML instead of Markdown); a missed
nested table gets mangled. So when unsure, the rule says "nested".

Usage:
    uv run ingestion/find_nested.py
Reads ingestion/table_report.csv (files with tables); writes ingestion/nested_report.csv.
"""

import csv
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TABLE_REPORT = Path(__file__).resolve().parent / "table_report.csv"
REPORT = Path(__file__).resolve().parent / "nested_report.csv"

SLACK = 2  # points; cell edges drawn on the same line differ by a fraction of a point


def is_nested(table):
    rows = [[c for c in row.cells if c] for row in table.rows]  # real cells only, as (x0, y0, x1, y1)
    left, right = table.bbox[0], table.bbox[2]
    for i, row in enumerate(rows):
        if i == 0:
            continue  # two-row headings, see above
        for x0, _, x1, _ in row:
            if x0 <= left + SLACK and x1 >= right - SLACK:
                continue  # a full-width row is a section heading ("During CIRP period"), not a container
            for k, other in enumerate(rows):
                if (k != i and len(other) >= 2
                        and all(x0 - SLACK <= c[0] and c[2] <= x1 + SLACK for c in other)
                        and any(c[2] - c[0] < (x1 - x0) - SLACK for c in other)):
                    return True
    return False


def main():
    files = [r["file"] for r in csv.DictReader(TABLE_REPORT.open()) if int(r["tables_found"] or 0) > 0]
    rows = []
    for n, rel in enumerate(files, 1):
        print(f"\rchecking {n}/{len(files)}", end="", flush=True)
        with pymupdf.open(DOCS / rel) as pdf:
            pages = [page.number + 1 for page in pdf
                     if any(is_nested(t) for t in page.find_tables().tables)]
        if pages:
            rows.append({"file": rel, "pages": " ".join(map(str, pages))})
    print()
    with REPORT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "pages"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} of {len(files)} table files have a nested table:")
    for r in rows:
        print(f"  {r['file']}  pages {r['pages']}")
    print(f"\nReport: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
