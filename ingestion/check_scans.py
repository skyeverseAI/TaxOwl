"""Check every downloaded PDF: does it have real text inside, or is it a scan (pictures of pages)?

How it decides, for each file:
  1. Pull the text out of every page and count the letters.
     A normal page has 1,500-3,000 letters. A scanned page gives almost none.
  2. Look at what share of the words are very common English words ("the", "of", "and", ...).
     Normal English text is roughly 25-35% such words. Garbage text (a bad hidden text layer
     in a scan, like "Ci rc#ul@r") has almost none.
  3. Count Hindi (Devanagari) letters, because some CBIC PDFs are bilingual or Hindi-only.
     Hindi text would otherwise look like "garbage" to step 2.

Each file gets one status:
  ok          text is fine
  scan        most pages have no text            -> needs OCR
  part_scan   some pages have no text            -> look at it (could be blank or signature pages)
  bad_text    text exists but is mostly garbage  -> needs OCR
  hindi       mostly Hindi text                  -> decide later (v1 is English only)

Usage:
    uv run ingestion/check_scans.py
Writes ingestion/scan_report.csv (one row per file) and prints a summary.
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MANIFEST = DOCS / "manifest.jsonl"
REPORT = Path(__file__).resolve().parent / "scan_report.csv"

EMPTY_PAGE_CHARS = 100        # a page with fewer letters than this counts as "no text"
SCAN_SHARE = 0.5              # more than half the pages empty -> scan
MIN_COMMON_WORD_SHARE = 0.10  # below this, the text is probably garbage
HINDI_SHARE = 0.5             # more than half the letters Hindi -> hindi

COMMON_WORDS = {
    "the", "of", "and", "to", "in", "is", "be", "for", "or", "by", "on", "as", "with", "that",
    "under", "any", "such", "shall", "are", "this", "an", "at", "from", "which", "it", "has", "have",
    "a", "not", "may", "been", "said", "where", "tax", "section", "rule",
}


def check_file(path):
    """Return the numbers we need for one PDF."""
    with pymupdf.open(path) as pdf:
        page_texts = [page.get_text("text") for page in pdf]

    pages = len(page_texts)
    empty_pages = sum(1 for t in page_texts if len(re.sub(r"\s", "", t)) < EMPTY_PAGE_CHARS)
    text = "\n".join(page_texts)

    latin = len(re.findall(r"[A-Za-z]", text))
    hindi = len(re.findall(r"[ऀ-ॿ]", text))
    words = re.findall(r"[A-Za-z]+", text.lower())
    common_share = sum(w in COMMON_WORDS for w in words) / len(words) if words else 0.0

    return {
        "pages": pages,
        "empty_pages": empty_pages,
        "letters": latin + hindi,
        "hindi_share": round(hindi / (latin + hindi), 2) if latin + hindi else 0.0,
        "common_word_share": round(common_share, 2),
    }


def status_of(r):
    if r["pages"] == 0 or r["empty_pages"] / r["pages"] > SCAN_SHARE:
        return "scan"
    if r["hindi_share"] > HINDI_SHARE:
        return "hindi"
    if r["common_word_share"] < MIN_COMMON_WORD_SHARE:
        return "bad_text"
    if r["empty_pages"] > 0:
        return "part_scan"
    return "ok"


def main():
    docs = [json.loads(line) for line in MANIFEST.open()]
    rows = []
    for i, d in enumerate(docs, 1):
        print(f"\rchecking {i}/{len(docs)}", end="", flush=True)
        try:
            r = check_file(DOCS / d["file"])
            r["status"] = status_of(r)
        except Exception as e:  # a PDF that will not even open
            r = {"pages": 0, "empty_pages": 0, "letters": 0, "hindi_share": 0.0,
                 "common_word_share": 0.0, "status": f"error: {e}"}
        rows.append({"doc_type": d["doc_type"], "number": d["number"], "file": d["file"], **r})
    print()

    with REPORT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\nSummary:")
    for status, n in Counter(r["status"] for r in rows).most_common():
        print(f"  {status:<10} {n}")
    print("\nBy document type (files that are not 'ok'):")
    for (doc_type, status), n in sorted(Counter((r["doc_type"], r["status"]) for r in rows if r["status"] != "ok").items()):
        print(f"  {doc_type:<14} {status:<10} {n}")

    flagged = [r for r in rows if r["status"] != "ok"]
    if flagged:
        print("\nFiles to look at:")
        for r in flagged:
            print(f"  {r['status']:<10} {r['empty_pages']}/{r['pages']} pages empty  {r['file']}")
    print(f"\nFull report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
