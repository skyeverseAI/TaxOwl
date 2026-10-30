"""Any PDF -> one ExtractedDoc: page text, tables, a quality report (plans/ingestion_pipeline.md).

Works on a corpus file or a user's upload alike: nothing is precomputed. Per document:

  1. Open it; sha256 of the bytes (names the caches; an upload has no stable path).
  2. Per page, what kind it is (the rules of ingestion/check_scans.py, per page, not per file, so
     a typed letter with a scanned annexure works):
       text   PyMuPDF's words
       scan   too few letters: OCR (ocr.py). docs/ocr/ is used when the corpus already has it.
       hindi  mostly Devanagari: kept as text, flagged (v1 is English only)
  3. Tables on text pages: PyMuPDF (tables.py).
  4. Gate (gate.py): pages whose tables look complex. A table cut by a page break goes to one
     reader whole, so a flagged page pulls in the pages its table runs onto.
  5. Those pages go to the vision model for the grid; the cells keep the PDF's words (vlm.py).
     No key, model=None, or a failed call: PyMuPDF's tables stay, and the document is flagged.
  6. Page text: words outside the tables, headers and footers stripped (extract.py).
  7. Self-check (extract.self_check), plus the model's own checks.

Usage:
    uv run python -m taxowl.ingestion_pipeline docs/circulars/2019/98-17-2019-GST.pdf
    uv run python -m taxowl.ingestion_pipeline some_upload.pdf --no-model
    uv run python -m taxowl.ingestion_pipeline --gold evals/ingestion_heldout_2034.json
    uv run python -m taxowl.ingestion_pipeline --corpus
Output: data/ingested/<file>.json (one ExtractedDoc each), scored by evals/check_ingestion.py.
"""

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pymupdf

from taxowl import gate, vlm
from taxowl.extract import DOCS, MANIFEST, OCR_DIR, normalize, page_lines, self_check, strip_headers
from taxowl.ocr import page_to_lines
from taxowl.schema import ExtractedDoc, Table
from taxowl.tables import CONTINUE_BOTTOM, CONTINUE_TOP, join_tables, read_page_tables, to_tables

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "ingested"
VLM_CACHE = ROOT / "data" / "cache" / "vlm"
MODEL = "google/gemini-3.5-flash-lite"  # 95.9% on the held-out runs, ~$0.0012 a page
WORKERS = 8           # model pages sent at the same time
EMPTY_PAGE_CHARS = 100  # fewer letters than this: a scanned page (as in ingestion/check_scans.py)
HINDI_SHARE = 0.5       # more than half the letters Devanagari: a Hindi page


# ---------- per page ----------

def page_kind(page):
    text = page.get_text("text")
    if len(re.sub(r"\s", "", text)) < EMPTY_PAGE_CHARS:
        return "scan"
    latin, hindi = len(re.findall(r"[A-Za-z]", text)), len(re.findall(r"[ऀ-ॿ]", text))
    return "hindi" if hindi > HINDI_SHARE * (latin + hindi) else "text"


def corpus_ocr(meta, n_pages):
    """The corpus' own OCR of this file (docs/ocr/, made by ingestion/ocr_scans.py), as page texts,
    or None. Same code as ocr.py, so it only saves time."""
    path = (OCR_DIR / meta["file"]).with_suffix(".txt")
    if not path.exists():
        return None
    pages = [normalize(p.strip()) for p in path.read_text().split("\f")]
    return pages if len(pages) == n_pages else None


def model_pages(flagged, raws_by_page, n_pages):
    """Flagged pages plus the pages their tables run onto, by the rule tables.join_tables uses
    (a table ending low on one page, the next page's first table starting high). Column counts
    are not checked, so this may take a page too many, never one too few."""
    pages, todo = set(flagged), list(flagged)
    while todo:
        p = todo.pop()
        here = raws_by_page.get(p, [])
        nxt, prev = raws_by_page.get(p + 1, []), raws_by_page.get(p - 1, [])
        if p < n_pages and here and nxt and max(r["bottom"] for r in here) > CONTINUE_BOTTOM \
                and min(r["top"] for r in nxt) < CONTINUE_TOP and p + 1 not in pages:
            pages.add(p + 1)
            todo.append(p + 1)
        if p > 1 and here and prev and min(r["top"] for r in here) < CONTINUE_TOP \
                and max(r["bottom"] for r in prev) > CONTINUE_BOTTOM and p - 1 not in pages:
            pages.add(p - 1)
            todo.append(p - 1)
    return pages


# ---------- one document ----------

def ingest(path, meta=None, model=MODEL, workers=WORKERS, stats=None):
    """One PDF -> ExtractedDoc. `meta`: the manifest row if known (else looked up, else made from
    the file). `model=None`: no page leaves this machine; complex tables stay PyMuPDF's, flagged.
    `stats`, if a dict, is filled with what happened (pages by kind, gate, model time and cost)."""
    path = Path(path)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    meta = meta or lookup(path) or {"file": path.name, "sha256": sha}
    doc_id = meta.get("number") or Path(meta["file"]).stem
    stats = {} if stats is None else stats
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # not a PDF, or damaged
        return ExtractedDoc(meta["file"], sha, [], quality={"error": f"can't open: {e!r}"[:300]})
    if pdf.needs_pass:
        return ExtractedDoc(meta["file"], sha, [], quality={"error": "password-protected"})

    with pdf:
        n = len(pdf)
        kinds = [page_kind(p) for p in pdf]
        stats["pages"] = {k: kinds.count(k) for k in set(kinds)}
        words, raws_by_page, ocr_text = {}, {}, {}
        saved_ocr = corpus_ocr(meta, n) if "scan" in kinds else None
        state = {"last_top": 0}  # carried across OCR pages (ocr.add_margin_numbers)
        for i, page in enumerate(pdf, 1):
            if kinds[i - 1] == "scan":
                ocr_text[i] = saved_ocr[i - 1] if saved_ocr else normalize(page_to_lines(page, state)[0])
                continue
            words[i] = [(*w[:4], normalize(w[4]), *w[5:]) for w in page.get_text("words")]
            if kinds[i - 1] == "text":
                raws_by_page[i] = read_page_tables(page, words[i])

        # Gate: on PyMuPDF's joined tables, as they would come out.
        all_raws = [r for p in sorted(raws_by_page) for r in raws_by_page[p]]
        joined_all, _ = join_tables([dict(r) for r in all_raws])
        pymupdf_tables = to_tables(joined_all, doc_id)
        signals = {}
        for p, raws in raws_by_page.items():
            fired = gate.page_signals(pdf[p - 1], raws, [t for t in pymupdf_tables if p in t.row_pages])
            if fired:
                signals[p] = sorted(fired)
        to_model = model_pages(signals, raws_by_page, n)
        stats["gate"] = {p: signals.get(p, ["(table continues)"]) for p in sorted(to_model)}

        quality, answers = {}, {}
        key = vlm.load_key() if model and to_model else None
        if to_model and not (model and key):
            quality["tables_unchecked"] = (f"page(s) {', '.join(map(str, sorted(to_model)))} have complex "
                                           f"tables but no model was used ({'no key' if model else 'model off'})")
        elif to_model:
            cache = VLM_CACHE / model.replace("/", "_")
            jobs = [(p, pdf[p - 1].get_pixmap(dpi=vlm.DPI).tobytes("png")) for p in sorted(to_model)]
            with ThreadPoolExecutor(workers) as pool:
                results = list(pool.map(lambda j: vlm.ask_cached(cache / f"{sha}__p{j[0]}.json", model, j[1], key), jobs))
            failed = [f"p.{p}: {r['error']}" for (p, _), r in zip(jobs, results) if "error" in r]
            stats["model"] = {"pages": len(jobs), "cached": sum(bool(r.get("cached")) for r in results),
                              "seconds": round(sum(r.get("seconds") or 0 for r in results if not r.get("cached")), 1),
                              "cost": round(sum((r.get("usage") or {}).get("cost") or 0
                                                for r in results if not r.get("cached")), 4)}
            if failed:  # all or nothing: half a document's tables from each reader can't be joined
                quality["vlm_failed"] = "; ".join(failed)[:300]
            else:
                answers = {p: r["answer"] for (p, _), r in zip(jobs, results)}

    return build(meta, sha, n, kinds, words, raws_by_page, ocr_text, answers, quality, doc_id)


def build(meta, sha, n, kinds, words, raws_by_page, ocr_text, answers, quality, doc_id):
    """Assemble the ExtractedDoc: PyMuPDF's tables on the pages the model didn't read, the model's
    snapped tables on the pages it did, page text outside both, then the self-checks."""
    keep_raws = [r for p in sorted(raws_by_page) if p not in answers for r in raws_by_page[p]]
    joined, dropped = join_tables(keep_raws)
    tables = to_tables(joined, doc_id)

    log, page_results, left, boxes = [], [], 0, {}
    for p in sorted(answers):
        snapped, page_left = vlm.snap_page(answers[p], words[p], [r["box"] for r in raws_by_page.get(p, [])], p, log)
        left += page_left
        page_results.append((p, snapped))
        boxes[p] = [t["box"] for t in snapped if t["box"]]
    for t in vlm.join(page_results):
        headings = [h or f"Column {j + 1}" for j, h in enumerate(t["headings"])]
        tables.append(Table(f"{doc_id}:table-{len(tables) + 1}", headings, [r for r, _ in t["rows"]],
                            [p for _, p in t["rows"]], reader="vlm"))
    tables.sort(key=lambda t: min(t.row_pages, default=0))

    lines, source = [], []
    for p in range(1, n + 1):
        if p in ocr_text:
            lines.append(list(enumerate(ocr_text[p].splitlines())))
            source += ocr_text[p].split()
            continue
        source += [w[4] for w in words[p]]
        page_boxes = boxes[p] if p in answers else [r["box"] for r in raws_by_page.get(p, [])]
        lines.append(page_lines(words[p], page_boxes))
    texts, removed = strip_headers(lines)

    doc = ExtractedDoc(meta["file"], sha, ["\n".join(t) for t in texts], tables, ocr=bool(ocr_text))
    doc.quality = {**self_check(doc, source, removed + dropped, keep_raws), **quality}
    misses = [e for e in log if not e["match"]]
    if misses:
        doc.quality["cells_not_in_pdf"] = f"{len(misses)} of {len(log)} cells, e.g. " + "; ".join(
            f"p.{e['page']} {e['where']}: {e['model'][:30]!r}" for e in misses[:3])
    if left:
        doc.quality["words_left_in_table"] = f"{left} PDF word(s) inside a table that no cell took"
    hindi = [p for p, k in enumerate(kinds, 1) if k == "hindi"]
    if hindi:
        doc.quality["hindi_pages"] = "page(s) " + ", ".join(map(str, hindi)) + " (v1 reads English only)"
    return doc


def lookup(path):
    """The manifest row of a corpus file, by its path under docs/, else None (an upload)."""
    try:
        rel = str(path.resolve().relative_to(DOCS.resolve()))
    except ValueError:
        return None
    return next((m for m in map(json.loads, MANIFEST.open()) if m["file"] == rel), None)


# ---------- the command line ----------

def main():
    args = sys.argv[1:]
    model = None if "--no-model" in args else MODEL
    if "--model" in args:
        model = args[args.index("--model") + 1]
        args.remove(model)
    flags = {"--no-model", "--model", "--corpus", "--gold"}
    rest = [a for a in args if a not in flags]
    if "--corpus" in args:
        paths = [DOCS / m["file"] for m in map(json.loads, MANIFEST.open())]
    elif "--gold" in args:
        files = sorted({c["file"] for g in rest for c in json.loads(Path(g).read_text())["pages"]})
        paths = [DOCS / f for f in files]
    else:
        paths = [Path(a) for a in rest]
    if not paths:
        sys.exit(__doc__)

    start, total_cost, flagged = time.time(), 0.0, 0
    for i, path in enumerate(paths, 1):
        stats, t0 = {}, time.time()
        try:
            doc = ingest(path, model=model, stats=stats)
        except Exception as e:  # one bad PDF shouldn't stop the run
            doc = ExtractedDoc(path.name, "", [], quality={"error": repr(e)[:300]})
        out = OUT / (doc.file + ".json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(asdict(doc), ensure_ascii=False))
        m = stats.get("model", {})
        total_cost += m.get("cost", 0)
        flagged += bool(doc.quality)
        readers = [t.reader for t in doc.tables]
        print(f"[{i}/{len(paths)}] {doc.file}  {time.time() - t0:.1f}s  pages {stats.get('pages', {})}  "
              f"tables: {readers.count('pymupdf')} pymupdf, {readers.count('vlm')} model"
              + (f"  model pages {sorted(stats['gate'])} ({m.get('cached', 0)} cached, ${m.get('cost', 0)})"
                 if stats.get("gate") else ""))
        for check, reason in doc.quality.items():
            print(f"      {check}: {reason}")
    print(f"\n{len(paths)} document(s) in {time.time() - start:.0f}s, model cost ${total_cost:.4f}, "
          f"{flagged} flagged. Output: {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
