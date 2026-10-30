"""Gate test: can cheap checks on PyMuPDF's tables tell which ones need the vision model?
(plans/table_gate_feasibility.md)

The plan being tested: PyMuPDF reads every page. A table that looks complex goes to Gemini; the
rest stay with PyMuPDF. This script runs no model. It measures whether the "looks complex" checks
would have caught the tables PyMuPDF actually got wrong on the held-out sets, and how many pages
they would send.

Per gold case with a table (scans left out, they have their own OCR path):
  bad?     PyMuPDF's output fails any structure / headings / cells / numbers check of the case
           (the same checks as evals/check_ingestion.py)
  signals  which checks fire on the case's pages:
    merged       a cell spans several rows or columns (PyMuPDF leaves None in the spanned places)
    nested       a table inside a cell (the find_container rule of src/taxowl/tables.py)
    colour       filled boxes inside the table that are neither black (borders) nor white
    white_boxes  2+ white filled boxes inside the table (179/11/2022: white boxes behind text lines)
    scan         an image covers half the page or more (a scan with a text layer)
    broken       0 data rows, a "Column N" heading, a cell made only of 2+ numbers, or a
                 mostly empty grid
    self_check   the document's self-check flagged anything (doc-level, so coarse)
  unseen   the gold has a table but PyMuPDF found none on these pages: no signal can see it

What to read in the output:
  - recall: of the bad cases, how many some signal caught. Needs to be ~100%; a miss means a
    wrong table reaches the index silently.
  - sent for nothing: good cases sent anyway. This only costs time.
  - with --corpus: of all table pages in the corpus, how many the gate would send, and what
    Gemini would take for them.

The held-out sets hold no nested table, so two more sources are added:
  - evals/ingestion_gold.json (the dev set, with the nested 133/03/2020 p.5), scored like the rest
  - the pages ingestion/nested_report.csv lists (136, 123, 75, ...): no gold, so only "would the
    gate send it" is shown

Usage:
    uv run evals/gate_test.py                       # every evals/ingestion_heldout*.json + the dev set
    uv run evals/gate_test.py evals/ingestion_heldout_2031.json
    uv run evals/gate_test.py --corpus              # also the share of the corpus' table pages sent
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf

from taxowl.extract import DOCS, MANIFEST, SCAN_REPORT, extract, normalize
from taxowl import gate
from taxowl.tables import read_page_tables

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_ingestion import check_case  # noqa: E402  (evals/ is not a package)

ROOT = Path(__file__).resolve().parent.parent
DEV_GOLD = ROOT / "evals" / "ingestion_gold.json"  # the set the rules were built on; holds the nested 133 p.5
NESTED_REPORT = ROOT / "ingestion" / "nested_report.csv"
# No "multi_page": in the first run it fired on 17 of 25 good cases (PyMuPDF joins pages right 12
# times in 14), and the two bad ones it caught were caught by "broken" and "scan" too.
SIGNALS = gate.SIGNALS + ["self_check"]  # self_check is doc-level, measured here only
TABLE_KINDS = {"structure", "headings", "cells", "numbers"}
GEMINI_S_PER_PAGE, GEMINI_WORKERS, GEMINI_USD_PER_PAGE = 4.4, 8, 0.0012  # measured, evals/heldout_runs.md


def page_signals(pdf, page_no, doc):
    """The gate's signals on one page (src/taxowl/gate.py, the same code the pipeline runs), plus
    self_check, and whether PyMuPDF saw a table there at all."""
    page = pdf[page_no - 1]
    words = [(*w[:4], normalize(w[4]), *w[5:]) for w in page.get_text("words")]
    raws = read_page_tables(page, words)
    fired = gate.page_signals(page, raws, [t for t in doc.tables if page_no in t.row_pages])
    if raws and doc.quality:
        fired.add("self_check")
    return fired, bool(raws)


def heldout(gold_files, manifest, scans):
    cases = [(g.name, c) for g in gold_files for c in json.loads(g.read_text())["pages"]
             if c.get("tables") and c["file"] not in scans]
    docs, rows = {}, []
    for gold_name, case in cases:
        rel = case["file"]
        if rel not in docs:
            docs[rel] = extract(manifest[rel], scans)
        doc = docs[rel]
        fails = [(kind, what) for kind, passed, what in check_case(case, doc) if not passed and kind in TABLE_KINDS]
        fired, seen = set(), False
        with pymupdf.open(DOCS / rel) as pdf:
            for p in case["pages"]:
                f, s = page_signals(pdf, p, doc)
                fired |= f
                seen |= s
        rows.append({"set": gold_name, "id": case["id"], "bad": bool(fails), "fails": len(fails),
                     "seen": seen, "signals": sorted(fired), "first_fail": fails[0][1][:70] if fails else ""})

    print(f"{'set':<28} {'case':<44} {'bad':>4} {'seen':>5}  signals")
    for r in rows:
        print(f"{r['set']:<28} {r['id'][:44]:<44} {r['fails'] if r['bad'] else '-':>4} {'yes' if r['seen'] else 'NO':>5}  "
              f"{', '.join(r['signals']) or '-'}")

    bad = [r for r in rows if r["bad"]]
    good = [r for r in rows if not r["bad"]]
    print(f"\n{len(rows)} table cases: {len(bad)} bad (PyMuPDF failed a table check), {len(good)} good")
    print(f"\n{'signal':<12} {'catches bad':>12} {'fires on good':>14}")
    for s in SIGNALS:
        print(f"{s:<12} {sum(s in r['signals'] for r in bad):>5} of {len(bad):<5} {sum(s in r['signals'] for r in good):>6} of {len(good)}")

    for name, use in (("all signals", SIGNALS), ("without self_check", [s for s in SIGNALS if s != "self_check"])):
        caught = [r for r in bad if set(r["signals"]) & set(use)]
        sent_good = [r for r in good if set(r["signals"]) & set(use)]
        print(f"\nGate = any of {name}:")
        print(f"  recall: {len(caught)}/{len(bad)} bad cases sent to the model"
              + (f" ({100 * len(caught) / len(bad):.0f}%)" if bad else ""))
        print(f"  sent for nothing: {len(sent_good)}/{len(good)} good cases")
        missed = [r for r in bad if r not in caught]
        for r in missed:
            why = "PyMuPDF saw no table" if not r["seen"] else "no signal fired"
            print(f"  MISSED {r['set']} {r['id']}: {r['fails']} failed checks ({why}); first: {r['first_fail']}")
    return rows


def known_nested(manifest, scans):
    """The held-out sets hold no nested table, so the "nested" signal is also tried on the pages
    ingestion/find_nested.py found. No gold for most of them: this only shows whether the gate
    would send them (plans/plan_ingestion.md, "Nested tables": 133, 136, 123, 75 are real; 99 is a
    false alarm; 26 is a three-level heading grid)."""
    print(f"\nKnown nested pages ({NESTED_REPORT.relative_to(ROOT)}):")
    for row in csv.DictReader(NESTED_REPORT.open()):
        rel = row["file"]
        doc = extract(manifest[rel], scans)
        with pymupdf.open(DOCS / rel) as pdf:
            for p in map(int, row["pages"].split()):
                fired, seen = page_signals(pdf, p, doc)
                print(f"  {rel:<42} p.{p:<3} nested: {'yes' if 'nested' in fired else 'NO ':<4} "
                      f"sent: {'yes' if fired - {'self_check'} else 'NO '}  signals: {', '.join(sorted(fired)) or '-'}"
                      + ("" if seen else "  (PyMuPDF saw no table)"))


def corpus(manifest, scans):
    """How many of the corpus' table pages the gate (all signals but self_check) would send."""
    use = set(SIGNALS) - {"self_check"}
    table_pages = sent = 0
    per_signal = Counter()
    files = [m for m in manifest.values() if m["file"] not in scans]
    for n, meta in enumerate(files, 1):
        doc = extract(meta, scans)
        with pymupdf.open(DOCS / meta["file"]) as pdf:
            for p in range(1, len(pdf) + 1):
                fired, seen = page_signals(pdf, p, doc)
                if not seen:
                    continue
                table_pages += 1
                per_signal.update(fired)
                sent += bool(fired & use)
        if n % 50 == 0:
            print(f"  {n}/{len(files)} files ...", flush=True)
    print(f"\nCorpus: {table_pages} page(s) where PyMuPDF sees a table; the gate sends {sent} "
          f"({100 * sent / max(table_pages, 1):.0f}%)")
    for s in SIGNALS:
        print(f"  {s:<12} fires on {per_signal[s]} page(s)")
    print(f"Gemini for those {sent} pages: ~{sent * GEMINI_S_PER_PAGE / GEMINI_WORKERS / 60:.1f} min with "
          f"{GEMINI_WORKERS} at a time, ~${sent * GEMINI_USD_PER_PAGE:.2f}")
    print(f"Every table page instead: ~{table_pages * GEMINI_S_PER_PAGE / GEMINI_WORKERS / 60:.1f} min, "
          f"~${table_pages * GEMINI_USD_PER_PAGE:.2f}")


def main():
    args = [a for a in sys.argv[1:] if a != "--corpus"]
    # The dev set too, for its nested table (133) and two-row headings (182). PyMuPDF's rules were
    # built on it, so it looks better there than on unseen pages.
    gold_files = [Path(a) for a in args] or sorted((ROOT / "evals").glob("ingestion_heldout*.json")) + [DEV_GOLD]
    manifest = {m["file"]: m for m in map(json.loads, MANIFEST.open())}
    scans = {r["file"] for r in csv.DictReader(SCAN_REPORT.open()) if r["status"] == "scan"}
    print(f"gold: {', '.join(g.name for g in gold_files)}\n")
    heldout(gold_files, manifest, scans)
    known_nested(manifest, scans)
    if "--corpus" in sys.argv:
        corpus(manifest, scans)


if __name__ == "__main__":
    main()
