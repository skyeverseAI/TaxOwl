"""Question -> the sections, rules and circulars it names. Reads text only: no store, no model.

    read_citations("What does section 16(4) say?")
    -> [Citation("section", "16", ("4",), "CGST Act", law_assumed=True)]

No law named means the CGST Act or CGST Rules, and `law_assumed` says so, so the answer can say it too.
A section of another law (Income-tax Act and so on) gives no citation: better no exact hit than the
wrong law's text. A date is not a circular.

Check it: uv run experiments/try_citations.py
"""

import re
from dataclasses import dataclass

MAX_RANGE = 20  # "sections 16 to 18" is listed out; a longer span is more likely a misreading


@dataclass(frozen=True)
class Citation:
    kind: str                     # "section", "rule" or "circular"
    number: str                   # "16", "110A", "183/15/2022"
    path: tuple[str, ...] = ()    # 17(5)(g) -> ("5", "g")
    law: str | None = None        # "CGST Act"; None for a circular
    law_assumed: bool = False     # True when the question named no law


# ---- how a section or rule is written

NUMBER = r"\d{1,3}[A-Za-z]{0,2}(?![A-Za-z0-9/])"     # 16, 110A; not 2017 or the start of 183/15/2022
PART = r"\d+[A-Za-z]?|[ivxIVX]{1,5}|[A-Za-z]{1,2}"   # what sits in brackets: 4, 3A, g, iii
PATH = rf"(?:\s*\(\s*(?:{PART})\s*\))*"              # (5)(g)
SEPARATOR = r"\s*(?:,\s*(?:and\s+|or\s+)?|&\s*|(?:and|or|aur|to)\s+|[-–—]\s*)"
NOT_SUB = r"(?<![A-Za-z-])(?<!(?i:sub) )"            # "sub-section 4" alone is no section 4
KEYWORDS = {
    "section": rf"{NOT_SUB}(?i:sections?|secs?\.?|ss?\.|u/s\.?)",
    "rule": rf"{NOT_SUB}(?i:rules?|r\.)",
}
# "clause (g) of sub-section (5) of": the outer parts, written in front of the section
LEAD_WORD = r"(?i:(?:sub[- ]?)?clause|sub[- ]?section|sub[- ]?rule)"
LEAD = rf"{LEAD_WORD}\s*\(?\s*(?:{PART})\s*\)?\s+(?i:of)\s+(?:(?i:the)\s+)?"
REFERENCES = {
    kind: re.compile(
        rf"(?P<lead>(?:{LEAD})+)?{keyword}\s*"
        rf"(?P<items>{NUMBER}{PATH}(?:{SEPARATOR}{NUMBER}{PATH})*)"
    )
    for kind, keyword in KEYWORDS.items()
}
ITEM_RE = re.compile(rf"({NUMBER})({PATH})")
PART_RE = re.compile(rf"\(\s*({PART})\s*\)")
LEAD_RE = re.compile(rf"{LEAD_WORD}\s*\(?\s*({PART})\s*\)?")
RANGE_WORD = re.compile(r"\bto\b|[-–—]")
ONLY_JOINED = re.compile(r"\s*(?:,|&|and|or|aur)?\s*", re.I)

# ---- how a law is named

OTHER = "OTHER"
PLAIN = "PLAIN"
SUFFIX = r"(?:\s+(?:act|rules))?(?:,?\s*\d{4})?"
GST_WORDS = r"(?:goods\s+and\s+services\s+tax|gst)"
LAW_RE = re.compile(
    rf"(?P<CGST>\bCGST\b{SUFFIX}|\bcentral\s+{GST_WORDS}{SUFFIX})"
    rf"|(?P<IGST>\bIGST\b{SUFFIX}|\bintegrated\s+(?:{GST_WORDS}|tax){SUFFIX})"
    rf"|(?P<UTGST>\bUT\s?GST\b{SUFFIX}|\bunion\s+territory\s+{GST_WORDS}{SUFFIX})"
    rf"|(?P<COMPENSATION>(?:\b{GST_WORDS}\s*\(\s*)?\bcompensation\s+to\s+states\)?{SUFFIX}"
    rf"|\bcompensation(?:\s+cess)?\s+act\b{SUFFIX})"
    rf"|(?P<PLAIN>\b{GST_WORDS}\s+(?:act|rules){SUFFIX})"   # names no one law
    r"|(?P<OTHER>\bincome[- ]?tax\b(?:\s+act)?|\bi\.?t\.?\s+act\b|\bcustoms\b(?:\s+act)?"
    r"|\b(?:central\s+)?excise\b(?:\s+act)?|\bservice\s+tax\b|\bsgst\b(?:\s+act)?|\bvat\b(?:\s+act)?"
    r"|(?-i:(?!(?:The|This|That|Said|GST|Under|What|Does)\b)(?:[A-Z][\w-]*\s+){1,4}(?:Act|Rules|Code))\b)",
    re.I,
)
SAYS_ACT = re.compile(r"\b(?:act|rules)\b", re.I)
ATTACHED = re.compile(r"\s*,?\s*(?:(?:of|under|in|from|ke|ka|ki)\s+)?(?:(?:the|said)\s+)?", re.I)
SAME_LAW = re.compile(r"\s*,?\s*(?:(?:of|under|in|from)\s+)?(?:the\s+)?(?:that|said|same)\s+(?:act|rules)\b", re.I)
JOINS_LATER_NAME = re.compile(r"\b(?:in|under|of)\s+(?:the\s+)?$", re.I)
SENTENCE_END = re.compile(r"[.?!;]\s")
CLOSE = 6 # characters between a bare name and the citation: "IGST section 16", "Income-tax Act, s.16"

LAW_NAMES = {
    ("CGST", "section"): "CGST Act", ("CGST", "rule"): "CGST Rules",
    ("IGST", "section"): "IGST Act", ("IGST", "rule"): "IGST Rules",
    ("UTGST", "section"): "UTGST Act",
    ("COMPENSATION", "section"): "Compensation Act",
}  # UTGST and Compensation rules aren't in our documents, so a citation to them is dropped

# ---- how a circular number is written

CIRCULAR_NUMBER = r"\d{1,3}\s*/\s*\d{1,3}\s*/\s*\d{4}(?![\d/])"
AFTER_WORD = re.compile(
    rf"(?<![A-Za-z])(?i:circulars?)(?:\s+(?i:nos?\.?|number))?\s*[:#.-]?\s*"
    rf"(?P<numbers>{CIRCULAR_NUMBER}(?:\s*(?:,|&|and|aur)\s*{CIRCULAR_NUMBER})*)"
)
WITH_TAG = re.compile(rf"(?<![\d/])(?P<numbers>{CIRCULAR_NUMBER})\s*-+\s*(?i:[ci]?gst)\b")
ONE_NUMBER = re.compile(CIRCULAR_NUMBER)


def clean_part(part: str) -> str:
    """Numbers in capitals (3A), letters small (g, iii), as the chunk locations write them."""
    return part.upper() if part[0].isdigit() else part.lower()


def read_items(items: str, lead: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
    """'16(2) and 17' -> [("16", ("2",)), ("17", ())]; '16 to 18' lists 16, 17, 18."""
    found: list[tuple[str, tuple[str, ...]]] = []
    previous = None
    for match in ITEM_RE.finditer(items):
        number = match[1].upper()
        path = tuple(clean_part(p) for p in PART_RE.findall(match[2]))
        if previous and not path and not found[-1][1] and number.isdigit() and found[-1][0].isdigit():
            low, high = int(found[-1][0]), int(number)
            if RANGE_WORD.search(items[previous.end():match.start()]) and 0 < high - low <= MAX_RANGE:
                found += [(str(n), lead) for n in range(low + 1, high)]
        found.append((number, path + lead))
        previous = match
    return found


def which_law(question: str, start: int, end: int, floor: int, stop: int) -> tuple[str | None, int]:
    """The law named for the citation at start..end -> (family, OTHER or None; where the name ended).

    First a name right after it ("of the IGST Act"), then one earlier in the sentence, then a full name
    later in the sentence, before the next citation (`stop`). `floor` is where the last citation's own
    law name ended, so a name is never used twice. A bare "IGST" must sit close ("Can I claim IGST
    credit under section 16?" means CGST section 16), and another law too ("income tax" elsewhere in
    the sentence doesn't make section 16 an income-tax section). A later name must follow in, under or
    of: "section 16 say in the IGST Rules" counts, "how section 16 differs from the IGST Act" doesn't.
    """
    after = LAW_RE.match(question, ATTACHED.match(question, end).end())
    if after:
        return (None if after.lastgroup == PLAIN else after.lastgroup), after.end()

    ends = list(SENTENCE_END.finditer(question, floor, start))
    sentence_start = ends[-1].end() if ends else floor
    for name in reversed(list(LAW_RE.finditer(question, sentence_start, start))):
        close = start - name.end() <= CLOSE
        if name.lastgroup == OTHER:
            if close:
                return OTHER, end
        elif name.lastgroup == PLAIN:
            return None, end
        elif close or SAYS_ACT.search(name.group()):
            return name.lastgroup, end

    sentence_end = SENTENCE_END.search(question, end, stop)
    for name in LAW_RE.finditer(question, end, sentence_end.start() if sentence_end else stop):
        if (name.lastgroup not in (OTHER, PLAIN) and SAYS_ACT.search(name.group())
                and JOINS_LATER_NAME.search(question, end, name.start())):
            return name.lastgroup, name.end()
    return None, end


def find_law_refs(question: str) -> list[tuple[int, Citation]]:
    """Every section and rule in the question -> [(where it starts, citation)]."""
    matches = sorted(
        ((m, kind) for kind, regex in REFERENCES.items() for m in regex.finditer(question)),
        key=lambda pair: pair[0].start(),
    )
    laws: list[str | None] = []
    floor = 0
    for i, (match, _) in enumerate(matches):
        same = SAME_LAW.match(question, match.end())
        if same:  # "section 12(3) of that Act": the law of the citation before it
            laws.append(laws[-1] if laws else None)
            floor = same.end()
            continue
        stop = matches[i + 1][0].start() if i + 1 < len(matches) else len(question)
        family, floor = which_law(question, match.start(), match.end(), floor, stop)
        laws.append(family)

    # "section 16 and section 17 of the IGST Act": both are IGST. Same the other way round.
    order = list(range(len(matches)))
    for sequence, step in ((order[1:], -1), (order[-2::-1], 1)):
        for i in sequence:
            near = i + step
            gap = question[min(matches[i][0].end(), matches[near][0].end()):
                           max(matches[i][0].start(), matches[near][0].start())]
            if laws[i] is None and matches[i][1] == matches[near][1] and ONLY_JOINED.fullmatch(gap):
                laws[i] = laws[near]

    found: list[tuple[int, Citation]] = []
    for (match, kind), family in zip(matches, laws):
        if family == OTHER:
            continue
        law = LAW_NAMES.get((family or "CGST", kind))
        if law is None:
            continue
        lead = tuple(clean_part(p) for p in reversed(LEAD_RE.findall(match["lead"] or "")))
        for number, path in read_items(match["items"], lead):
            found.append((match.start(), Citation(kind, number, path, law, law_assumed=family is None)))
    return found


def find_circulars(question: str) -> list[tuple[int, Citation]]:
    """Circular numbers: only after the word "circular" or with -GST behind them, as a date looks the same."""
    found: list[tuple[int, Citation]] = []
    for regex in (AFTER_WORD, WITH_TAG):
        for match in regex.finditer(question):
            for number in ONE_NUMBER.finditer(match["numbers"]):
                found.append((match.start("numbers") + number.start(),
                              Citation("circular", re.sub(r"\s", "", number.group()))))
    return found


def read_citations(question: str) -> list[Citation]:
    """All citations in the question, in the order they appear, each once."""
    found = sorted(find_law_refs(question) + find_circulars(question), key=lambda pair: pair[0])
    return list(dict.fromkeys(citation for _, citation in found))
