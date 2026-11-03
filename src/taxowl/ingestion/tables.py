"""Read tables with PyMuPDF and join them across pages (plans/plan_ingestion.md, C2).

The rules here were tested in archive/experiments/compare_tables.py on the 9 hardest files. Three steps:

  read_page_tables(page, words)  one page -> raw tables. Each cell's text is the PDF's own words
                                 whose centre lies inside the cell. A nested table (133/03/2020)
                                 is split into an outer and an inner raw table.
  join_tables(raws)              one document's raw tables -> logical tables: a table cut by a
                                 page break is joined; headings and merged cells are handled.
  to_tables(joined, doc_id)      logical tables -> schema Tables.

Every rule is general (positions and patterns), never "if file is X".
"""

import re
from html import escape

from taxowl.schema import Table

SLACK = 2  # points; cell edges drawn on the same line differ by a fraction of a point
CONTINUE_BOTTOM = 0.7  # a table ending below this share of the page height may continue...
CONTINUE_TOP = 0.3     # ...if the next page's first table starts above this share

SERIAL = re.compile(r"^\(?([0-9]{1,3}|[a-zA-Z]|[ivxIVX]{1,5})[.)]?\)?\.?$")  # "1.", "(a)", "iv", "a ."
COLUMN_NUMBER = re.compile(r"^\(?\d{1,2}\)?$")                             # "(1)", "2"
NUMERIC = re.compile(r"[\d,.%\s()₹/-]*\d[\d,.%\s()₹/-]*")                    # "70%", "10,00,000"
SERIAL_HEADING = re.compile(r"(S|Sl|Sr)\.?")  # "S." alone: an "S. No." heading broken over lines, not item S
SERIAL_HEADING_END = re.compile(r"No\.?|\.")  # ...whose next lines are "No" and "."
MAX_HEAD_ROWS = 6  # a heading split into text lines spans at most this many rows
# Marks the spot in an outer cell where a nested table sits, until the table has an id.
INNER = "\x00inner\x00"


# ---------- step 1: one page ----------

def read_page_tables(page, words):
    """Raw tables on one page. `words` is page.get_text("words"), already normalised.
    A raw table: {"page", "top", "bottom", "box", "rows": [{"cells": [text | None], "page", "inner"?}]}.
    A row whose cell holds a nested table carries that table as "inner".

    PyMuPDF's default reading also treats filled (shaded) boxes as table lines. Where a table has
    shaded columns, that cuts it into fragments (99/18/2019: 52 x 24 instead of 4 x 8). So if a
    table comes out fragmented, read the page again counting only real lines ("lines_strict"),
    and keep that if it isn't fragmented and holds as many words. Not the default, because many
    PDFs draw their borders as thin filled boxes, which "lines_strict" doesn't see."""
    raws = page_tables(page, words, "lines")
    if any(r["sparse"] for r in raws):
        strict = page_tables(page, words, "lines_strict")
        if n_words(strict) >= n_words(raws) and n_cells(strict) < n_cells(raws):
            return strict
    return raws


def sparse(grid):
    """10+ rows and most cells empty. A table cut into fragments looks like this (99/18/2019:
    52 x 24 cells for a 4 x 8 table); so does a blank form, which is why the stricter reading is
    only kept when it holds the same words in fewer cells."""
    cells = [c for row in grid for c in row]
    return len(grid) >= 10 and sum(1 for c in cells if not c) > len(cells) / 2


def n_cells(raws):
    return sum(len(r["grid"]) * len(r["grid"][0]) for r in raws if r["grid"])


def n_words(raws):
    def count(rows):
        return sum(len(c.split()) for r in rows for c in r["cells"] if c and INNER not in c) + sum(
            count(r["inner"]["rows"]) for r in rows if "inner" in r)
    return sum(count(r["rows"]) for r in raws)


def page_tables(page, words, strategy):
    height = page.rect.height
    raws = []
    for t in page.find_tables(strategy=strategy).tables:
        boxes = [row.cells for row in t.rows]
        grid = [[cell_text(box, words) if box else None for box in row] for row in boxes]
        base = {"page": page.number + 1, "top": t.bbox[1] / height, "bottom": t.bbox[3] / height,
                "box": t.bbox, "grid": grid, "sparse": sparse(grid)}
        container = find_container(boxes, t.bbox)
        if container is None:
            rows = rows_of(grid, base["page"])
            for r, row_boxes in zip(rows, boxes):
                r["section"] = is_section_row(row_boxes, t.bbox)
            raws.append({**base, "rows": rows})
            continue
        outer, inner = split_nested(grid, boxes, container)
        rows = rows_of(outer, base["page"])
        for r in rows:
            if has_inner(r["cells"]):
                r["inner"] = {**base, "rows": rows_of(inner, base["page"])}
        raws.append({**base, "rows": rows})
    return raws


def cell_text(box, words):
    x0, y0, x1, y1 = box
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    inside.sort(key=lambda w: (w[5], w[6], w[7]))  # reading order
    return " ".join(w[4] for w in inside)


def rows_of(grid, page):
    return [{"cells": cells, "page": page} for cells in grid]


def is_section_row(row_boxes, table_box):
    """One cell across the whole table: a section heading inside the table ("B. Place of supply
    ... advertising sector", 203/15/2023). Told by its shape, not its words."""
    real = [b for b in row_boxes if b]
    return (len(real) == 1 and len(row_boxes) > 1
            and real[0][0] <= table_box[0] + SLACK and real[0][2] >= table_box[2] - SLACK)


def has_inner(cells):
    return any(c and INNER in c for c in cells)


def find_container(boxes, table_box):
    """The cell holding a nested table, as (row, column), or None: some other row has 2+ real
    cells that all lie inside it. Not in the first row (that's a two-row heading, 182/14/2022)
    and not full width (a section-heading row, 134/04/2020). Checked on all 111 table files:
    plans/plan_ingestion.md, C2 "Nested tables"."""
    left, right = table_box[0], table_box[2]
    for i, row in enumerate(boxes):
        if i == 0:
            continue
        for j, box in enumerate(row):
            if box is None or (box[0] <= left + SLACK and box[2] >= right - SLACK):
                continue
            x0, x1 = box[0], box[2]
            for k, other in enumerate(boxes):
                real = [c for c in other if c]
                if (k != i and len(real) >= 2 and all(x0 - SLACK <= c[0] and c[2] <= x1 + SLACK for c in real)
                        and any(c[2] - c[0] < (x1 - x0) - SLACK for c in real)):
                    return i, j
    return None


def is_nested(table):
    """For a PyMuPDF table: does one of its cells hold another table? (Used by archive/experiments/find_nested.py.)"""
    return find_container([row.cells for row in table.rows], table.bbox) is not None


def split_nested(grid, boxes, container):
    """PyMuPDF merges the inner table's lines into the outer grid (133/03/2020: 10 columns
    instead of 3). Undo that. The container row's real cells define the outer columns; rows with
    2+ real cells inside the container's columns are the inner table. In the outer table the
    whole inner block becomes one row, whose container cell holds the INNER mark."""
    ci, cj = container
    x0, x1 = boxes[ci][cj][0], boxes[ci][cj][2]
    ncols = len(grid[0])
    col_x = [min((row[j][0] for row in boxes if row[j]), default=-1) for j in range(ncols)]
    band = [j for j in range(ncols) if x0 - SLACK <= col_x[j] < x1 - SLACK]

    # Outer columns: each real cell of the container row runs until the next real cell.
    starts = [j for j, box in enumerate(boxes[ci]) if box]
    groups = [list(range(s, e)) for s, e in zip(starts, starts[1:] + [ncols])]

    inner_rows = [k for k, row in enumerate(boxes) if k != ci and sum(1 for j in band if row[j]) >= 2]
    inner = [[grid[k][j] for j in band] for k in inner_rows]
    keep = [n for n in range(len(band)) if any(row[n] for row in inner)]  # drop empty sliver columns
    inner = [[row[n] for n in keep] for row in inner]

    def outer_row(ks, block=False):
        cells = []
        for g in groups:
            if block and g[0] in band:
                cells.append(INNER)  # the inner table's text lives in the inner table
                continue
            texts = [grid[k][j] for k in ks for j in g if grid[k][j]]
            covered = all(grid[k][j] is None for k in ks for j in g)
            cells.append(None if covered else " ".join(texts))
        return cells

    outer = []
    for k in range(len(grid)):
        if k not in inner_rows:
            outer.append(outer_row([k]))
        elif k == inner_rows[0]:
            outer.append(outer_row(inner_rows, block=True))
    return outer, inner


# ---------- step 2: one document ----------

def tidy(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\b(S|Sl|Sr)\s*\.\s*No\s*\.?", r"\1. No.", text)  # "S . No ." -> "S. No."
    return re.sub(r"\s+([.,;:)])", r"\1", text)                      # "a ." -> "a."


def real_text(cells):
    """Cell texts without the INNER mark (it's not a word from the PDF)."""
    return [c.replace(INNER, "").strip() for c in cells if c and c.replace(INNER, "").strip()]


def is_column_numbers(cells):
    real = real_text(cells)
    return bool(real) and all(COLUMN_NUMBER.fullmatch(c) for c in real)


def is_data_row(cells):
    # "(1)" fits SERIAL too, so rule out the "(1) (2) (3)" column-number row first. "S." fits it
    # as well, but is the start of an "S. No." heading broken over lines (141/11/2020).
    first = cells[0] if cells else None
    return (bool(first and SERIAL.fullmatch(first) and not SERIAL_HEADING.fullmatch(first))
            and not is_column_numbers(cells))


def words_of(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def looks_like_heading(cells, headings):
    """A continuation-page row that repeats (part of) the headings: most of its words appear in them."""
    row_words = words_of(" ".join(real_text(cells)))
    return bool(row_words) and len(row_words & words_of(" ".join(headings))) / len(row_words) >= 0.6


def fill_merged(rows):
    """A cell covered by a merged cell from above is None: copy the value down, so each row
    carries it ("Functions" in 254/11/2025 Table I covers officers a, b and c). Not in a section
    row: its empty cells are covered by its own cell from the left, not by the row above (copying
    there put 203/15/2023's text in twice)."""
    for above, row in zip(rows, rows[1:]):
        if row.get("section"):
            continue
        for j, cell in enumerate(row["cells"]):
            if cell is None and j < len(above["cells"]) and not has_inner([above["cells"][j]]):
                row["cells"][j] = above["cells"][j]


def heading_rows(rows):
    """How many rows at the top are headings, when the headings run over several rows; else None.
    PyMuPDF sometimes gives each text line of a heading its own row (56/30/2018: "Tariff item, /
    heading, sub- / heading or / Chapter"). Two signs show where such headings end: a column-number
    row "(1) (2) (3)" right below them, or an "S. No." heading broken over lines ("S." / "No" / ".",
    141/11/2020) becoming complete."""
    for k, r in enumerate(rows[:MAX_HEAD_ROWS + 1]):
        cells = r["cells"]
        if is_column_numbers(cells):
            return k or None
        if is_data_row(cells) or has_inner(cells):
            break
    if SERIAL_HEADING.fullmatch(rows[0]["cells"][0] or ""):
        k = 1
        while k < min(len(rows), MAX_HEAD_ROWS) and SERIAL_HEADING_END.fullmatch(rows[k]["cells"][0] or ""):
            k += 1
        return k
    return None


def split_headings(rows):
    """(headings per column, body rows, skipped column-number rows). Row 0 is a heading row;
    row 1 is too when row 0 has merged (empty) cells and row 1 isn't data; more rows when
    heading_rows() finds headings split into text lines. A merged heading cell is carried to the
    right: "Amount" over "CGST | SGST" becomes "Amount CGST", "Amount SGST"."""
    ncols = max(len(r["cells"]) for r in rows)
    first = rows[0]["cells"]
    if has_inner(first) or is_data_row(first):
        return [""] * ncols, rows, []  # starts with data, e.g. a table continued from a page we didn't join
    n_head = heading_rows(rows)
    head = [r["cells"] for r in rows[:n_head]] if n_head else [first]
    second = rows[1]["cells"] if len(rows) > 1 and not n_head else None
    has_values = second is not None and any(c and NUMERIC.fullmatch(c) for c in second)  # "70%" is data
    if (second is not None and any(not c for c in first) and not is_data_row(second)
            and not is_column_numbers(second) and not has_values and not has_inner(second)):
        head.append(second)
    columns = [[] for _ in range(ncols)]
    for n, cells in enumerate(head):
        carry = ""
        for j in range(ncols):
            cell = cells[j] if j < len(cells) else ""
            if cell:
                carry = cell
            elif n == 0:
                cell = carry  # merged heading cell spanning to the right
            if cell and (not columns[j] or columns[j][-1] != cell):
                columns[j].append(cell)
    body = rows[len(head):]
    skipped = []
    while body and is_column_numbers(body[0]["cells"]):
        skipped.append(body.pop(0))
    return [" ".join(parts) for parts in columns], body, skipped


def prepare(raw):
    rows = [{**r, "cells": list(r["cells"])} for r in raw["rows"]]
    fill_merged(rows)
    for r in rows:
        r["cells"] = [c if c and INNER in c else tidy(c) for c in r["cells"]]
    return [r for r in rows if any(r["cells"])]


def join_tables(raws):
    """Raw per-page tables -> logical tables {"headings", "body", ...}. Also returns the words
    dropped on purpose (repeated headings, column-number rows), so the self-check doesn't count
    them as lost."""
    joined, dropped = [], []
    for raw in raws:
        rows = prepare(raw)
        if not rows:
            continue
        prev = joined[-1] if joined else None
        continues = (prev and raw["page"] == prev["last_page"] + 1 and prev["last_bottom"] > CONTINUE_BOTTOM
                     and raw["top"] < CONTINUE_TOP and len(rows[0]["cells"]) == len(prev["headings"]))
        if not continues:
            headings, body, skipped = split_headings(rows)
            dropped += [c for r in skipped for c in real_text(r["cells"])]
            joined.append({"headings": headings, "body": body,
                           "last_page": raw["page"], "last_bottom": raw["bottom"]})
            continue
        # Leading non-data rows on the continuation page are, in this order: column numbers
        # (drop); more heading text while no data row has come yet (254/11/2025 Table III, whose
        # headings run onto the next page); repeated headings (drop); or the rest of a row cut by
        # the page break (join it to the row above, 238/32/2024). A section row ends this: it is a
        # row of its own, never the rest of the row above (203/15/2023).
        while rows and not is_data_row(rows[0]["cells"]) and not rows[0].get("section"):
            row = rows.pop(0)
            cells = row["cells"]
            if is_column_numbers(cells):
                dropped += real_text(cells)
            elif not prev["body"]:
                prev["headings"] = [f"{h} {c}".strip() if c else h for h, c in zip(prev["headings"], cells)]
            elif looks_like_heading(cells, prev["headings"]):
                dropped += real_text(cells)
            else:
                above = prev["body"][-1]
                for j, cell in enumerate(cells):
                    if cell and j < len(above["cells"]):
                        above["cells"][j] = f"{above['cells'][j]} {cell}".strip()
                if "inner" in row:
                    above["inner"] = row["inner"]
        prev["body"].extend(rows)
        prev["last_page"], prev["last_bottom"] = raw["page"], raw["bottom"]
    return joined, dropped


# ---------- step 3: Table objects ----------

def to_tables(joined, doc_id):
    """Logical tables -> schema Tables. A nested table becomes two: the outer one (its cell says
    "[table <id>]" where the inner table sits, and `html` shows both) and the inner one, so its
    rows can be searched like any other table's."""
    tables = []
    for t in joined:
        outer_id = f"{doc_id}:table-{len(tables) + 1}"
        inner_tables = []
        for r in t["body"]:
            if "inner" in r:
                inner_joined, _ = join_tables([r["inner"]])
                for it in inner_joined:
                    iid = f"{outer_id}.{len(inner_tables) + 1}"
                    inner_tables.append(make_table(it, iid))
                    r["inner_id"] = iid
        outer = make_table(t, outer_id)
        if inner_tables:
            outer.html = to_html(outer, {tb.table_id: tb for tb in inner_tables})
        tables.append(outer)
        tables.extend(inner_tables)
    return tables


def make_table(t, table_id):
    headings = [h or f"Column {j + 1}" for j, h in enumerate(t["headings"])]
    rows = [[c.replace(INNER, f"[table {r.get('inner_id', '?')}]") for c in r["cells"]] for r in t["body"]]
    return Table(table_id, headings, rows, [r["page"] for r in t["body"]])


def to_html(table, inner):
    """`inner` maps an inner table's id to the Table; its "[table <id>]" mark is replaced by it."""
    def cell(text):
        html = escape(text)
        for tid, tb in inner.items():
            mark = escape(f"[table {tid}]")
            if mark in html:
                html = html.replace(mark, to_html(tb, {}))
        return html
    head = "".join(f"<th>{escape(h)}</th>" for h in table.headings)
    body = "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in row) + "</tr>" for row in table.rows)
    return f"<table><tr>{head}</tr>{body}</table>"
