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
from taxowl.splitting.act import INGESTED, ROOT, clean

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
    # Both lines in full: on p.50 (held-out) the first line alone, 70 letters long, repeats lower down.
    target = key(" ".join(first_note_lines))
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


# ---------- 3. Footnote lines -> footnotes; marks in the law -> their footnote ----------
#
# What the footnote area holds (p.220 shows all of it):
#   "8 Substituted vide Notification No. 27/2021 ... Prior to its substitution, it was read as:"
#   '"*[Provided further that ...]".'            <- the old text, over several lines
#   "* Inserted vide Notification No. 13/2021"   <- a footnote OF the old text ("*[" is in it)
# Numbered footnotes belong to marks in the law ("8[Provided further ..."). Symbol footnotes
# (*, @, #, $) belong to marks inside another footnote's old text: in the five parts such marks
# appear 0 times in law text and 92 times in footnotes (counted 2026-11-03).

# A mark in the law: "10[", or glued to a word ("Authority21[or", CGST Act copy p.124).
# Never after a digit, a capital or a dot, so "GSTR-2[" style text or "(w.e.f." is not touched.
OPEN_MARK = r"(?:(?<![\w.])|(?<=[a-z]))\d{1,3}\["
LAW_MARK = re.compile(r"(?:(?<![\w.])|(?<=[a-z]))(\d{1,3})(?=\[)")
SYMBOL = re.compile(r"^[@#$*]+$")
# "Prior to its substitution, it was read as: ...". Not bare "prior to": law says "prior to the
# appointed day" too.
PRIOR = re.compile(r"\bprior to (?:its |the )?(?:substitution|omission|amendment)", re.I)
ROUND_MARK = re.compile(r"(?<![\w.(])\d{1,3}\((?=[a-z]\)\s*\[)")  # "30(b) [..." (p.292): a typo


def read_notes(pages: list[tuple[int, list[str], list[str]]]) -> tuple[list[dict], list[str]]:
    """Footnote lines of all pages, in order -> footnotes. A line starting like "10 Inserted ..."
    or "* Inserted ..." starts one; any other line continues the one before, also when it is the
    first line of a page (a footnote carried over, p.198). Each footnote is split in two:
      said: what changed ("Substituted vide Notification No. 19/2022 ... w.e.f. 01.10.2022.")
      old:  from "Prior to ..." on, the old wording -> the unit's history, never its text."""
    notes, warnings = [], []
    for no, _, area in pages:
        for line in (l.strip() for l in area):
            if not line:
                continue
            if m := FOOTNOTE.match(line):
                notes.append({"mark": m.group(1), "page": no,
                              "text": line[len(m.group(1)):].strip(), "notes_on_old": []})
            elif notes:
                notes[-1]["text"] += " " + line
            else:
                warnings.append(f"p.{no}: footnote text with no footnote before it: {line[:50]!r}")
    for n in notes:
        m = PRIOR.search(n["text"])
        n["said"], n["old"] = (n["text"][:m.start()].strip(), n["text"][m.start():].strip()) if m else (n["text"], "")
    return notes, warnings


SYMBOL_REACH = 3  # pages either side to look for a symbol footnote's mark (p.333's is on p.330)


def symbol_mark(mark: str) -> re.Pattern:
    """'@' -> the symbol on its own, not part of a longer run ('@@'). Only the symbol, not what
    follows it: ICAI writes the same mark as '@[', '@ [', '[@', '@"' and '@(iv)' (p.290, 291, 407).
    Stars also stand for deleted words, '33[***]' or '1***' (as in act.py): stars right after a
    digit or '[', or right before ']', are not a mark."""
    c = re.escape(mark[0])
    return re.compile(rf"(?<![\d\[{c}]){re.escape(mark)}(?![\]{c}])")


def attach_symbol_notes(notes: list[dict], law: dict[int, str]) -> tuple[list[dict], list[str]]:
    """Each symbol footnote goes to the footnote whose text holds its mark: the nearest one before
    it, else the nearest after it, within SYMBOL_REACH pages. That one can be another symbol footnote ("@@@" inside
    "@@"'s old text, p.210). If the law itself (its text or a table, both in `law`) has the mark
    on the page or a page next to it, it stays a normal footnote.
    Guard against a loose match: two footnotes with the same symbol landing on the same parent
    means one of them matched the wrong mark, so it is warned about.
    Returns (the footnotes that belong to the law, warnings)."""
    parent_of = {}
    for i, n in enumerate(notes):
        if not SYMBOL.match(n["mark"]):
            continue
        pat, page = symbol_mark(n["mark"]), n["page"]
        if any(pat.search(law.get(p, "")) for p in (page - 1, page, page + 1)):
            continue
        # A footnote is printed after the one it belongs to (p.220: 8, then its "*"), so look
        # back first, nearest first; only if none, look ahead.
        holds = [j for j, p in enumerate(notes)
                 if j != i and abs(p["page"] - page) <= SYMBOL_REACH and pat.search(p["text"])]
        before, after = [j for j in holds if j < i], [j for j in holds if j > i]
        parent_of[i] = before[-1] if before else (after[0] if after else None)
    kept, warnings, taken = [], [], {}
    for i, n in enumerate(notes):
        if i not in parent_of:
            kept.append(n)
        elif parent_of[i] is None:
            warnings.append(f"p.{n['page']}: footnote '{n['mark']}' has no mark in the law or in another footnote")
            kept.append(n)
        else:
            parent = notes[parent_of[i]]
            mark_count = len(symbol_mark(n["mark"]).findall(parent["text"]))
            taken[(parent_of[i], n["mark"])] = taken.get((parent_of[i], n["mark"]), 0) + 1
            if taken[(parent_of[i], n["mark"])] > mark_count:
                warnings.append(f"p.{n['page']}: footnote '{n['mark']}' joins p.{parent['page']} footnote "
                                f"'{parent['mark']}', which has fewer '{n['mark']}' marks than footnotes")
            parent["notes_on_old"].append(n)  # the footnote itself, so its own notes come along
    return kept, warnings


def note_for(mark: str, page: int, index: dict) -> dict | None:
    """The footnote for a law mark: on its page, else the next page (ICAI sometimes prints it
    there, p.213 -> 214), else the page before."""
    return next((index[(p, mark)] for p in (page, page + 1, page - 1) if (p, mark) in index), None)


def words(text: str) -> Counter:
    return Counter(re.findall(r"[A-Za-z]{2,}", text))


def footnotes_part(doc: dict, pdf: pymupdf.Document, part: dict) -> dict:
    """One part -> its footnotes, every law mark matched to one, and the self-check."""
    r = split_footnotes_part(doc, pdf, part)
    pages, warnings = r["pages"], list(r["warnings"])
    law = {no: "\n".join(lines) for no, lines, _ in pages}
    # Table text per page: a mark can sit in a table (p.190's "@", "#"), which the extractor
    # keeps apart from the page text. Used only to find where a symbol footnote belongs.
    tables = {}
    for t in doc["tables"]:
        for no in set(t["row_pages"]):
            tables[no] = tables.get(no, "") + "\n" + json.dumps([t["headings"], t["rows"]], ensure_ascii=False)
    notes, w = read_notes(pages)
    warnings += w
    kept, w = attach_symbol_notes(notes, {no: law[no] + tables.get(no, "") for no in law})
    warnings += w
    index = {(n["page"], n["mark"]): n for n in kept}

    marks, missing, used = 0, [], set()
    for no, text in law.items():
        for mark in LAW_MARK.findall(text):
            marks += 1
            n = note_for(mark, no, index)
            if n:
                used.add(id(n))
            else:
                missing.append(f"p.{no}:{mark}")
        for m in ROUND_MARK.finditer(text):
            warnings.append(f"p.{no}: '{m.group()}' looks like a mark with '(' for '[': left as it is")
    unused = [f"p.{n['page']}:{n['mark']}" for n in kept if id(n) not in used]

    raw = "\n".join(law.values())
    cleaned = clean(raw, OPEN_MARK)
    all_notes = " ".join(n["text"] for n in notes)
    checks = {
        "marks_left_in_law": len(LAW_MARK.findall(cleaned)) + cleaned.count("*"),
        "prior_to_in_law": len(PRIOR.findall(cleaned)),
        "law_words_lost": sum((words(raw) - words(cleaned)).values()),
        "footnote_words_lost": sum((words("\n".join(l for _, _, a in pages for l in a)) - words(all_notes)).values()),
        "prior_to_without_old_text": sum(1 for n in notes if PRIOR.search(n["text"]) and not n["old"]),
    }
    return {"notes": kept, "all_notes": notes, "marks": marks, "missing": missing, "unused": unused,
            "warnings": warnings, "checks": checks, "law": law, "cleaned": cleaned}


# ---------- 4. Run it and show what happened ----------

# ICAI's copy of the CGST Act: same style, never looked at while writing this file. We split the
# India Code copy instead (act.py), so these pages serve only as a held-out test of the rules.
HELD_OUT = {"name": "CGST Act, ICAI copy (held-out)", "pages": [20, 181]}


def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    doc = json.loads((INGESTED / f"{DOC_FILE}.json").read_text())
    pdf = pymupdf.open(ROOT / "docs" / DOC_FILE)
    all_ok = True
    results = {}
    for part in known_parts(DOC_FILE) + [HELD_OUT]:
        r = results[part["name"]] = footnotes_part(doc, pdf, part)
        notes = r["all_notes"]
        print(f"\n== {part['name']} (p.{part['pages'][0]}-{part['pages'][1]})")
        print(f"   footnotes {len(notes)} ({sum(1 for n in notes if n['old'])} with old text; "
              f"{len(notes) - len(r['notes'])} are notes on an old text)")
        print(f"   law marks {r['marks']}: {r['marks'] - len(r['missing'])} found their footnote, "
              f"{len(r['missing'])} did not {r['missing'][:6]}")
        print(f"   footnotes with no mark in the law text {len(r['unused'])} {r['unused'][:6]}  "
              f"(expected: marks inside tables)")
        for w in r["warnings"][:5]:
            print(f"   {red}warning{reset} {w}")
        if len(r["warnings"]) > 5:
            print(f"   ... {len(r['warnings']) - 5} more warnings")
        bad = {k: v for k, v in r["checks"].items() if v}
        all_ok &= not bad
        print(f"   checks: {green}all 0{reset}" if not bad else f"   checks: {red}{bad}{reset}")

    # Look at p.220: footnote 8 with its '*' note, and footnote 9 split in two.
    r = results[known_parts(DOC_FILE)[0]["name"]]
    for n in r["notes"]:
        if n["page"] == 220 and n["mark"] in ("8", "9"):
            print(f"\n-- p.220, footnote {n['mark']}")
            print(f"   said: {n['said'][:110]}")
            print(f"   old:  {n['old'][:110]}")
            for x in n["notes_on_old"]:
                print(f"   note on the old text: {x['mark']} {x['text'][:100]}")
    # And p.207: a mark inside a mark, cleaned.
    line = next(l for l in r["law"][207].split("\n") if "69[" in l)
    print(f"\n-- p.207 before: {line[:100]}")
    print(f"   after:  {clean(line, OPEN_MARK)[:100]}")
    print(f"\n{green}all passed{reset}" if all_ok else f"\n{red}some checks failed{reset}")


if __name__ == "__main__":
    main()
