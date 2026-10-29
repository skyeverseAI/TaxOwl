"""Bake-off: let a vision model (Gemini via OpenRouter) read the table GRID, keep the PDF's own WORDS.

Why: the held-out runs (evals/heldout_runs.md) lost most of their points on tables, and the
self-check didn't see it: shaded boxes read as grid lines, multi-level headings, rows glued at page
breaks. A vision model sees the page the way a person does, so it should get the structure right.
But it re-types what it sees and can change a digit, and "numbers never change" is rule one.

How, per document:
  1. Every page of a file with a table becomes a PNG and goes to the model, a few at a time.
     The model returns each table as headings + rows of cell text (a JSON schema fixes the shape).
  2. Snap: every cell the model wrote is looked up among the PDF words on that page, and the cell
     becomes those PDF words. The model's text only says WHICH words go in WHICH cell; the PDF says
     WHAT the words are. A cell whose text isn't fully on the page is reported, never kept as typed.
     The model's text is saved next to the PDF's (report.json), so the two can be compared.
  3. Tables continued on the next page are joined from the model's own flags (continues_previous,
     first_row_continues), not from our row-pattern rules.
  4. Page text = the words outside the tables, as in src/taxowl/extract.py, plus the same self-check.

Files without a table case in the gold, and the 8 OCR scans, are copied from the PyMuPDF run, so
the whole held-out run can be scored with the usual checker and compared one to one.

Measured for each run: seconds per page, tokens, and the cost OpenRouter reports (usage.cost),
next to the time PyMuPDF takes for the same files. Answers are cached, so re-running to change the
snapping costs nothing; --fresh asks the model again.

Usage:
    uv run ingestion/vlm_tables.py google/gemini-3.5-flash-lite evals/ingestion_heldout_2031.json
    uv run ingestion/vlm_tables.py google/gemini-3.8-flash evals/ingestion_heldout_20*.json --workers 8
then score it:
    uv run evals/check_ingestion.py data/extracted_vlm/<model> --gold evals/ingestion_heldout_2031.json
Needs OPENROUTER_API_KEY in .env (project root). Output: data/extracted_vlm/<model>/ (git-ignored).
"""

import csv
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pymupdf

from taxowl.extract import MANIFEST, SCAN_REPORT, extract, normalize, page_lines, self_check, strip_headers
from taxowl.schema import ExtractedDoc, Table
from taxowl.tables import read_page_tables
from taxowl.vlm import DPI, ask_cached, join, load_key, snap_page

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "data" / "extracted_vlm"
WORKERS = 8     # pages sent at the same time


# ---------- one document ----------

def table_pages(rel):
    """Per page: the normalised PDF words, the PNG for the model, and where PyMuPDF sees tables.
    Every page goes to the model, not only those where PyMuPDF sees a table: it misses tables
    without lines, and a table then can't be joined across pages (251/08/2025 pp.1-4). At about
    $0.002 a page that's cheaper than being wrong."""
    pages = []
    with pymupdf.open(DOCS / rel) as pdf:
        for page in pdf:
            words = [(*w[:4], normalize(w[4]), *w[5:]) for w in page.get_text("words")]
            raws = read_page_tables(page, words)
            png = page.get_pixmap(dpi=DPI).tobytes("png")
            pages.append({"words": words, "png": png, "regions": [r["box"] for r in raws]})
    return pages



def build_doc(meta, pages, answers, log):
    """PDF words + the model's answers -> an ExtractedDoc in the usual shape."""
    rel = meta["file"]
    doc_id = meta.get("number") or Path(rel).stem
    lines, source, page_results, left = [], [], [], 0
    for page_no, page in enumerate(pages, 1):
        words = page["words"]
        source += [w[4] for w in words]
        tables = []
        if page_no in answers:
            tables, page_left = snap_page(answers[page_no], words, page["regions"], page_no, log)
            left += page_left
            page_results.append((page_no, tables))
        lines.append(page_lines(words, [t["box"] for t in tables if t["box"]]))
    texts, removed = strip_headers(lines)
    out_tables = []
    for n, t in enumerate(join(page_results), 1):
        headings = [h or f"Column {j + 1}" for j, h in enumerate(t["headings"])]
        out_tables.append(Table(f"{doc_id}:table-{n}", headings, [r for r, _ in t["rows"]],
                                [p for _, p in t["rows"]], reader="vlm"))
    doc = ExtractedDoc(rel, meta["sha256"], ["\n".join(p) for p in texts], out_tables)
    doc.quality = self_check(doc, source, removed, [])
    misses = [e for e in log if not e["match"]]
    if misses:
        doc.quality["cells_not_in_pdf"] = f"{len(misses)} of {len(log)} cells, e.g. " + "; ".join(
            f"p.{e['page']} {e['where']}: {e['model'][:30]!r}" for e in misses[:3])
    if left:
        doc.quality["words_left_in_table"] = f"{left} PDF word(s) inside a table that no cell took"
    return doc


# ---------- the run ----------

def main():
    args = sys.argv[1:]
    workers = WORKERS
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    fresh = "--fresh" in args
    args = [a for a in args if a != "--fresh"]
    if len(args) < 2:
        sys.exit(__doc__)
    model, gold_files = args[0], [Path(a) for a in args[1:]]
    out = OUT / model.replace("/", "_")
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    manifest = {m["file"]: m for m in map(json.loads, MANIFEST.open())}
    scans = {r["file"] for r in csv.DictReader(SCAN_REPORT.open()) if r["status"] == "scan"}
    cases = [c for g in gold_files for c in json.loads(g.read_text())["pages"]]
    files = sorted({c["file"] for c in cases})
    table_files = sorted({c["file"] for c in cases if c.get("tables")} - scans)

    # The baseline: PyMuPDF on the same files, timed. Files without a table case are scored from it.
    pymupdf_seconds, baseline = {}, {}
    for rel in files:
        start = time.time()
        baseline[rel] = extract(manifest[rel], scans)
        pymupdf_seconds[rel] = time.time() - start

    pages = {rel: table_pages(rel) for rel in table_files}
    jobs = [(rel, n, p["png"]) for rel in table_files for n, p in enumerate(pages[rel], 1) if p["png"]]
    print(f"{model}: {len(jobs)} table page(s) in {len(table_files)} file(s), {workers} at a time ...")
    key_ = load_key()
    if key_ is None:
        sys.exit("OPENROUTER_API_KEY not found in the environment or .env")
    start = time.time()
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda j: ask_cached(cache / (j[0].replace("/", "__") + f"__p{j[1]}.json"),
                                                     model, j[2], key_, fresh), jobs))
    wall = time.time() - start

    report = {"model": model, "gold": [g.name for g in gold_files], "pages": [], "cells": []}
    for rel in files:
        target = out / (rel + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        answers = {n: r for (f, n, _), r in zip(jobs, results) if f == rel}
        if rel not in table_files or any("error" in r for r in answers.values()):
            doc = baseline[rel]
            if rel in table_files:
                doc.quality["vlm_failed"] = "; ".join(r["error"] for r in answers.values() if "error" in r)[:300]
        else:
            log = []
            doc = build_doc(manifest[rel], pages[rel], {n: r["answer"] for n, r in answers.items()}, log)
            report["cells"] += [{"file": rel, **e} for e in log]
        target.write_text(json.dumps(asdict(doc), ensure_ascii=False))
        for n, r in answers.items():
            u = r.get("usage", {})
            report["pages"].append({
                "file": rel, "page": n, "seconds": r.get("seconds"), "cached": r.get("cached"),
                "error": r.get("error"), "model_used": r.get("model_used"),
                "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"),
                "tokens_thinking": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "cost": u.get("cost")})

    # ---------- what it cost ----------
    ok = [p for p in report["pages"] if not p["error"]]
    secs = [p["seconds"] for p in ok]
    cost = sum(p["cost"] or 0 for p in ok)
    print(f"\n{'file':<48} {'page':>4} {'sec':>6} {'in':>6} {'out':>6} {'think':>6} {'$':>8}")
    for p in report["pages"]:
        if p["error"]:
            print(f"{p['file'][-48:]:<48} {p['page']:>4}  ERROR {p['error'][:60]}")
            continue
        print(f"{p['file'][-48:]:<48} {p['page']:>4} {p['seconds']:>6.1f} {p['tokens_in'] or 0:>6} "
              f"{p['tokens_out'] or 0:>6} {p['tokens_thinking'] or 0:>6} {p['cost'] or 0:>8.4f}")
    cells = report["cells"]
    matched = sum(c["match"] for c in cells)
    pm_tables = sum(pymupdf_seconds[f] for f in table_files)
    summary = {
        "table_pages": len(jobs), "failed_pages": len(jobs) - len(ok),
        "seconds_per_page_mean": round(statistics.mean(secs), 2) if secs else None,
        "seconds_per_page_max": round(max(secs), 2) if secs else None,
        "seconds_model_total": round(sum(secs), 1), "seconds_wall": round(wall, 1), "workers": workers,
        "pymupdf_seconds_same_files": round(pm_tables, 2), "pymupdf_seconds_all_files": round(sum(pymupdf_seconds.values()), 2),
        "cost_usd": round(cost, 4), "cost_per_page_usd": round(cost / len(ok), 5) if ok else None,
        "cells_matched": f"{matched}/{len(cells)}",
        "note": "seconds/cost of cached pages are from the run that asked the model",
    }
    report["summary"] = summary
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))

    print(f"\nPyMuPDF, same {len(table_files)} file(s): {pm_tables:.1f}s   (all {len(files)} files: "
          f"{summary['pymupdf_seconds_all_files']}s)")
    print(f"Model: {len(ok)} page(s), {summary['seconds_per_page_mean']}s per page on average "
          f"(slowest {summary['seconds_per_page_max']}s); {wall:.0f}s wall with {workers} at a time "
          f"({sum(secs):.0f}s one by one)")
    print(f"Cost: ${cost:.4f} in all, ${summary['cost_per_page_usd']} per page")
    print(f"Cells found word for word in the PDF: {matched}/{len(cells)}")
    for c in [c for c in cells if not c["match"]][:10]:
        print(f"   {c['file'][-30:]} p.{c['page']} {c['where']}: model {c['model'][:40]!r} | pdf {c['pdf'][:40]!r}")
    print(f"\nDetails (model text next to PDF text): {(out / 'report.json').relative_to(ROOT)}")
    print("Score it:")
    for g in gold_files:
        print(f"  uv run evals/check_ingestion.py {out.relative_to(ROOT)} --gold {g}")


if __name__ == "__main__":
    main()
