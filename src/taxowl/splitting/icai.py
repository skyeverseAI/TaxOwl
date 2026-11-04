"""ICAI's compilation PDF ("GST Act(s) and Rule(s)-Bare Law.pdf") -> Units for the parts we take
from it: the CGST Rules and the IGST Rules (pages in known_docs.json; the Acts come from India
Code, act.py).

Built one step at a time (to-do-list.md, A4):
  1. footnotes off each page (sections 1-2 below);
  2. footnotes read, split into what changed and the old text, matched to their marks (3);
  3. law lines -> one unit per rule, rule 2 per definition, footnotes attached (4), self-check (5).
Held-out: ICAI's copy of the CGST Act, split by the same code; its sections must match act.py's.

Step 1, footnotes:

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
Out:  data/units/GST Act(s) and Rule(s)-Bare Law.pdf.jsonl (the Rules' units), plus a summary and
      a self-check per part, the held-out included.
"""

import json
import re
import sys
from collections import Counter
from dataclasses import asdict

import pymupdf

from taxowl.config import DOCS, INGESTED, ROOT, UNITS
from taxowl.schema import Unit
from taxowl.splitting import finish, known_parts
from taxowl.splitting.act import clean, nice

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
    """Words for the "nothing lost / nothing doubled" checks. Lower case: a chapter's
    "INPUT TAX CREDIT" lives on in parent as "Input Tax Credit"."""
    return Counter(re.findall(r"[a-z]{2,}", text.lower()))


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
            "warnings": warnings, "checks": checks, "law": law, "cleaned": cleaned, "index": index}


# ---------- 4. Law lines -> units (one per rule or section; rule 2 per definition) ----------
#
# What a page's law text looks like (p.221):
#   "Ch-V : Input Tax Credit"   <- running header, top of every page: dropped
#   "Rules 36-45"               <- running header: dropped
#   "CHAPTER V - INPUT TAX CREDIT"                       <- chapter: into `parent`, not text
#   "Rule 37. Reversal of input tax credit in the ... consideration.-"   <- a unit starts
# ICAI typos in the starts: "Rule113." (p.318), "Rule131." (p.326), "Rule 88 C." (p.283).

# Running headers, matched only on a page's first 3 lines and only as a whole line.
HEADER = re.compile(r"^(?:Ch-[IVXL]+[A-Z]?\s*:.*|(?:Rules?|Sec(?:tions?|s)?\.?)\s*\d+[A-Z]*\s*(?:-\s*\d+[A-Z]*)?"
                    r"|(?:CGST|IGST|UTGST)\s+(?:Rules|Act),?\s*\d{4})$")
CHAPTER = re.compile(r"^CHAPTER\s+([IVXL]+[A-Z]?)\s*[:\-–—]\s*(.+)$")
# An Act's schedule heading, a whole line: "THE SCHEDULE" (Compensation Act, p.434), "SCHEDULE I"
# (ICAI's CGST Act, p.176), "SCHEDULES" (the heading above those). Each schedule is one unit;
# without this, it ran on inside the last section (the Compensation Act's cess rates in s.14).
SCHEDULE = re.compile(r"^(?:THE\s+)?SCHEDULE(S)?(?:\s+([IVXL]+))?$")
HEAD_END = r"\.?\]?\s*(?:—|––|–|-)(?:\s|$)"  # what ends a heading: ".-", ". -", ".—"
# Rule 2's definitions: (a) (b) ... (z) (za) (zb) ...
LETTERS = list("abcdefghijklmnopqrstuvwxyz")
DEF_ORDER = LETTERS + ["z" + c for c in LETTERS] + ["zz" + c for c in LETTERS]
LETTER_DEF = re.compile(r"^(?:\d{1,3}\[)?\(([a-z]{1,3})\)\s")
GAP = 5  # a start may skip at most this many numbers (omitted rules); more is prose, not a start


def unit_start(word: str) -> re.Pattern:
    """'Rule' -> 'Rule 37.', '27[Rule 88 C.', 'Rule113.'. A mark can sit in three places:
    before the word, with or without its '[' ('15Section 51.', held-out p.84); between the word
    and the number ('Section 13[168A.', p.172); right after the dot ('Rule 120A.12[Revision', p.322)."""
    return re.compile(rf"^(?:\d{{1,3}}\[?)?{word}\s*(?:\d{{1,3}}\[)?(\d{{1,3}})\s?([A-Z]{{0,2}})\."
                      rf"(?:\s|$|(?=\d{{1,3}}\[))")


def marked_words(text: str) -> dict[str, str]:
    """The words inside each mark: '11[or reverse]' -> {'11': 'or reverse'}; '1[****]' ->
    {'1': ''} (words deleted). Brackets paired with a stack, as in clean(), so a mark inside a
    mark works ('69[70[Provided also] that ...]'). The first time a mark appears wins."""
    found, stack = {}, []
    for m in re.finditer(rf"{OPEN_MARK}|\[|\]", text):
        token = m.group()
        if token == "[":
            stack.append(None)
        elif token == "]":
            if stack and (opened := stack.pop()) is not None:
                mark, start = opened
                words = " ".join(clean(text[start:m.start()], OPEN_MARK).split())
                found.setdefault(mark, words)
        else:
            stack.append((re.match(r"\D*(\d+)", token).group(1), m.end()))
    return found


def change_line(n: dict, words: str | None) -> str:
    """A footnote's 'what changed', with the words it touched:
    'Inserted vide Notification No. 26/2022 ... Words: "or reverse"'."""
    if words is None:
        return n["said"]
    return f'{n["said"]} Words: "{words}"' if words else f'{n["said"]} Words: (deleted)'


def history_text(n: dict) -> str:
    """A footnote's old text, with the notes on that old text inside it, as one string."""
    out = f"{n['said']} {n['old']}".strip()
    for child in n["notes_on_old"]:
        out += f" [note {child['mark']}: {history_text(child)}]"
    return out


def split_part(doc: dict, pdf: pymupdf.Document, part: dict) -> tuple[list[Unit], dict, list[str]]:
    """One part -> (units, self-check problems, warnings)."""
    f = footnotes_part(doc, pdf, part)
    warnings = list(f["warnings"])
    start = unit_start(part.get("starts_with", "Rule"))
    kind = "rule" if part.get("starts_with", "Rule") == "Rule" else "section"

    # Every law line with its page; running headers off the top of each page.
    lines, headers = [], 0
    for no, text in f["law"].items():
        for k, line in enumerate(l.strip() for l in text.split("\n")):
            if not line:
                continue
            if k < 3 and HEADER.match(line):
                headers += 1
                continue
            lines.append((no, line))

    units: list[Unit] = []
    block: list[tuple[int, str]] = []
    current = ("other", "preamble", "Title and enacting words", "")  # type, location, heading, parent
    chapter, last, gaps, rejected = "", (0, ""), [], []

    def close():
        if block:
            unit_type, location, heading, parent = current
            # Rule 2's definitions are lettered. An Act's s.2 is numbered "(1)" ... and has
            # lettered lists inside its definitions, so letters must not split it.
            if location == "rule 2" and "efinition" in heading:
                units.extend(split_letter_definitions(block, location, parent))
            else:
                units.append(make_unit(unit_type, location, heading, parent, block))

    pieces_of: list[list[tuple[int, str]]] = []  # each unit's own lines, with pages (for its marks)

    def make_unit(unit_type, location, heading, parent, piece, term=""):
        pieces_of.append(piece)
        text = clean("\n".join(l for _, l in piece), OPEN_MARK)
        text = re.sub(r"^\d{1,3}(?=[A-Z][a-z])", "", text)  # a mark that lost its "[": "15Section 51."
        return Unit(unit_type, DOC_FILE, location, clean(heading, OPEN_MARK), text,
                    piece[0][0], piece[-1][0], parent=parent, term=term)

    def split_letter_definitions(piece, location, parent):
        """Rule 2 -> its opening words, then one unit per (a), (b) ... A "(x)" line starts a
        definition only if x comes next in the order (one may be skipped, for an omitted one),
        so a "(i)" list inside a definition can't."""
        pieces, pos = [("", [])], -1
        for page, line in piece:
            m = LETTER_DEF.match(line)
            if m and m.group(1) in DEF_ORDER[pos + 1:pos + 3]:
                pos = DEF_ORDER.index(m.group(1), pos + 1)
                pieces.append((m.group(1), []))
            pieces[-1][1].append((page, line))
        out = []
        for label, ls in pieces:
            if not label:
                out.append(make_unit(kind, location, "Definitions", parent, ls))
                continue
            text = clean(ls[0][1], OPEN_MARK)
            term = re.search(r'["“]([^"”]+)["”]', text)
            term = term.group(1) if term else ""
            out.append(make_unit("definition", f"{location}({label})",
                                 f'Definition of "{term}"' if term else "Definitions",
                                 f"{location} Definitions", ls, term))
        return out

    for i, (page, line) in enumerate(lines):
        cl = clean(line, OPEN_MARK)
        if m := CHAPTER.match(cl):
            chapter = f"Chapter {m.group(1)} {nice(m.group(2).strip())}"
            continue
        if kind == "section" and (m := SCHEDULE.match(cl)):
            name = f"Schedule {m.group(2)}" if m.group(2) else "Schedule"
            # "SCHEDULES" then "SCHEDULE I": the first is only a heading; it joins Schedule I.
            if not (current[0] == "schedule" and current[1] == "Schedule" and len(block) == 1):
                close()
                block = []
            current = ("schedule", name, name, "")
            block.append((page, line))
            continue
        if m := start.match(line):
            key = (int(m.group(1)), m.group(2))
            if key > last and key[0] <= last[0] + GAP:
                close()
                if key[0] > last[0] + 1:
                    gaps.append(f"{kind} {key[0]}{key[1]} comes after {last[0]}{last[1]}")
                last = key
                number = f"{key[0]}{key[1]}"
                joined = clean(" ".join(l for _, l in lines[i:i + 3]), OPEN_MARK)
                rest = joined[start.match(joined).end():] if start.match(joined) else ""
                hm = re.match(rf"(.{{3,250}}?){HEAD_END}", rest) or re.match(r"(.{3,200}?)\.(?:\s|$)", rest)
                block = []
                current = (kind, f"{kind} {number}", hm.group(1).strip() if hm else "", chapter)
            else:
                rejected.append(f"p.{page}: {line[:50]!r}")
        block.append((page, line))
    close()

    # Footnotes: each unit gets those whose marks are in its own lines: what changed into
    # amended_by, the old wording into history. Footnotes with no mark in any unit's text (their
    # mark is in a table) go to the unit covering their page, so none is lost.
    used = set()
    for u, piece in zip(units, pieces_of):
        words_of = marked_words("\n".join(l for _, l in piece))
        for page, line in piece:
            for mark in LAW_MARK.findall(line):
                n = note_for(mark, page, f["index"])
                if n and id(n) not in used:
                    used.add(id(n))
                    u.amended_by.append(change_line(n, words_of.get(mark)))
                    if n["old"] or n["notes_on_old"]:
                        u.history.append(history_text(n))
    for n in f["notes"]:
        if id(n) in used:
            continue
        owner = next((u for u in reversed(units) if u.page_start <= n["page"]), units[0])
        owner.amended_by.append(n["said"])
        if n["old"] or n["notes_on_old"]:
            owner.history.append(history_text(n))
        owner.warnings.append(f"footnote '{n['mark']}' (p.{n['page']}) has no mark in the text; "
                              f"given to this unit as it covers that page")
        used.add(id(n))

    tables, owners, w = link_tables(units, doc, pdf, part, start, kind)
    warnings += w
    if gaps:
        warnings += [f"gap: {g}" for g in gaps]
    if rejected:
        warnings += [f"looks like a start but out of order (kept as text): {r}" for r in rejected]

    problems = self_check_units(units, lines, kind)
    problems.update({k: v for k, v in f["checks"].items() if v})  # the footnote step's own checks
    if found := finish(units, DOC_FILE, part=part["name"]):
        problems["finish"] = "; ".join(found)
    for t in tables:  # unit_id is known only now, after finish()
        t["unit_id"] = t.pop("owner").unit_id
    left = [t["table_id"] for t in tables
            if any(LAW_MARK.search(c) for row in [t["headings"]] + t["rows"] for c in row)]
    if left:
        problems["marks_left_in_tables"] = f"{len(left)}: {left[:5]}"
    info = {"headers_dropped": headers, "marks": f["marks"], "marks_missing": f["missing"],
            "tables": tables, "owners": owners}
    return units, problems, warnings, info


# ---------- 4b. Tables -> the rule they belong to ----------
#
# The extractor keeps tables apart from the page text and leaves no mark where they stood, so
# a table is placed by its height on the page: it belongs to the rule that starts above it on
# that page, else to the rule running on from an earlier page (Rules p.261's table: rule 61).
# A table printed in the footnotes' small font is an OLD table, quoted under "Prior to its
# substitution, it was read as:" (rule 138's e-way tables, p.331/332/334, all 8pt; the current
# ones, p.337-340, are 9pt). It goes to the rule's history with a label, never to table_ids.

def lines_with_y(page: pymupdf.Page) -> list[tuple[float, str]]:
    """One PDF page -> [(top of the line, its text)], top to bottom."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                out.append((line["bbox"][1], text))
    return sorted(out)


def table_top(t: dict, page: pymupdf.Page) -> float | None:
    """Where the table starts on its first page: the highest line holding its longest heading,
    else a cell of its first row (Gemini's made-up "Column 1" headings aren't in the PDF)."""
    heads = sorted((key(str(h)) for h in t["headings"] or []), key=len, reverse=True)
    cells = sorted((key(str(c)) for c in (t["rows"][0] if t["rows"] else [])), key=len, reverse=True)
    # Not the running header at the top: "Ch-XIX : Offences and Penalties" holds "offence" (p.358).
    lines = [(y, key(text)) for i, (y, text) in enumerate(lines_with_y(page))
             if not (i < 3 and HEADER.match(text))]
    for target in [h for h in heads if len(h) >= 4] + [c for c in cells if len(c) >= 6]:
        # A heading can wrap: "Compounding amount if" / "offence is punishable ..." (p.358), so a
        # line that is the heading's start counts too.
        ys = [y for y, k in lines if target[:20] in k or (len(k) >= 8 and target.startswith(k))]
        if ys:
            return min(ys)
    return None


def table_font(t: dict, pdf: pymupdf.Document) -> float | None:
    """The size most of the table's text is printed in."""
    cells = {" ".join(str(c).split()) for row in t["rows"] for c in row if len(str(c).strip()) > 8}
    sizes = Counter()
    for p in sorted(set(t["row_pages"])):
        for text, size in pdf_lines(pdf[p - 1]):
            if any(text[:15] in c for c in cells):
                sizes[size] += len(text)
    return sizes.most_common(1)[0][0] if sizes else None


def clean_cell(cell) -> str:
    return " ".join(clean(str(cell), OPEN_MARK).split())


def link_tables(units: list[Unit], doc: dict, pdf: pymupdf.Document, part: dict,
                start: re.Pattern, kind: str) -> tuple[list[dict], dict[str, str], list[str]]:
    """Each table of the part -> its unit. Returns (current tables, cleaned, each with its owner
    unit; {table: "rule 61" or "old, in rule 138's history"} for the check; warnings)."""
    first, last = part["pages"]
    body = body_size(pdf, first, last)
    numbered = {u.location: u for u in units if u.unit_type == kind}
    tables, owners, warnings = [], {}, []
    for t in doc["tables"]:
        if not t["row_pages"] or not first <= min(t["row_pages"]) <= last:
            continue
        p, name = min(t["row_pages"]), t["table_id"].rsplit(":", 1)[-1]
        top = table_top(t, pdf[p - 1])
        starts = [(y, f"{kind} {int(m.group(1))}{m.group(2)}")
                  for y, text in lines_with_y(pdf[p - 1]) if (m := start.match(text))]
        above = [loc for y, loc in starts if top is not None and y < top and loc in numbered]
        if above:
            owner = numbered[above[-1]]
        else:
            if top is None:
                warnings.append(f"p.{p}: {name} not found on its page; given to the rule running there")
            earlier = [u for u in units if u.page_start < p]
            owner = earlier[-1] if earlier else units[0]
        size = table_font(t, pdf)
        rows = [[clean_cell(c) for c in row] for row in t["rows"]]
        heads = [clean_cell(h) for h in t["headings"] or []]
        pages = sorted(set(t["row_pages"]))
        if size is not None and size <= body - SMALLER:
            owner.history.append(f"Old table, printed in the footnotes (p.{pages[0]}), as it read before an "
                                 f"amendment: " + " | ".join(heads) + " || "
                                 + " || ".join(" | ".join(r) for r in rows))
            owners[name] = f"old, in {owner.location}'s history"
        else:
            owner.table_ids.append(t["table_id"])
            owners[name] = owner.location
            tables.append({"table_id": t["table_id"], "owner": owner, "pages": pages,
                           "headings": heads, "rows": rows})
    return tables, owners, warnings


# ---------- 5. Self-check ----------

def self_check_units(units: list[Unit], lines: list[tuple[int, str]], kind: str) -> dict[str, str]:
    """Problems found, as {check: reason}. Empty means every check passed."""
    problems = {}
    body = clean("\n".join(l for _, l in lines), OPEN_MARK)
    left = [u.location for u in units if LAW_MARK.search(u.text) or "*" in u.text]
    if left:
        problems["marks_left_in_text"] = f"{len(left)} units, e.g. {left[:5]}"
    old = [u.location for u in units if PRIOR.search(u.text)]
    if old:
        problems["old_text_in_text"] = f"{len(old)} units, e.g. {old[:5]}"
    headers = [u.location for u in units if any(HEADER.match(l) for l in u.text.split("\n"))]
    if headers:
        problems["running_header_in_text"] = f"{len(headers)} units, e.g. {headers[:5]}"
    # Nothing lost: every word of the law lines is in some unit (text, heading or parent; the
    # chapter lines live on as parents). Nothing doubled: text only, against the law lines.
    kept, text_only = Counter(), Counter()
    for u in units:
        kept += words(" ".join([u.heading, u.parent, u.text]))
        text_only += words(u.text)
    lost = words(body) - kept
    if lost:
        problems["words_lost"] = f"{sum(lost.values())} words, e.g. {lost.most_common(8)}"
    doubled = text_only - words(body)
    if doubled:
        problems["words_doubled"] = f"{sum(doubled.values())} words, e.g. {doubled.most_common(8)}"
    # Every unit starts with its own number: "rule 88C" with "Rule 88 C." or "Rule88C.",
    # "rule 2(a)" with "(a)". Catches a boundary that slipped by a line.
    word = kind.capitalize()
    wrong = []
    for u in units:
        if u.unit_type == "definition":
            ok = u.text.startswith("(" + u.location.rsplit("(", 1)[-1])
        elif u.unit_type == kind:
            m = re.match(r"\w+ (\d+)([A-Z]*)$", u.location)
            ok = bool(m) and re.match(rf"{word}\s*{m.group(1)}\s?{m.group(2)}\.", u.text)
        else:
            continue
        if not ok:
            wrong.append(f"{u.location}: {u.text[:30]!r}")
    if wrong:
        problems["wrong_start"] = f"{len(wrong)} units, e.g. {wrong[:3]}"
    return problems


# ---------- 6. Run it and show what happened ----------

# ICAI's copy of the CGST Act: same style. We split the India Code copy instead (act.py), so
# these pages serve only as a held-out test: the same code splits them into sections, and the
# section numbers must match act.py's from the India Code PDF (two sources, one answer).
HELD_OUT = {"name": "CGST Act, ICAI copy (held-out)", "pages": [20, 181], "starts_with": "Section"}
SHOW = ["rule 2(a)", "rule 37", "rule 88C", "rule 113", "rule 138"]
# Which rule each CGST Rules table belongs to, checked by the user in the PDF, 2026-11-04.
# p.190's second table (table-2) is old rule 7's table, quoted in a footnote (8pt, symbol marks).
# p.358's table belongs to rule 162 (sub-rule 3A).
TABLE_GOLD = {
    "table-1": "rule 7", "table-2": "old, in rule 7's history",
    "table-3": "rule 10B", "table-8": "rule 31D",                # user
    "table-4": "rule 61", "table-9": "rule 61",                  # user: one table, cut by footnotes
    "table-10": "rule 83A", "table-11": "rule 83A",              # user
    "table-12": "old, in rule 138's history", "table-13": "old, in rule 138's history",
    "table-14": "old, in rule 138's history",
    "table-5": "rule 138", "table-6": "rule 138", "table-15": "rule 162",
}


def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    doc = json.loads((INGESTED / f"{DOC_FILE}.json").read_text())
    pdf = pymupdf.open(DOCS / DOC_FILE)
    all_ok, saved, saved_tables = True, [], []
    for part in known_parts(DOC_FILE) + [HELD_OUT]:
        units, problems, warnings, info = split_part(doc, pdf, part)
        held_out = part is HELD_OUT
        if not held_out:
            saved += units
            saved_tables += info["tables"]
        kinds = Counter(u.unit_type for u in units)
        print(f"\n== {part['name']} (p.{part['pages'][0]}-{part['pages'][1]}): {len(units)} units ("
              + ", ".join(f"{k} {n}" for k, n in kinds.most_common()) + ")")
        print(f"   running header lines dropped {info['headers_dropped']}; law marks {info['marks']}, "
              f"without a footnote {len(info['marks_missing'])}")
        owners = info["owners"]
        print(f"   tables {len(owners)}: {len(info['tables'])} current, "
              f"{sum(o.startswith('old') for o in owners.values())} old (into history)")
        if part["name"] == "CGST Rules, 2017":
            wrong = {t: (owners.get(t), want) for t, want in TABLE_GOLD.items() if owners.get(t) != want}
            print(f"   tables vs the user's answers: {len(TABLE_GOLD) - len(wrong)}/{len(TABLE_GOLD)} right")
            for t, (got, want) in wrong.items():
                print(f"     {red}{t}{reset}: got {got}, should be {want}")
            if wrong:
                problems["tables_differ_from_gold"] = f"{len(wrong)} of {len(TABLE_GOLD)}"
        for w in warnings[:8]:
            print(f"   {red}warning{reset} {w}")
        if len(warnings) > 8:
            print(f"   ... {len(warnings) - 8} more warnings")
        if held_out:
            india_code = {json.loads(l)["location"] for l in (UNITS / "GST_act.pdf.jsonl").open()
                          if json.loads(l)["unit_type"] == "section"}
            icai = {u.location for u in units if u.unit_type == "section"}
            print(f"   sections vs India Code (act.py): {len(india_code & icai)} in both; "
                  f"only India Code {sorted(india_code - icai)[:8]}; only ICAI {sorted(icai - india_code)[:8]}")
            if india_code != icai:
                problems["sections_differ_from_india_code"] = f"{len(india_code ^ icai)} differ"
        all_ok &= not problems
        print(f"   self-check: {green}all passed{reset}" if not problems else "   self-check:")
        for check, reason in problems.items():
            print(f"     {red}{check}{reset}: {reason}")

    out = UNITS / f"{DOC_FILE}.jsonl"
    with out.open("w") as fh:
        for u in saved:
            fh.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")
    print(f"\nSaved {len(saved)} units (the Rules; not the held-out): {out.relative_to(ROOT)}")
    out_tables = UNITS / f"{DOC_FILE}.tables.jsonl"
    with out_tables.open("w") as fh:
        for t in saved_tables:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"Saved {len(saved_tables)} current tables, marks cleaned, each with its unit_id: "
          f"{out_tables.relative_to(ROOT)}")
    t5 = next((t for t in saved_tables if t["table_id"].endswith(":table-5")), None)
    if t5:
        print(f"--- {t5['table_id']} -> {t5['unit_id']}: {t5['headings']}")
        for r in t5["rows"][:2]:
            print(f"    {[c[:50] for c in r]}")
    for loc in SHOW:
        u = next((u for u in saved if u.location == loc), None)
        if u:
            print(f"\n--- {u.location} | {u.heading} | {u.parent} | p.{u.page_start}-{u.page_end} | "
                  f"{u.unit_id} | {u.token_count} tokens")
            print("    " + u.text[:220].replace("\n", "\n    ") + (" ..." if len(u.text) > 220 else ""))
            print(f"    amended_by {len(u.amended_by)}:")
            for a in u.amended_by[:4]:
                print(f"      - {a[:150]}")
            print(f"    history {len(u.history)}" + (f": {u.history[0][:120]} ..." if u.history else ""))
    sizes = sorted((u.token_count for u in saved), reverse=True)
    print(f"\nTokens per unit: median {sizes[len(sizes) // 2]}, largest {sizes[:3]}, "
          f"over 512: {sum(s > 512 for s in sizes)} of {len(sizes)}")
    print(f"\n{green}all passed{reset}" if all_ok else f"\n{red}some checks failed{reset}")


if __name__ == "__main__":
    main()

