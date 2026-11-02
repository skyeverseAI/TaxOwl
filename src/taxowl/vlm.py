"""Read a table's GRID with a vision model, keep the PDF's own WORDS (archive/notes/table_gate_feasibility.md).

Used by the ingestion pipeline for the tables the gate (gate.py) sends: shaded boxes, merged
cells, nested tables, broken grids. Measured on the held-out runs: 95.9% with Gemini 3.5 Flash
Lite against 85.6% for PyMuPDF alone (eval_results/heldout_runs.md).

  ask_cached(path, model, png, key)   one page image -> the model's tables (headings, rows, flags),
                                      cached on disk, failures returned, not raised
  snap_page(answer, words, regions)   the model's tables -> tables made of the PDF's words
  join(page_results)                  per-page tables -> tables joined across pages, from the
                                      model's own "continues" flags

The model's text only says WHICH words go in WHICH cell; the PDF says WHAT the words are. A cell
whose text isn't fully on the page is reported, never kept as typed. So a misread digit can't
reach the index.
"""

import base64
import json
import os
import re
import statistics
import time
import urllib.request
from collections import Counter
from pathlib import Path

from taxowl.extract import normalize
from taxowl.tables import tidy

ROOT = Path(__file__).resolve().parents[2]
URL = "https://openrouter.ai/api/v1/chat/completions"
DPI = 200       # small figures in dense tables stay readable; PNG is still ~1 MB
RETRIES = 2
NEAR = 6        # a cell's next word must be within this many line heights of the previous one
CASE_COST = 30   # points; see snap()
COLUMN_STEP = 20  # points; heading words this close to the column count as equally close
SLACK_PT = 3     # points around a table's area that still count as inside
HEAD_LINES = 10  # a heading row is at most this many text lines tall
MAX_STARTS = 40  # where a cell could start: try at most this many places, nearest the expected spot first
BOX_MARGIN_LINES = 2  # a table's box may reach this many text lines past its PyMuPDF area, no further

PROMPT = """This is one page of an Indian GST document (a circular, notification, instruction or form).
List every TABLE on the page, top to bottom.

A table is content laid out in rows and columns, with or without drawn lines. A box holding only
paragraphs, a letterhead, or a signature block is not a table.

For each table:
- headings: one string per column, left to right. If the headings have several levels, join them
  top to bottom with a space: "Amount" over "CGST" gives "Amount CGST". A heading cell spanning
  several columns is repeated in each column it covers. Leave out a row that only numbers the
  columns, like "(1) (2) (3)". If the table has no heading row on this page (it continues from the
  previous page without repeating them), give [].
- rows: one list per data row, top to bottom, with exactly one string per column. A row that starts
  with a label instead of a serial number (e.g. "Case 1") is still a data row.
- A cell spanning several ROWS: repeat its text in every row it covers. A cell spanning several
  COLUMNS (including a full-width section row): its text in the first column it covers, "" in the
  others. A small table drawn inside a cell: put its text in that cell. Empty cell: "".
- continues_previous: true if the table is cut at the top of this page, continuing a table from the
  previous page (it starts mid-table, with no title of its own).
- first_row_continues: true if the first row is the rest of a row cut at the bottom of the previous
  page (its serial-number cell is empty).

Copy text exactly as printed, character for character: keep spelling mistakes, numbers, commas,
brackets and punctuation. Do not correct, translate, summarise or add anything.
If the page has no table, return {"tables": []}."""

SCHEMA = {
    "name": "page_tables",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"tables": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "headings": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                "continues_previous": {"type": "boolean"},
                "first_row_continues": {"type": "boolean"},
            },
            "required": ["headings", "rows", "continues_previous", "first_row_continues"],
            "additionalProperties": False,
        }}},
        "required": ["tables"],
        "additionalProperties": False,
    },
}

DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})


# ---------- asking the model ----------

def load_key():
    """The OpenRouter key: from the environment (a server), else from .env (this machine), else
    None, and then the pipeline keeps PyMuPDF's tables and flags them. Never print the key."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env = ROOT / ".env"
    for line in (env.read_text().splitlines() if env.exists() else []):
        name, _, value = line.partition("=")
        if name.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip("\"'")
    return None


def ask_model(model, png, key):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
        "usage": {"include": True},  # OpenRouter then reports the real cost in usage.cost
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    start = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.load(resp)
    seconds = time.time() - start
    answer = json.loads(data["choices"][0]["message"]["content"])
    return {"answer": answer, "seconds": seconds, "usage": data.get("usage", {}),
            "model_used": data.get("model", "?"), "provider": data.get("provider", "?")}


def ask_cached(path, model, png, key, fresh=False):
    """One page -> the model's answer plus timing, cached at `path`. A failure is returned, not
    raised, so one bad page doesn't stop the run (its document then keeps the PyMuPDF tables)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not fresh:
        return {**json.loads(path.read_text()), "cached": True}
    for attempt in range(RETRIES + 1):
        try:
            result = ask_model(model, png, key)
            path.write_text(json.dumps(result, ensure_ascii=False))
            return {**result, "cached": False}
        except Exception as e:  # network, rate limit, a reply that isn't the schema
            if attempt == RETRIES:
                return {"error": repr(e)}
            time.sleep(3 * (attempt + 1))


# ---------- snapping the model's cells to PDF words ----------

def key(text):
    """What two words are compared by: no spaces, one kind of dash, any case. Only for matching;
    the cell keeps the PDF's own words."""
    return re.sub(r"\s+", "", normalize(text)).translate(DASHES).casefold()


class PageWords:
    """The PDF words of one page, ready to look up. `used` counts how often each word went into a
    cell: a merged cell the model repeats in several rows uses the same words again. `regions`:
    where PyMuPDF sees tables on the page; its grid may be wrong, but the area is a good guess, so
    a cell is looked for there first (else "Output liability" in a paragraph can win)."""

    def __init__(self, words, regions=()):
        self.words = words
        self.regions = list(regions)
        self.keys = [key(w[4]) for w in words]
        self.centre = [((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) for w in words]
        self.height = statistics.median([w[3] - w[1] for w in words]) if words else 10
        self.by_first = {}
        for j, k in enumerate(self.keys):
            if k:
                self.by_first.setdefault(k[0], []).append(j)
        self.used = Counter()

    def dist(self, a, b):
        (ax, ay), (bx, by) = self.centre[a], self.centre[b]
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    def outside(self, x, y, home=None):
        """Distance from a point to the table's own area (`home`), or else to the nearest PyMuPDF
        table area; 0 inside."""
        boxes = [home] if home else self.regions
        if not boxes:
            return 0
        return min(((max(b[0] - x, 0, x - b[2])) ** 2 + (max(b[1] - y, 0, y - b[3])) ** 2) ** 0.5
                   for b in boxes)

    def region_of(self, x, y):
        return next((b for b in self.regions if b[0] <= x <= b[2] and b[1] <= y <= b[3]), None)

    def same_case(self, j, target, pos):
        return normalize(self.words[j][4]).translate(DASHES).replace(" ", "") == target[pos:pos + len(self.keys[j])]

    def centre_of(self, idx):
        return (statistics.mean(self.centre[j][0] for j in idx), statistics.mean(self.centre[j][1] for j in idx))

    def text_of(self, idx):
        ordered = sorted(set(idx), key=lambda j: self.words[j][5:8])  # reading order
        return tidy(" ".join(self.words[j][4] for j in ordered))


def grow(target, exact, bounds, pos, chosen, pw):
    """Extend a match word by word: the next PDF word must spell the next part of the cell, and
    sit close to the last one (the word right after it in the PDF wins ties). Where no word fits,
    skip one of the model's words and go on, so one misread word doesn't lose the rest of the cell."""
    skipped = 0
    while pos < len(target):
        last = chosen[-1]
        fits = [j for j in pw.by_first.get(target[pos], []) if j not in chosen
                and target.startswith(pw.keys[j], pos)
                and (j == last + 1 or pw.dist(last, j) <= NEAR * pw.height)]
        if fits:
            j = min(fits, key=lambda j: (j != last + 1, not pw.same_case(j, exact, pos), pw.used[j] > 0,
                                         pw.dist(last, j)))
            chosen.append(j)
            pos += len(pw.keys[j])
            continue
        skipped += 1
        pos = next((b for b in bounds if b > pos), len(target))
    return chosen, skipped


def place_cost(idx, pw, anchor):
    """How far a match sits from where the cell should be. `anchor` may say:
      home   the table's own area (two tables on one page share words like "State tax / Union
             Territory tax", 98/17/2019);
      col_x  x of the cells already found in this column;
      row_y  the line of this row (from its other cells);
      min_y  the line of the row above: a row is below it, and the nearest line below wins, since
             rows follow each other (98/17/2019 p.3 has the same rows twice, Option 1 and 2);
      max_y  for a heading: the first row, which it sits above;
      top_y  for a heading: how far up it can reach."""
    x, y = pw.centre_of(idx)
    cost = 3 * pw.outside(x, y, anchor.get("home"))
    if anchor.get("col_x") is not None:
        cost += abs(x - anchor["col_x"])
    if anchor.get("row_y") is not None:
        cost += 2 * abs(y - anchor["row_y"])
    if anchor.get("min_y") is not None:
        below = y - anchor["min_y"]
        cost += 5 * max(0, -below) + 0.5 * max(0, below)
    if anchor.get("max_y") is not None:
        cost += 5 * max(0, y - anchor["max_y"])
    if anchor.get("top_y") is not None:
        cost += 5 * max(0, anchor["top_y"] - y)
    return cost


def snap(text, pw, anchor):
    """The model's cell text -> (indices of PDF words, complete?). Complete means every character
    the model wrote was found, in order, among nearby PDF words."""
    parts = [k for k in (key(t) for t in normalize(text).split()) if k]
    if not parts:
        return [], True
    target = "".join(parts)
    exact = "".join(re.sub(r"\s+", "", normalize(t)).translate(DASHES) for t in normalize(text).split())
    exact = exact if len(exact) == len(target) else target  # casefold changed a length (rare): no case preference
    bounds = [sum(len(p) for p in parts[:i]) for i in range(len(parts))]
    best = None
    for n_lead, b in enumerate(bounds):  # normally the cell's first word; later ones if it isn't on the page
        starts = [j for j in pw.by_first.get(target[b], []) if target.startswith(pw.keys[j], b)]
        starts = sorted(starts, key=lambda j: place_cost([j], pw, anchor))[:MAX_STARTS]
        for j in starts:
            chosen, skipped = grow(target, exact, bounds, b + len(pw.keys[j]), [j], pw)
            found = sum(len(pw.keys[c]) for c in chosen)
            case_misses = sum(not pw.same_case(c, exact, target.find(pw.keys[c])) for c in chosen)
            # Jumps: next word not the PDF's next word. A cell's words follow each other in the PDF,
            # so of two complete matches the one in one piece wins: "Statement 3 under..." took its
            # "Statement" from the "Statement 3A" line below, and read "3 under ... Statement"
            # (125/44/2019 p.26). A different case costs as much as being ~2 lines off: it decides
            # between near matches, but never pulls a cell into another table.
            jumps = sum(b != a + 1 for a, b in zip(chosen, chosen[1:]))
            score = (found, -(skipped + n_lead), -jumps,
                     -(place_cost(chosen, pw, anchor) + CASE_COST * case_misses), -sum(pw.used[c] for c in chosen))
            if best is None or score > best[0]:
                best = (score, chosen)
        if best and best[0][0] == len(target):
            break
    # Less than half found: the PDF words are a different cell's ("2" for a misread "2,46,500").
    # Leave the cell empty; it is reported, and its real words show up as left over.
    if best is None or best[0][0] < len(target) / 2:
        return [], False
    return best[1], best[0][0] == len(target)


def snap_heading(text, pw, col_x, zone, below, prev_x=None):
    """A heading -> (PDF word indices, complete?). Not like a cell: a multi-level heading's words
    aren't next to each other in the PDF ("Stage of Return Filing" spans every column, and each
    column has its own "Stage", 26/26/2017), so each word is taken from the table's area (`zone`),
    above the first row (`below`), nearest the column (`col_x`). The order is the model's, the
    words are the PDF's. Inside the area only, else a line above the table that happens to say
    "S. No." becomes a heading (Corrigendum to 76/50/2018). A blank form has no rows to place the
    columns, so there the word just right of the previous column's heading (`prev_x`) wins."""
    parts = [k for k in (key(t) for t in normalize(text).split()) if k]
    if not parts:
        return [], True
    target = "".join(parts)
    exact = "".join(re.sub(r"\s+", "", normalize(t)).translate(DASHES) for t in normalize(text).split())
    exact = exact if len(exact) == len(target) else target
    bounds = [sum(len(p) for p in parts[:i]) for i in range(len(parts))]
    starts = set(bounds)
    x0, y0, x1, y1 = zone
    allowed = {j for j, (x, y) in enumerate(pw.centre)
               if x0 - SLACK_PT <= x <= x1 + SLACK_PT and y0 - SLACK_PT <= y <= y1 + SLACK_PT
               and (below is None or y < below - pw.height / 2)}
    chosen, pos, found = [], 0, 0
    while pos < len(target):
        fits = [j for j in pw.by_first.get(target[pos], []) if j in allowed and j not in chosen
                and target.startswith(pw.keys[j], pos)]
        if fits:
            # Narrow columns split words in the PDF ("Sup plier", 106/25/2019): the rest of a word
            # is the PDF's next word, not a matching letter elsewhere. Otherwise: same case, near
            # the column (in steps of COLUMN_STEP, so a whole word beats a split one close by),
            # then the longer word.
            last = chosen[-1] if chosen else None
            mid_word = pos not in starts and last is not None
            def place(j):
                x = pw.centre[j][0]
                if col_x is not None:
                    return abs(x - col_x)
                if prev_x is not None:
                    return abs(x - prev_x) + (1000 if x < prev_x - SLACK_PT else 0)
                return x
            def dead_end(j):
                # A word that spells only the start of the model's word ("(Rs." for "(Rs.)") is
                # fine if the PDF's next word goes on with it ("Sup" + "plier"); otherwise the rest
                # can't be found and is lost. "(Rs." from the column before won over "(Rs.)" and
                # the ")" was lost (Instruction 01/2023 p.7).
                end = pos + len(pw.keys[j])
                if end in starts or end >= len(target):
                    return False
                return not (j + 1 < len(pw.keys) and pw.keys[j + 1] and target.startswith(pw.keys[j + 1], end))
            j = min(fits, key=lambda j: (mid_word and j != last + 1, dead_end(j), not pw.same_case(j, exact, pos),
                                         round(place(j) / COLUMN_STEP), -len(pw.keys[j])))
            chosen.append(j)
            pos += len(pw.keys[j])
            found += len(pw.keys[j])
            continue
        pos = next((b for b in bounds if b > pos), len(target))
    if found < len(target) / 2:
        return [], False
    return chosen, found == len(target)


def pick_home(t, pw):
    """Which PyMuPDF table area this table is in: the one whose words spell most of its cells. Found
    before snapping, because the first cell alone can't tell ("Integrated tax" is in both tables of
    98/17/2019 p.2, and the first one on the page is the wrong one).
    A blank form has no cell text, so there the heading words decide, one by one (a multi-level
    heading's words aren't next to each other in the PDF). Without this the form had no area, its
    headings were looked for on the whole page, and the box stretched over the paragraphs above
    and below it, which then left the page text (24/24/2017 p.2, 106/25/2019 p.7, 36/10/2018 p.7)."""
    cells = [key(c) for row in t["rows"] for c in row]
    if not any(cells):
        cells = [k for h in t["headings"] for k in (key(w) for w in normalize(h).split()) if len(k) >= 3]
    best, best_score = None, 0
    for b in pw.regions:
        inside = sorted((j for j, (x, y) in enumerate(pw.centre) if b[0] <= x <= b[2] and b[1] <= y <= b[3]),
                        key=lambda j: pw.words[j][5:8])
        spelled = "".join(pw.keys[j] for j in inside)
        score = sum(len(k) for k in cells if k and k in spelled)
        if score > best_score:
            best, best_score = b, score
    return best


def snap_table(t, pw, page_no, log, floor=None):
    """One table from the model -> headings and rows made of PDF words, the PDF words it used, and
    a log line per cell: the model's text next to the PDF's. `floor`: the last row of the table
    above on this page; the model lists tables top to bottom, so this one starts below it."""
    ncols = max([len(t["headings"])] + [len(r) for r in t["rows"]])
    home = pick_home(t, pw)
    col_x, found, prev_y, first_y, last_y = {}, {}, floor, None, floor  # found: where -> (idx, model text, complete)

    def one(text, where, anchor):
        idx, complete = snap(text, pw, anchor)
        pw.used.update(idx)
        found[where] = (idx, text, complete)
        return idx

    def undo(where):
        pw.used.subtract(found[where][0])

    rows = []
    for r_no, row in enumerate(t["rows"], 1):
        row = (row + [""] * ncols)[:ncols]
        ys, row_y = {}, None
        for c in sorted(range(ncols), key=lambda c: -len(row[c])):  # long cells first: they pin the row's line
            if not row[c].strip():
                continue
            anchor = {"home": home, "col_x": statistics.mean(col_x[c]) if col_x.get(c) else None,
                      "row_y": row_y, "min_y": prev_y}
            idx = one(row[c], (r_no, c), anchor)
            if idx:
                ys[c] = pw.centre_of(idx)[1]
                row_y = ys[c] if row_y is None else row_y
        # A row's cells share a line. A cell found far off it took the same words from elsewhere
        # ("Integrated tax" in a heading above): look again on the row's line.
        if len(ys) >= 2:
            line = statistics.median(ys.values())
            for c, y in ys.items():
                if abs(y - line) > 1.5 * pw.height:
                    undo((r_no, c))
                    anchor = {"home": home, "col_x": statistics.mean(col_x[c]) if col_x.get(c) else None,
                              "row_y": line, "min_y": prev_y}
                    idx = one(row[c], (r_no, c), anchor)
                    ys[c] = pw.centre_of(idx)[1] if idx else line
            row_y = line
        for c in ys:
            if found[(r_no, c)][0]:
                col_x.setdefault(c, []).append(pw.centre_of(found[(r_no, c)][0])[0])
        rows.append([pw.text_of(found[(r_no, c)][0]) if (r_no, c) in found else "" for c in range(ncols)])
        if row_y is not None:
            prev_y = row_y
            last_y = max(row_y, last_y or row_y)
            first_y = row_y if first_y is None else first_y

    headings = (t["headings"] + [""] * ncols)[:ncols]
    # Where headings can be: the table's area; without one (no PyMuPDF table here), the page's
    # width and up to HEAD_LINES text lines above the first row. With neither, nowhere: the whole
    # page would let a heading take words from the paragraphs (the headings stay "Column n").
    if home:
        zone = home
    elif first_y is not None:
        zone = (0, first_y - HEAD_LINES * pw.height, 10_000, first_y)
    else:
        zone = None
    prev_x = None
    for c, h in enumerate(headings):
        if h.strip() and zone is None:
            found[("heading", c)] = ([], h, False)
            headings[c] = ""
        elif h.strip():
            idx, complete = snap_heading(h, pw, statistics.mean(col_x[c]) if col_x.get(c) else None, zone,
                                         first_y, prev_x)
            if idx:
                prev_x = pw.centre[idx[-1]][0]  # the last word is the column's own level
            pw.used.update(idx)
            found[("heading", c)] = (idx, h, complete)
            # The model's order, the PDF's words.
            headings[c] = tidy(" ".join(pw.words[j][4] for j in idx))

    used = {j for idx, _, _ in found.values() for j in idx}
    for where, (idx, text, complete) in found.items():
        name = f"heading col {where[1] + 1}" if where[0] == "heading" else f"row {where[0]} col {where[1] + 1}"
        log.append({"page": page_no, "where": name, "model": text, "pdf": pw.text_of(idx), "match": complete})
    box = None
    if used:
        ws = [pw.words[j] for j in used]
        box = (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))
        if home:
            # Never wider than the table's area (a little more, for a row PyMuPDF cut off): every
            # word inside the box leaves the page text, so one cell snapped far away would take
            # the paragraphs between with it. A word outside the box stays in the page text too.
            m = BOX_MARGIN_LINES * pw.height
            box = (max(box[0], home[0] - m), max(box[1], home[1] - m),
                   min(box[2], home[2] + m), min(box[3], home[3] + m))
    return {"headings": headings, "rows": rows, "box": box, "used": used, "last_y": last_y,
            "continues_previous": t["continues_previous"], "first_row_continues": t["first_row_continues"]}


# ---------- one page, then one document ----------

def snap_page(answer, words, regions, page_no, log):
    """The model's tables for one page -> snapped tables, and how many PDF words inside their
    boxes no cell took (a row the model dropped shows up here). `words`: the page's normalised
    PyMuPDF words; `regions`: where PyMuPDF sees tables (the area each table is looked for in)."""
    pw = PageWords(words, regions)
    tables, floor = [], None
    for t in answer["tables"]:
        tables.append(snap_table(t, pw, page_no, log, floor))
        floor = tables[-1]["last_y"] if tables[-1]["last_y"] is not None else floor
    left = 0
    for t in tables:
        if t["box"]:
            x0, y0, x1, y1 = t["box"]
            left += sum(1 for j, (cx, cy) in enumerate(pw.centre)
                        if x0 <= cx <= x1 and y0 <= cy <= y1 and j not in t["used"])
    return tables, left


def join(page_results):
    """The model's per-page tables -> logical tables, joined where the model says a table goes on."""
    joined = []
    for page_no, tables in page_results:
        for k, t in enumerate(tables):
            prev = joined[-1] if joined else None
            ncols = len(t["headings"])
            if (k == 0 and t["continues_previous"] and prev and prev["last_page"] == page_no - 1
                    and ncols == len(prev["headings"])):
                rows = t["rows"]
                # Only when the first cell (serial number) is empty, as the prompt says: the model
                # also flags a new entry as a continuation (51/25/2018 p.2 "Sl. No. 25(a)").
                if t["first_row_continues"] and rows and prev["rows"] and not rows[0][0].strip():
                    above = prev["rows"][-1][0]
                    above[:] = [f"{a} {b}".strip() for a, b in zip(above, rows[0])]
                    rows = rows[1:]
                prev["rows"] += [(r, page_no) for r in rows]
                prev["last_page"] = page_no
                continue
            joined.append({"headings": t["headings"], "rows": [(r, page_no) for r in t["rows"]], "last_page": page_no})
    return joined


