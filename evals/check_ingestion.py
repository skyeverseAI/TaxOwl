"""Score an extraction against the gold set (evals/ingestion_gold.json; plans/plan_ingestion.md, C3).

Input: one JSON file per PDF, holding an ExtractedDoc (src/taxowl/schema.py), at
<extracted dir>/<pdf path>.json, e.g. out/circulars/2025/254-11-2025-GST.pdf.json.
The checker doesn't care which tool made it, so every extractor version is scored the same way.

What each kind of check means (the gold file's "_about" has the details):
  text_has   phrase found in the page text, in the gold's order
  text_not   header/footer NOT in the page text
  numbers    found exactly in the page text or the tables (not as part of a longer number)
  structure  right number of columns and rows; nested table marked; no table where there is none
  headings   each column's heading contains the gold phrases
  cells      the cell in that row, under that heading, contains the gold text
Matching ignores whitespace and quote style and nothing else, so "10,00,000" must be exactly that.

A nested table (133/03/2020) is expected twice in ExtractedDoc.tables: the outer table with its
`html` filled, and the inner table as a Table of its own, so its rows can be checked (and chunked).

Rows are counted only among rows on the gold's pages (238's table runs to page 14; the gold
checks pages 8-9), so "row 2" means the second row that starts on those pages.

Usage:
    uv run evals/check_ingestion.py <extracted dir>
    uv run evals/check_ingestion.py <extracted dir> --show-passed
    uv run evals/check_ingestion.py <extracted dir> --gold evals/ingestion_heldout.json
--gold scores against another gold file in the same format (default: ingestion_gold.json), e.g. the
held-out pages that were never used to build the extractor's rules.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from taxowl.schema import ExtractedDoc, Table

GOLD = Path(__file__).resolve().parent / "ingestion_gold.json"


QUOTES = str.maketrans({c: "'" for c in "‘’‚‛′“”„‟″\""})


def squash(text):
    """Text without whitespace, and with every kind of quote mark the same (quote style isn't content)."""
    return re.sub(r"\s+", "", text or "").translate(QUOTES)


def load_doc(path):
    d = json.loads(path.read_text())
    d["tables"] = [Table(**t) for t in d["tables"]]
    return ExtractedDoc(**d)


# ---------- one gold case ----------

def check_case(case, doc):
    """Yield (kind, passed, what) for every check in one gold case."""
    pages = case["pages"]
    text = squash(" ".join(doc.pages[p - 1] for p in pages if p <= len(doc.pages)))

    pos = 0
    for phrase in case.get("text_has", []):
        found = text.find(squash(phrase), pos)
        if found >= 0:
            pos = found + len(squash(phrase))
        yield "text_has", found >= 0, phrase

    for phrase in case.get("text_not", []):
        yield "text_not", squash(phrase) not in text, phrase

    on_pages = [t for t in doc.tables if set(t.row_pages) & set(pages)]
    # "|" between cells, so neighbouring cells "0" and "10,00,000" don't read as "010,00,000".
    everything = text + "|" + "|".join(squash(c) for t in on_pages for row in t.rows for c in row)
    # Also with spaces kept: squashed, "2023, 5%" reads "2023,5%", and 5% looks like the tail of a
    # bigger number. Squashed is still needed so "168 (1)" matches "168(1)".
    spaced = " | ".join([" ".join(doc.pages[p - 1] for p in pages if p <= len(doc.pages))]
                        + [c for t in on_pages for row in t.rows for c in row])
    spaced = re.sub(r"\s+", " ", spaced).translate(QUOTES)
    for number in case.get("numbers", []):
        alone = lambda s: rf"(?<![\d,]){re.escape(s)}(?!\d|,\d)"  # not part of a longer number
        hit = (re.search(alone(squash(number)), everything)
               or re.search(alone(re.sub(r"\s+", " ", number).translate(QUOTES)), spaced))
        yield "numbers", bool(hit), number

    if case["tables"] == [] and "tables" in case:
        yield "structure", not on_pages, f"no table on page(s) {pages} (found {len(on_pages)})"

    used = set()
    for n, gold in enumerate(case["tables"], 1):
        yield from check_table(gold, n, on_pages, used, pages)


def check_table(gold, n, candidates, used, pages):
    label = f"table {n}"
    # Pick the extracted table that passes the most cell checks; ties go to the right column count.
    best, best_score = None, -1
    for t in candidates:
        if id(t) in used:
            continue
        score = sum(passed for _, passed, _ in cell_checks(gold, t, pages)) * 10 + (len(t.headings) == gold["columns"])
        if score > best_score:
            best, best_score = t, score
    if best is None:
        yield "structure", False, f"{label}: no matching table found"
        for _, _, what in cell_checks(gold, None, pages):
            yield "cells", False, f"{label}: {what}"
        return
    used.add(id(best))

    rows = rows_on(best, pages)
    yield "structure", len(best.headings) == gold["columns"], f"{label}: {gold['columns']} columns (got {len(best.headings)})"
    if "rows" in gold:
        yield "structure", len(rows) == gold["rows"], f"{label}: {gold['rows']} rows (got {len(rows)})"
    if "rows_min" in gold:
        yield "structure", len(rows) >= gold["rows_min"], f"{label}: at least {gold['rows_min']} rows (got {len(rows)})"
    if gold.get("nested"):
        yield "structure", bool(best.html), f"{label}: marked nested (html filled)"

    for j, phrases in enumerate(gold["headings"]):
        got = best.headings[j] if j < len(best.headings) else ""
        for phrase in phrases:
            yield "headings", squash(phrase) in squash(got), f"{label} column {j + 1}: {phrase!r} (got {got[:60]!r})"

    for kind, passed, what in cell_checks(gold, best, pages):
        yield kind, passed, f"{label}: {what}"


def rows_on(table, pages):
    return [row for row, page in zip(table.rows, table.row_pages) if page in pages]


def column_of(gold, phrase):
    """Which column a cell check means, from the GOLD headings (so a wrongly read heading
    doesn't also fail every cell under it). '' means any column."""
    if not phrase:
        return None
    matches = [j for j, parts in enumerate(gold["headings"]) if squash(phrase) in squash(" ".join(parts))]
    if len(matches) != 1:
        raise ValueError(f"gold heading phrase {phrase!r} matches columns {matches}; fix the gold file")
    return matches[0]


def cell_checks(gold, table, pages):
    rows = rows_on(table, pages) if table else []
    for row_no, phrase, value in gold["cells"]:
        what = f"row {row_no}, {phrase or 'any column'}: {value[:50]!r}"
        index = row_no - 1 if row_no > 0 else len(rows) + row_no
        if not 0 <= index < len(rows):
            yield "cells", False, what + " (row missing)"
            continue
        row = rows[index]
        j = column_of(gold, phrase)
        cells = row if j is None else row[j:j + 1]
        yield "cells", any(squash(value) in squash(c) for c in cells), what


# ---------- the whole gold set ----------

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    extracted = Path(sys.argv[1])
    show_passed = "--show-passed" in sys.argv
    gold_path = Path(sys.argv[sys.argv.index("--gold") + 1]) if "--gold" in sys.argv else GOLD
    gold = json.loads(gold_path.read_text())
    print(f"gold set: {gold_path.name} ({len(gold['pages'])} cases)")

    totals, passes = Counter(), Counter()
    for case in gold["pages"]:
        path = extracted / (case["file"] + ".json")
        results = (list(check_case(case, load_doc(path))) if path.exists()
                   else [("missing", False, f"no extraction at {path}")])
        ok = sum(passed for _, passed, _ in results)
        print(f"\n{case['id']}: {ok}/{len(results)}")
        for kind, passed, what in results:
            totals[kind] += 1
            passes[kind] += passed
            if show_passed or not passed:
                print(f"   {'ok  ' if passed else 'FAIL'} {kind:<9} {what}")

    print("\n" + "=" * 60)
    for kind in totals:
        print(f"{kind:<10} {passes[kind]:>4}/{totals[kind]:<4} {100 * passes[kind] / totals[kind]:5.1f}%")
    total, ok = sum(totals.values()), sum(passes.values())
    print(f"{'TOTAL':<10} {ok:>4}/{total:<4} {100 * ok / total:5.1f}%")


if __name__ == "__main__":
    main()
