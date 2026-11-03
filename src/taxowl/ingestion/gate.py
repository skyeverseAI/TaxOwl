"""The gate: which PyMuPDF tables look complex enough to send to the vision model (vlm.py)?

PyMuPDF reads simple tables right and complex ones wrong: shaded boxes become grid lines, merged
cells and multi-level headings land in the wrong columns, scanned pages give a wrong grid. Each
signal below is cheap (PyMuPDF's own grid and drawings, no model) and fires on one of those.

Measured by archive/experiments/gate_test.py on 8 held-out sets + the dev set (archive/notes/table_gate_feasibility.md):
every table PyMuPDF got wrong was caught (13 of 14; the 14th is a checker bug), 9 of 31 good
ones were sent anyway (that only costs time), and 56% of the corpus' table pages go to the model.

  merged       a cell spans several rows or columns (PyMuPDF leaves None in the spanned places)
  nested       a table inside a cell (the find_container rule of tables.py)
  colour       filled boxes inside the table that are neither black (borders) nor white
  white_boxes  2+ white filled boxes inside the table (179/11/2022: white boxes behind text lines)
  scan         an image covers half the page or more (a scan with a text layer)
  broken       0 data rows, a "Column N" heading, a cell made only of 2+ numbers, or a mostly
               empty grid

Not a signal: "the table runs over several pages". PyMuPDF joins those right 12 times in 14, and
it fired on 17 of 25 good tables.
"""

import re

SIGNALS = ["merged", "nested", "colour", "white_boxes", "scan", "broken"]
MIN_BOX = 4          # points; a filled box thinner than this is a drawn line, not a shaded area
BLACK, WHITE = 0.15, 0.97  # fill colours at or below / at or above this in every channel
SCAN_SHARE = 0.5     # an image covering this share of the page
NUMBER = re.compile(r"\(?[\d][\d,./%-]*\)?")  # one number-like token: "1,25,500", "(2)", "18%"


def inside(rect, box):
    return rect.x0 >= box[0] - 1 and rect.y0 >= box[1] - 1 and rect.x1 <= box[2] + 1 and rect.y1 <= box[3] + 1


def fills_in(page, boxes):
    """(colour boxes, white boxes) inside any table box on the page."""
    colour = white = 0
    for d in page.get_drawings():
        fill, rect = d.get("fill"), d.get("rect")
        if not fill or rect is None or rect.width < MIN_BOX or rect.height < MIN_BOX:
            continue
        if not any(inside(rect, b) for b in boxes):
            continue
        if all(c <= BLACK for c in fill):
            continue  # a border drawn as a thin black box, or a black cell
        if all(c >= WHITE for c in fill):
            white += 1
        else:
            colour += 1
    return colour, white


def is_scan(page):
    area = page.rect.width * page.rect.height
    return any((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) >= SCAN_SHARE * area
               for i in page.get_image_info())


def numbers_only(cell):
    toks = cell.split()
    return len(toks) >= 2 and all(NUMBER.fullmatch(t) for t in toks)


def page_signals(page, raws, tables):
    """The signals that fire on one page. `raws`: read_page_tables(page, ...); `tables`: the
    document's joined Tables (tables.to_tables) that have rows on this page. A page without
    raws has no table PyMuPDF can see, so nothing fires."""
    page_no = page.number + 1
    fired = set()
    if not raws:
        return fired
    if any(c is None for r in raws for row in r["grid"] for c in row):
        fired.add("merged")
    if any("inner" in row for r in raws for row in r["rows"]):
        fired.add("nested")
    colour, white = fills_in(page, [r["box"] for r in raws])
    if colour:
        fired.add("colour")
    if white >= 2:
        fired.add("white_boxes")
    if is_scan(page):
        fired.add("scan")
    if (any(r["sparse"] for r in raws)
            or not tables  # PyMuPDF saw a grid here but no table came out with rows on this page
            or any(re.fullmatch(r"Column \d+", h) for t in tables for h in t.headings)
            or any(numbers_only(c) for t in tables for row, p in zip(t.rows, t.row_pages) if p == page_no for c in row)):
        fired.add("broken")
    return fired
