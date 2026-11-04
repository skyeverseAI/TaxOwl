"""The CGST Act (India Code PDF) -> one Unit per section, definition and schedule item.

What the PDF looks like (checked by eye 2026-11-03; page numbers are the PDF's own):
  p.1-2   title page, list of amending Acts            -> one "other" unit
  p.3-9   contents ("ARRANGEMENT OF SECTIONS")         -> not a unit; used as the CHECKLIST
  p.10-   the Act: "16. Eligibility and ....—(1) ..."   -> one "section" unit each
          s.2: '(52) "goods" means ...'                 -> one "definition" unit each
          "SCHEDULE I" ... "1. Permanent transfer ..."  -> one "schedule" unit per item
  end     "STATEMENT OF OBJECTS AND REASONS"            -> one "other" unit

The marks inside the text, and what we do with them:
  1[ ... ]       words added by an amendment -> keep the words, drop "1[" and its "]",
                 and put footnote 1 of that page into amended_by
  3* * * *       words deleted by an amendment -> drop the stars, keep footnote 3
  footnotes      "1. Ins. by Act 8 of 2023 ..." at the page bottom; numbering restarts each page

Two traps: footnotes and schedule items both start "1. ...", just like section 1. Footnotes are
lifted off each page first. For the rest, the contents list decides: a line starts a section
only if its number is the NEXT one on the list.

Run:  uv run python -m taxowl.splitting.act                (the CGST Act)
      uv run python -m taxowl.splitting.act <file under docs/>  (another India Code Act, once extracted)
Out:  data/units/<file>.jsonl (one Unit per line, to look at), plus a summary and self-check.
"""

import json
import re
import sys
from collections import Counter
from dataclasses import asdict

from taxowl.config import INGESTED, ROOT, UNITS
from taxowl.schema import Unit
from taxowl.splitting import finish

DEFAULT = "GST_act.pdf"                # the CGST Act; another Act is passed on the command line

# A section number: 16, 11A, 158A. An inserted section carries its mark first: "4[74A."
SECTION_START = re.compile(r"^(?:\d{1,2}\[)?(\d{1,3}[A-Z]{0,2})\.(?:\s|$)")  # "1[158A." can end its line
CHAPTER = re.compile(r"^CHAPTER ([IVXL]+[A-Z]?)$")
SCHEDULE = re.compile(r"^SCHEDULE ([IV]+)\.?$")
DEFINITION = re.compile(r"^(?:\d{1,2}\[)?\((\d{1,3})([A-Z]?)\)\s")
# Amendment marks: "1[" (added words) and "3*" / "1***" (deleted words). Never right after a
# letter, digit or dot, so "section 2" or "(w.e.f." are not touched.
MARK = re.compile(r"(?<![\w.])(\d{1,2})(?=\[|\*)")
OPEN_MARK = r"(?<![\w.])\d{1,2}\["
# Stars, with the footnote number before them ("3*", "1***"), or alone ("Kashmir*]", s.22).
STARS = re.compile(r"(?:(?<![\w.])\d{1,2})?\*(?:\s*\*)*")
DASH = r"\.?\]?\s*(?:—|––|–|\.-)"  # what ends a section heading: ".—", ".––", "]—"


# ---------- 1. The contents pages: the checklist ----------

def read_contents(pages: list[str], first: int, last: int) -> list[tuple[str, str, str]]:
    """Contents pages -> [(number, heading, chapter)] in order, e.g.
    ("16", "Eligibility and conditions for taking input tax credit", "Chapter V Input Tax Credit")."""
    entries: list[list[str]] = []
    chapter, title, in_title = "", [], False
    for page in pages[first:last]:
        for line in (l.strip() for l in page.split("\n")):
            if m := CHAPTER.match(line):
                chapter, title, in_title = m.group(1), [], True
            elif line == "SECTIONS":
                continue  # the column label at the top of each contents page
            elif in_title and line.isupper():
                title.append(line)  # the chapter's name, e.g. "INPUT TAX CREDIT"
            elif m := SECTION_START.match(line):
                in_title = False
                entries.append([m.group(1), line[m.end():].rstrip("."),
                                f"Chapter {chapter} {nice(' '.join(title))}"])
            elif entries and line and not line.isupper() and not line.startswith("_"):
                entries[-1][1] += " " + line.rstrip(".")  # a heading that ran onto a second line
    return [tuple(e) for e in entries]


def nice(title: str) -> str:
    """'INPUT TAX CREDIT' -> 'Input Tax Credit', with small words kept small."""
    small = {"of", "and", "the", "in", "to", "for", "or", "on", "by", "as", "be", "if"}
    return " ".join(w.lower() if i and w.lower() in small else w
                    for i, w in enumerate(title.title().split()))


# ---------- 2. Footnotes: lift them off the bottom of each page ----------

def split_footnotes(page: str) -> tuple[list[str], dict[int, str]]:
    """One page -> (its body lines, {footnote number: footnote text}).

    The footnotes are the last run of lines numbered 1, 2, 3 ... down to the page end, on a page
    that has amendment marks. (Checked: on 121 of the 122 body pages this gives exactly as many
    footnotes as the page has marks. The other has a typo, "5 Subs." with no dot, so the dot is
    optional after footnote 1.) A schedule page with items "1. 2. 3." but no marks is left alone."""
    lines = page.split("\n")
    for start in range(len(lines) - 1, -1, -1):
        if not lines[start].startswith("1. "):
            continue
        if not any(MARK.search(l) for l in lines[:start]):
            return lines, {}  # no marks above, so these numbered lines aren't footnotes
        notes: dict[int, str] = {}
        for line in lines[start:]:
            n = len(notes) + 1
            m = re.match(rf"^{n}\.\s" if n == 1 else rf"^{n}\.?\s", line)
            if m:
                notes[n] = line[m.end():]
            else:
                notes[n - 1] += " " + line  # a footnote that runs onto the next line
        return lines[:start], notes
    return lines, {}


# ---------- 3. Cleaning: take the marks out, keep the words ----------

def clean(text: str, open_mark: str = OPEN_MARK) -> str:
    """Drop amendment marks, keep the law's words.
      'the 3[Central Board of Indirect Taxes and Customs], the' -> 'the Central Board of ..., the'
      'outward 1*** supplies'                                  -> 'outward supplies'
    A "[" that isn't a mark (like "[See section 7]") keeps its "]". A stack pairs each "]" with
    the "[" it closes, so brackets inside brackets work. `open_mark`: another document's mark
    pattern (icai.py's also takes a mark glued to a word, "Authority21[or"; a space replaces it)."""
    out, stack, pos = [], [], 0
    for m in re.finditer(rf"{open_mark}|\[|\]", text):
        out.append(text[pos:m.start()])
        token = m.group()
        if token == "[":
            stack.append("plain")
            out.append("[")
        elif token == "]":
            if not stack or stack.pop() == "plain":
                out.append("]")  # closes a normal bracket (an unmatched one is kept too)
            elif text[m.end():m.end() + 1].isalpha():
                out.append(" ")  # "14[six]months" (ICAI p.326) -> "six months", not "sixmonths"
        else:
            stack.append("mark")  # "N[": dropped now, and its "]" when it comes
            if m.start() and text[m.start() - 1].isalpha():
                out.append(" ")  # "Authority21[or" -> "Authority or"
        pos = m.end()
    out.append(text[pos:])
    text = STARS.sub("", "".join(out))
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    return "\n".join(l for l in lines if l)


def footnotes_used(lines: list[tuple[int, str]], notes: dict[int, dict[int, str]]) -> list[str]:
    """The footnotes whose marks appear in these lines (each line knows its page)."""
    found = []
    for page, line in lines:
        for n in MARK.findall(line):
            note = notes.get(page, {}).get(int(n), "").strip()
            if note and note not in found:
                found.append(note)
    return found


# ---------- 4. The split ----------

def split(doc: dict) -> tuple[list[Unit], dict]:
    """ExtractedDoc (as loaded from its JSON) -> (units, self-check report)."""
    pages, doc_file = doc["pages"], doc["file"]  # the document names itself; no file is hard-coded
    contents_from = next(i for i, p in enumerate(pages) if "ARRANGEMENT OF SECTIONS" in p)
    body_from = next(i for i, p in enumerate(pages)
                     if re.search(r"^1\. Short title[^\n]*(—|––)", p, re.M))
    contents = read_contents(pages, contents_from, body_from)
    numbers = [c[0] for c in contents]

    # Every body line with its page number (1-based); footnotes lifted off; chapter headings out.
    notes: dict[int, dict[int, str]] = {}
    lines: list[tuple[int, str]] = []
    for i in range(body_from, len(pages)):
        body, notes[i + 1] = split_footnotes(pages[i])
        lines += [(i + 1, l.strip()) for l in body if l.strip()]
    resolve_ibid(notes)
    body_text = "\n".join(pages[:contents_from] + [l for _, l in lines])  # for the self-check

    units = [Unit("other", doc_file, "front matter", "Title and list of amending Acts",
                  clean("\n".join(pages[:contents_from])), 1, contents_from)]

    # Walk the lines. `block` holds the lines of the piece we're in; close() turns it into units.
    block: list[tuple[int, str]] = []
    current = ("other", "preamble", "Long title and enacting formula", "")  # type, location, heading, parent
    next_i = 0              # position on the contents list: the section we expect next
    skipped: list[str] = []
    skip_notes: dict[str, str] = {}  # location of the section found after a gap -> warning
    chapter, chapter_words, in_chapter_heading = "", [], False
    schedule, schedule_title, item = "", [], 0

    def close():
        if not block:
            return
        unit_type, location, heading, parent = current
        if location == "section 2":
            units.extend(split_definitions(block, notes, parent, doc_file))
        else:
            units.append(Unit(unit_type, doc_file, location, clean(heading),
                              clean("\n".join(l for _, l in block)), block[0][0], block[-1][0],
                              parent=parent, amended_by=footnotes_used(block, notes)))

    for i, (page, line) in enumerate(lines):
        # "CHAPTER V" and the upper-case name under it ("INPUT TAX CREDIT") sit between sections.
        # They go into `parent`, not into any section's text. The name is taken from here, not
        # from the contents list: the contents has a typo ("OFFENCES AND PENALITIS", ch. XIX).
        if m := CHAPTER.match(line):
            chapter, chapter_words, in_chapter_heading = m.group(1), [], True
            continue
        if in_chapter_heading and line.isupper():
            chapter_words.append(line)
            continue
        in_chapter_heading = False

        if m := SCHEDULE.match(line):
            close()
            block, schedule, schedule_title, item = [], m.group(1), [], 0
            current = ("other", f"Schedule {schedule}", f"Schedule {schedule}", "")
            continue
        if line.startswith("STATEMENT OF OBJECTS AND REASONS"):
            close()
            block, schedule = [], "done"
            current = ("other", "statement of objects and reasons", "Statement of Objects and Reasons", "")
        elif schedule and schedule != "done":
            if re.match(rf"^(?:\d{{1,2}}\[)?{item + 1}\.\s", line):  # this schedule's next item
                close()
                block, item = [], item + 1
                parent = f"Schedule {schedule} {nice(clean(' '.join(schedule_title)))}"
                current = ("schedule", f"Schedule {schedule} para {item}", "", parent)
            elif item == 0:  # "[See section 7]" and the schedule's title, before item 1
                schedule_title.append(line)
                continue
        elif (m := SECTION_START.match(line)) and m.group(1) in numbers[next_i:next_i + 3]:
            # The next section on the list (or one of the next three, so one miss can't derail
            # the rest; anything jumped over is reported).
            close()
            found = numbers.index(m.group(1), next_i)
            if numbers[next_i:found]:
                skip_notes[f"section {m.group(1)}"] = (
                    f"section(s) {', '.join(numbers[next_i:found])} on the contents list not found before this one")
            skipped += numbers[next_i:found]
            next_i = found + 1
            number, listed_heading, _ = contents[found]
            joined = " ".join(l for _, l in lines[i:i + 4])  # a heading can run over lines
            hm = re.match(rf"^(?:\d{{1,2}}\[)?{re.escape(number)}\.\s*(.+?){DASH}", joined)
            block = []
            parent = f"Chapter {chapter} {nice(clean(' '.join(chapter_words)))}"
            current = ("section", f"section {number}", hm.group(1) if hm else listed_heading, parent)
        block.append((page, line))
    close()
    attach_leftover_footnotes(units, notes)
    for u in units:  # a gap in the numbering is kept on the unit where it showed up, never hidden
        if u.location in skip_notes:
            u.warnings.append(skip_notes[u.location])

    report = self_check(units, body_text, notes, skipped + numbers[next_i:])
    for problem in finish(units, doc_file):  # unit_id, source_sha256, token_count
        report["finish"] = problem
    return units, report


def resolve_ibid(notes: dict[int, dict[int, str]]) -> None:
    """'Ins. by s. 138, ibid.' means 'the same Act as the footnote before'. Read alone, in a
    unit's amended_by, that says nothing, so write the Act in: 'Ins. by s. 138, Act 15 of 2024'.
    73 footnotes say ibid. The footnote before can be on the previous page, so carry it over."""
    last_act = ""
    for page in sorted(notes):
        for n in sorted(notes[page]):
            note = notes[page][n]
            if "ibid" in note and last_act:
                notes[page][n] = re.sub(r"\bibid\.?", last_act, note)
            elif m := re.search(r"\bAct \d+ of \d{4}|\bthe [A-Z][\w ,()]+ (?:Act|Order), \d{4}", note):
                last_act = m.group()


def attach_leftover_footnotes(units: list[Unit], notes: dict[int, dict[int, str]]) -> None:
    """A few footnotes have no "N[" mark we can see: the commencement note on p.10 ("22nd June,
    2017 for ss. 1, 2 ..."), "Explanation numbered as Explanation 1" on p.33, and one in a
    schedule's title on p.126. Rather than lose them, give each to the first section or
    schedule unit on its page."""
    claimed = {n for u in units for n in u.amended_by}
    for page, page_notes in notes.items():
        for note in (n.strip() for n in page_notes.values()):
            if note in claimed:
                continue
            owner = next((u for u in units if u.unit_type != "other"
                          and u.page_start <= page <= u.page_end), None)
            if owner:
                owner.amended_by.append(note)


def split_definitions(block: list[tuple[int, str]], notes: dict, parent: str, doc_file: str) -> list[Unit]:
    """Section 2 -> its opening words as a small section unit, then one unit per definition.
    A "(N)" line starts a definition only if N comes just after the last one (a gap of up to 3
    for omitted ones; "80A" after "80"), so a numbered list inside a definition can't."""
    pieces: list[tuple[str, list]] = [("intro", [])]
    last = 0
    for page, line in block:
        m = DEFINITION.match(line)
        if m and (last < int(m.group(1)) <= last + 3 or (int(m.group(1)) == last and m.group(2))):
            last = int(m.group(1))
            pieces.append((m.group(1) + m.group(2), []))
        pieces[-1][1].append((page, line))

    units = []
    for label, lines in pieces:
        text = clean("\n".join(l for _, l in lines))
        common = dict(doc_file=doc_file, text=text, page_start=lines[0][0], page_end=lines[-1][0],
                      amended_by=footnotes_used(lines, notes))
        if label == "intro":
            units.append(Unit("section", location="section 2", heading="Definitions", parent=parent, **common))
        else:
            term = re.search(r'["“]([^"”]+)["”]', text.split("\n")[0])
            term = term.group(1) if term else ""
            units.append(Unit("definition", location=f"section 2({label})",
                              heading=f'Definition of "{term}"' if term else "Definitions",
                              parent="section 2 Definitions", term=term, **common))
    return units


# ---------- 5. Self-check ----------

def words(text: str) -> Counter:
    """Words for the "nothing lost" check. Bare 1-2 digit numbers are left out: they're the
    amendment marks and footnote numbers we drop on purpose."""
    return Counter(w for w in re.findall(r"[a-z0-9]+", clean(text).lower())
                   if not (w.isdigit() and len(w) <= 2))


def self_check(units: list[Unit], body_text: str, notes: dict[int, dict[int, str]],
               missing: list[str]) -> dict[str, str]:
    """Problems found, as {check: reason}. Empty means every check passed."""
    problems = {}
    if missing:
        problems["sections_not_found"] = f"{len(missing)} on the contents list: {missing[:15]}"
    leftover = [u.location for u in units if re.search(rf"{OPEN_MARK}|\*", u.text)]
    if leftover:
        problems["marks_left_in_text"] = f"{len(leftover)} units, e.g. {leftover[:5]}"
    # Nothing lost, in two parts. (1) Every word of the law's text (all pages but the contents
    # and the footnotes) is in some unit.
    unit_words = Counter()
    for u in units:
        unit_words += words("\n".join([u.heading, u.parent, u.text]))
    lost = words(body_text) - unit_words
    if lost:
        problems["words_lost"] = f"{sum(lost.values())} words, e.g. {lost.most_common(10)}"
    # (2) Every footnote is in some unit's amended_by. Compared as distinct texts: when the same
    # amendment touches a section on two pages, the two identical footnotes are stored once.
    stored = {n for u in units for n in u.amended_by}
    unstored = {n.strip() for p in notes.values() for n in p.values()} - stored
    if unstored:
        problems["footnotes_lost"] = f"{len(unstored)}, e.g. {sorted(unstored)[:3]}"
    # Nothing doubled: no word is in the units' text more often than on the pages. (Text only:
    # a heading or parent is repeated on purpose.) Catches a paragraph put into two units.
    text_words = Counter()
    for u in units:
        text_words += words(u.text)
    doubled = text_words - words(body_text)
    if doubled:
        problems["words_doubled"] = f"{sum(doubled.values())} words, e.g. {doubled.most_common(10)}"
    # Every unit starts with its own number: "section 16" with "16.", "section 2(52)" with
    # "(52)", "Schedule I para 1" with "1.". Catches a boundary that slipped by a line.
    wrong_start = []
    for u in units:
        if u.unit_type == "section":
            anchor = u.location.removeprefix("section ") + "."
        elif u.unit_type == "definition":
            anchor = "(" + u.location.removeprefix("section 2(")
        elif u.unit_type == "schedule":
            anchor = u.location.rsplit(" ", 1)[-1] + "."
        else:
            continue
        if not u.text.startswith(anchor):
            wrong_start.append(f"{u.location}: {u.text[:30]!r}")
    if wrong_start:
        problems["wrong_start"] = f"{len(wrong_start)} units, e.g. {wrong_start[:3]}"
    return problems


# ---------- Run ----------

def main():
    doc_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    units, report = split(json.loads((INGESTED / (doc_file + ".json")).read_text()))
    out = UNITS / (doc_file + ".jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for u in units:
            f.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")

    kinds = Counter(u.unit_type for u in units)
    print(f"{doc_file}: {len(units)} units  (" + ", ".join(f"{k} {n}" for k, n in kinds.most_common()) + ")")
    print(f"Saved: {out.relative_to(ROOT)}\n")
    for loc in ["section 16", "section 2(52)", "section 42", "section 74A", "Schedule I para 1"]:
        u = next((u for u in units if u.location == loc), None)
        if u:
            print(f"--- {u.location} | {u.heading} | {u.parent} | pages {u.page_start}-{u.page_end}")
            print(f"    id {u.unit_id} | {u.token_count} tokens")
            print(u.text[:300] + (" ..." if len(u.text) > 300 else ""))
            print(f"    amended_by: {len(u.amended_by)} footnote(s)"
                  + (f", first: {u.amended_by[0][:90]}" if u.amended_by else "") + "\n")
    sizes = sorted((u.token_count for u in units), reverse=True)
    print(f"Tokens per unit: median {sizes[len(sizes) // 2]}, largest {sizes[:3]}, "
          f"over 512: {sum(s > 512 for s in sizes)} of {len(sizes)}\n")
    # Green if all passed, red for each problem (plain text when the output goes to a file).
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    print("Self-check:", f"{green}all passed{reset}" if not report else "")
    for check, reason in report.items():
        print(f"  {red}{check}{reset}: {reason}")


if __name__ == "__main__":
    main()
