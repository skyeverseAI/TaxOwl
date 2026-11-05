"""Unit -> pieces that fit the embedder (B2 in to-do-list.md; sizes decided from experiments/measure_units.py).

A unit that fits stays whole. A long one is cut along the law's own lines, biggest first, each
level only where the piece above it is still too long:

    para number "2.2.4" -> sub-section "(1)" -> clause "(a)" -> sentence -> line -> word

A number is believed only if it comes next in its own order and isn't a wrapped reference
("under sub-rule\n(2) of rule 8"). So a clause "(i)" inside "(a)" doesn't become its own citation.
A proviso has no number, so it stays with its sub-section. Citations are never made up: pieces cut
by sentence or line keep the citation of what they came from.
"""

import re
from dataclasses import dataclass, field

from taxowl.splitting import count_tokens

MAX_TOKENS = 400  # a whole chunk, heading included. bge reads 510; below that it's a choice, to test later
OVERLAP = 80      # at most this much of the piece before is repeated, only in units that are cut
SMALL = 50        # a smaller piece joins a neighbour if the two fit
LEAD_MAX = 120    # a clause repeats its sub-section's opening words only if they are this short
GAP = 5           # a sub-section number may skip this many (omitted ones)

SUBSECTION = re.compile(r"^\((\d{1,3})([A-Z]{0,2})\)(?:\s+(?=[A-Z\"“'‘\d(])|(?=\())")  # "(3) The", "(4)(a) The"
HEAD_LINES = 3    # a wrapped heading: "(1)" can sit on any of a unit's first lines
FIRST_INLINE = re.compile(r"[—–-]\s*\(1\)\s+[A-Z]")  # "129. Detention ...––(1) Notwithstanding ..."
CLAUSE = re.compile(r"^\(([a-z]{1,5})\)\s")
DOTTED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?(?:\s|(?=[A-Z]))")
PARA = re.compile(r"^para (\d{1,2}(?:\.\d{1,2})?)$")
CITABLE = re.compile(r"^(?:section|rule|para|schedule)\b", re.I)  # not annexures, letterheads ...
REFERENCE = re.compile(r"\b(?:sub-sections?|sub-rules?|sub-clauses?|clauses?|sections?|rules?|items?|paras?|"
                       r"paragraphs?|of|in|under|to|with|by)\s*$", re.I)
SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z(])")
SENTENCE_STOP = re.compile(r"[.;:—–-]\s*$")  # a line that ends like this ends a sentence or an opening

LETTERS = list("abcdefghijklmnopqrstuvwxyz")
LETTER_ORDER = LETTERS + ["z" + c for c in LETTERS]
ROMAN_ORDER = [t + u for t in ("", "x", "xx") for u in ("", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix")][1:]


@dataclass
class Piece:
    location: str             # its citation: "section 129(3)-(5)"
    lines: list[str]          # its own text; put back in order, a unit's pieces give the unit
    repeated: list[str] = field(default_factory=list)  # opening words and overlap, for context only

    @property
    def text(self) -> str:
        return "\n".join(self.repeated + self.lines)


@dataclass
class Level:
    split: object         # lines, location -> (lines before the first number, [(location, short label, lines)])
    repeat_head: bool     # do the pieces after the first repeat those opening lines?


def tokens(lines: list[str]) -> int:
    return count_tokens("\n".join(lines))


def group(lines: list[str], starts: list[tuple[int, str, str]]) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """Cut the lines at each start, given as (line number, location, short label)."""
    if not starts:
        return lines, []
    ends = [s[0] for s in starts[1:]] + [len(lines)]
    return lines[:starts[0][0]], [(loc, short, lines[k:end]) for (k, loc, short), end in zip(starts, ends)]


def by_subsection(lines: list[str], location: str):
    starts, last = [], (0, "")
    inline = next((k for k, line in enumerate(lines[:HEAD_LINES]) if FIRST_INLINE.search(line)), None)
    if inline is not None:
        starts.append((inline, f"{location}(1)", "(1)"))
        last = (1, "")
    for k, line in enumerate(lines):
        m = SUBSECTION.match(line)
        if not m or (k and REFERENCE.search(lines[k - 1])):
            continue
        key = (int(m.group(1)), m.group(2))
        if key > last and key[0] <= last[0] + GAP:
            short = f"({key[0]}{key[1]})"
            starts.append((k, location + short, short))
            last = key
    return group(lines, starts)


def by_clause(lines: list[str], location: str):
    starts, order, pos = [], None, -1
    for k, line in enumerate(lines):
        m = CLAUSE.match(line)
        if not m or (k and REFERENCE.search(lines[k - 1])):
            continue
        label = m.group(1)
        if order is None:
            if label not in ("a", "b", "i"):
                continue
            order = ROMAN_ORDER if label == "i" else LETTER_ORDER
        if label in order[pos + 1:pos + 3]:
            pos = order.index(label, pos + 1)
            starts.append((k, f"{location}({label})", f"({label})"))
    return group(lines, starts)


def by_dotted(lines: list[str], location: str):
    """Sub-paragraphs: "2.2.4" inside "para 2.2". Their number must start with the para's own."""
    para = PARA.match(location)
    if not para:
        return lines, []
    starts, last = [], ()
    for k, line in enumerate(lines):
        m = DOTTED.match(line)
        if m and m.group(1).startswith(para.group(1) + "."):
            key = tuple(map(int, m.group(1).split(".")))
            if key > last:
                starts.append((k, f"para {m.group(1)}", m.group(1)))
                last = key
    return group(lines, starts)


LEVELS = [Level(by_dotted, False), Level(by_subsection, False), Level(by_clause, True)]


def join_small(parts: list[tuple[str, str, list[str]]], room: int) -> list[tuple[str, list[str]]]:
    """Parts under SMALL tokens join a neighbour if the two fit -> [(location, lines)]."""
    out: list[list] = []  # [location, last short label, lines, joined?]
    for loc, short, lines in parts:
        if out and (tokens(lines) < SMALL or tokens(out[-1][2]) < SMALL) \
                and tokens(out[-1][2] + lines) <= room:
            out[-1][1:] = [short, out[-1][2] + lines, True]
        else:
            out.append([loc, short, lines, False])
    return [(f"{loc}-{short}" if joined else loc, lines) for loc, short, lines, joined in out]


def by_lines(lines: list[str], location: str, room: int, lead: list[str]) -> list[Piece]:
    """The last resort: as many whole sentences as fit. A printed line ends anywhere, so cutting
    there would cut mid-sentence. A sentence too long (a form has no full stops) goes by line, then by word."""
    if tokens(lead) > room // 2:
        lead = []
    room -= tokens(lead) if lead else 0

    bits: list[str] = []
    for sentence in SENTENCE_END.split("\n".join(lines)):
        if count_tokens(sentence) <= room:
            bits.append(sentence)
            continue
        for line in sentence.split("\n"):
            if count_tokens(line) <= room:
                bits.append(line)
            else:  # no line end in reach: whatever fits, word by word
                now: list[str] = []
                for word in line.split():
                    if now and count_tokens(" ".join(now + [word])) > room:
                        bits.append(" ".join(now))
                        now = []
                    now.append(word)
                bits.append(" ".join(now))

    pieces, now = [], []
    for bit in bits:
        if now and tokens(now + [bit]) > room:
            pieces.append(now)
            now = []
        now.append(bit)
    pieces.append(now)
    return [Piece(location, p, list(lead)) for p in pieces]


def cut_lines(lines: list[str], location: str, room: int, lead: list[str], levels: list[Level]) -> list[Piece]:
    if tokens(lead + lines) <= room:
        return [Piece(location, lines, list(lead))]
    for i, level in enumerate(levels):
        head, parts = level.split(lines, location)
        if len(parts) < 2:
            continue
        repeat = head if level.repeat_head and head and tokens(head) <= LEAD_MAX else []
        # The first part carries the opening lines as its own text, so nothing is lost.
        parts[0] = (parts[0][0], parts[0][1], head + parts[0][2])
        out: list[Piece] = []
        joined = join_small(parts, room - tokens(lead + repeat))
        if level.repeat_head and head:  # opening words + first clause: the parent's citation is the honest one
            joined[0] = (location, joined[0][1])
        for k, (loc, part) in enumerate(joined):
            part_lead = lead + (repeat if k else [])
            out += cut_lines(part, loc, room, part_lead, levels[i + 1:])
        return out
    return by_lines(lines, location, room, lead)


def add_overlap(pieces: list[Piece], room: int) -> None:
    """Repeat the end of the piece before, up to OVERLAP, only where there's space, and always from
    a sentence's start: a repeated half-sentence reads like part of this piece's own law."""
    for before, piece in zip(pieces, pieces[1:]):
        space = min(OVERLAP, room - count_tokens(piece.text))
        tail: list[str] = []
        for line in reversed(before.lines):
            if tokens([line] + tail) > space:
                break
            tail.insert(0, line)
        if tail and len(tail) < len(before.lines) and not SENTENCE_STOP.search(before.lines[-len(tail) - 1]):
            parts = SENTENCE_END.split("\n".join(tail), maxsplit=1)  # the first line starts mid-sentence
            tail = [parts[1]] if len(parts) > 1 else []
        piece.repeated = piece.repeated + tail


def cut(text: str, location: str, reserve: int = 0) -> list[Piece]:
    """One unit's text -> its pieces. `reserve`: tokens kept free for the context header (B4)."""
    room = MAX_TOKENS - reserve
    levels = LEVELS if CITABLE.match(location) else []  # a form's "(2)" is no citation
    pieces = cut_lines(text.split("\n"), location, room, [], levels)
    if len(pieces) > 1:
        add_overlap(pieces, room)
    return pieces
