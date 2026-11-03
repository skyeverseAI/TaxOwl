"""ICAI's compilation PDF ("GST Act(s) and Rule(s)-Bare Law.pdf") -> Units for its five parts
(CGST Rules, IGST Act, IGST Rules, UTGST Act, Compensation Act; pages in known_docs.json).

Built one step at a time (to-do-list.md, A4). Step 1, this file so far: separate each page's
footnotes from its law text.

Why font size, and not text alone (measured 2026-11-03 on all 11,007 lines of the five parts):
  ICAI prints law text in 9pt and footnotes in 8pt. A text-only rule ("from the first
  '10 Inserted vide ...' line to the page end") gets 96.9% of lines right. All of its mistakes
  are one kind: a long footnote, quoting a whole old rule, spills onto the next page and is printed
  ABOVE that page's first numbered footnote, with no number of its own (23 pages, 335 lines,
  e.g. p.198, p.331). Read as law, that old text would look like current law.

The rule here (footnote_start): the text rule finds the first numbered footnote; font size is
looked at only just above it, to catch the carried-over part. Small text elsewhere on the page
is never used, since tables or notes can be small too. The body size is measured per document
(the most common size), not fixed at 9. Scans (OCR) have no font size: not handled here.

The extractor's page text is still what we split (headers, tables and joined lines as everywhere
else). The PDF is opened only to read sizes and to find where each page's footnote area starts.

Run:  uv run python -m taxowl.splitting.icai
"""

import json
import re
import sys
from collections import Counter

import pymupdf

from taxowl.splitting import known_parts
from taxowl.splitting.act import INGESTED, ROOT

DOC_FILE = "GST Act(s) and Rule(s)-Bare Law.pdf"
SMALLER = 0.5   # a line counts as small if it is at least 0.5pt below the body size
KEY_CHARS = 30  # letters and digits compared when matching a PDF line to an extracted line
TABLE_REF = re.compile(r"\[table [^\]]+\]")
# A footnote's first line: its mark (a number, @, #, *, $), then what the amendment did.
FOOTNOTE = re.compile(r"^(\d{1,3}|@+|#+|\*+|\$+)\s*(Inserted|Substituted|Omitted|Added|Amended|"
                      r"Renumbered|Re-numbered|Corrected|Deleted|Brought|The words|Words|Prior)", re.I)


# ---------- 1. Font sizes from the PDF ----------

def pdf_lines(page: pymupdf.Page) -> list[tuple[str, float]]:
    """One PDF page -> [(line text, font size)] in the PDF's stored order. The size of a line is
    its biggest span, so a small superscript mark doesn't make a law line look small."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                out.append((text, round(max(s["size"] for s in line["spans"]), 1)))
    return out


def body_size(pdf: pymupdf.Document, first: int, last: int) -> float:
    """The most common font size over these pages, counted by characters: the law text's size."""
    sizes = Counter()
    for i in range(first - 1, last):
        for text, size in pdf_lines(pdf[i]):
            sizes[size] += len(text)
    return sizes.most_common(1)[0][0]


def footnote_start(lines: list[tuple[str, float]], body: float) -> list[str]:
    """The first two lines of the page's footnote area, or [] if the page has none. Two lines,
    because one can repeat lower down: on p.50 two footnotes both start "No. 02/2019 – CT dated
    29.01.2019, w.e.f. 01.02.2019, prior to its substitution ...". Two steps:
      1. Text: the first line like "10 Inserted vide ..." / "@ Substituted ...". From there to the
         page end is footnotes, whatever their size (ICAI printed its 2025-26 footnotes in 10pt).
      2. Font, only just above that line: small lines there are a footnote carried over from the
         previous page, so the area starts higher. With no numbered footnote, step 2 starts from
         the page end (a page whose bottom holds only a carried-over footnote).
    Small text anywhere else on the page (a table, a note) is never looked at."""
    k = next((i for i, (text, _) in enumerate(lines) if FOOTNOTE.match(text)), len(lines))
    while k > 0 and lines[k - 1][1] <= body - SMALLER:
        k -= 1
    return [text for text, _ in lines[k:k + 2]]


# ---------- 2. Cut the extracted page at that line ----------

def key(text: str) -> str:
    """Letters and digits only, lower case: a PDF line and the extractor's copy of it differ in
    spaces and quote marks, never in these."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def split_page(page_text: str, first_note_lines: list[str]) -> tuple[list[str], list[str]] | None:
    """Extracted page text -> (law lines, footnote lines), cut at the line where the footnote
    area's text begins. Compared as one stream of letters, not line by line: the extractor joins
    pieces of one printed line, so the PDF's "(i)" + "any additional amount ..." is one extracted
    line (p.223). Searched from the bottom, since the footnotes are there. None if not found."""
    lines = page_text.split("\n")
    if not first_note_lines:
        return lines, []
    target = key(" ".join(first_note_lines))[:2 * KEY_CHARS]
    for k in range(len(lines) - 1, -1, -1):
        if key(" ".join(lines[k:k + 3])).startswith(target):
            return lines[:k], lines[k:]
    return None


def split_footnotes_part(doc: dict, pdf: pymupdf.Document, part: dict) -> dict:
    """All pages of one part -> {"pages": [(page no, law lines, footnote lines)], "warnings": [...]}."""
    first, last = part["pages"]
    body = body_size(pdf, first, last)
    pages, warnings = [], []
    for no in range(first, last + 1):
        start_lines = footnote_start(pdf_lines(pdf[no - 1]), body)
        cut = split_page(doc["pages"][no - 1], start_lines)
        if cut is None:
            warnings.append(f"p.{no}: footnote start not found in the extracted text: {start_lines[0][:50]!r}")
            cut = (doc["pages"][no - 1].split("\n"), [])
        law, notes = cut
        if any(TABLE_REF.search(l) for l in notes):
            warnings.append(f"p.{no}: a table sits inside the footnote area")
        pages.append((no, law, notes))
    return {"body_size": body, "pages": pages, "warnings": warnings}


# ---------- 3. Run it and show what happened ----------

def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    doc = json.loads((INGESTED / f"{DOC_FILE}.json").read_text())
    pdf = pymupdf.open(ROOT / "docs" / DOC_FILE)
    all_ok = True
    for part in known_parts(DOC_FILE):
        r = split_footnotes_part(doc, pdf, part)
        law_lines = [l for _, law, _ in r["pages"] for l in law]
        note_lines = [l for _, _, notes in r["pages"] for l in notes]
        # "Prior to substitution/omission, it read ..." is old law: it must sit in a footnote.
        prior_in_law = [l for l in law_lines if re.search(r"\bprior to (its )?(substitution|omission|amendment)", l, re.I)]
        print(f"\n== {part['name']} (p.{part['pages'][0]}-{part['pages'][1]}), body font {r['body_size']}pt")
        print(f"   law lines {len(law_lines)}, footnote lines {len(note_lines)}, "
              f"pages with footnotes {sum(1 for _, _, n in r['pages'] if n)}")
        for w in r["warnings"]:
            print(f"   {red}warning{reset} {w}")
        if prior_in_law:
            all_ok = False
            print(f"   {red}FAIL{reset} 'Prior to ...' in law text, {len(prior_in_law)} line(s): {prior_in_law[0][:80]!r}")
    # The page that went wrong before: p.198, where an old footnote spills over from p.197.
    rules = known_parts(DOC_FILE)[0]
    r = split_footnotes_part(doc, pdf, rules)
    no, law, notes = next(p for p in r["pages"] if p[0] == 198)
    print(f"\n-- p.{no}, last 2 law lines:")
    for l in law[-2:]:
        print(f"   {l[:100]}")
    print(f"-- p.{no}, footnote area:")
    for l in notes:
        print(f"   {l[:100]}")
    print(f"\n{green}all passed{reset}" if all_ok else f"\n{red}some checks failed{reset}")


if __name__ == "__main__":
    main()
