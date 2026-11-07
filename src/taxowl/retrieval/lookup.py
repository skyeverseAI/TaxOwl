"""Citation -> the chunks of the law that hold it, found by their location labels, not by meaning.

    section 16(4)     -> the chunk labelled section 16(4)
    section 76(5)     -> section 76(4)-(8), as the label's range covers it
    section 17(5)     -> section 17(5), 17(5)(b)-(c) and the rest under it
    section 16(2)(a)  -> section 16(2), as (a) has no label of its own but is in that chunk's text
    IGST rule 3(3A)   -> nothing: better no exact hit than some other rule's text
    circular 6/6/2017 -> 06/06/2017-CGST, then any corrigendum to it

Chroma's filters only match whole values, so reading a range or a number is our own code.

Check it: uv run experiments/try_lookup.py
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.documents import Document

from taxowl.retrieval.citations import Citation
from taxowl.retrieval.store import get_store

MAX_CHUNKS = 10  # a first guess: section 2 alone is over 100 chunks. To settle with the test questions

LAW_DOCS = {
    "CGST Act": "Act 12 of 2017",
    "IGST Act": "IGST Act, 2017",
    "UTGST Act": "UTGST Act, 2017",
    "Compensation Act": "GST (Compensation to States) Act, 2017",
    "CGST Rules": "CGST Rules, 2017",
    "IGST Rules": "IGST Rules, 2017",
}
LOCATION = re.compile(r"(section|rule) (\d+[A-Za-z]*)((?:\([^()]+\))*)(?:-\(([^()]+)\))?")
PART = re.compile(r"\(([^()]+)\)")
DIGIT_PART = re.compile(r"(\d+)([A-Za-z]*)")
ROMAN_PART = re.compile(r"[ivxlc]+")
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
DOC_NUMBER = re.compile(r"\d+(?:/\d+)+")  # the first in "Corrigendum to Circular No. 76/50/2018-GST"
DIGITS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Label:
    kind: str                # "section" or "rule"
    number: str              # "76"
    path: tuple[str, ...]    # "section 76(4)-(8)" -> ("4",); the last part is the start of any range
    end: str | None = None   # "8"


@dataclass(frozen=True)
class Entry:
    label: Label
    document: Document


def read_location(location: str) -> Label | None:
    """'section 17(5)(f)-(i)' -> Label("section", "17", ("5", "f"), "i"); a Schedule or preamble -> None."""
    match = LOCATION.fullmatch(location)
    if not match:
        return None
    return Label(match[1], match[2], tuple(PART.findall(match[3])), match[4])


def roman_value(part: str) -> int | None:
    """'iv' -> 4; a part with other letters -> None."""
    if not ROMAN_PART.fullmatch(part):
        return None
    values = [ROMAN[letter] for letter in part]
    return sum(-v if v < after else v for v, after in zip(values, values[1:] + [0]))


def in_range(part: str, start: str, end: str) -> bool:
    """Is (5) in (4)-(8), (3A) in (3)-(4), (g) in (f)-(i), (iii) in (ii)-(iv)?"""
    digits = [DIGIT_PART.fullmatch(p) for p in (part, start, end)]
    if all(digits):
        low, middle, high = ((int(m[1]), m[2].upper()) for m in (digits[1], digits[0], digits[2]))
        return low <= middle <= high
    if any(digits):
        return False
    # Letters in order: a to z, then aa. (i)-(l) means i, j, k, l.
    if (len(start), start) <= (len(part), part) <= (len(end), end):
        return True
    # Roman numbers read as letters are out of order, so (ii)-(iv) needs its own test.
    low, middle, high = roman_value(start), roman_value(part), roman_value(end)
    return None not in (low, middle, high) and low <= middle <= high


def holds(label: Label, path: tuple[str, ...]) -> bool:
    """Is this label at the path, or under it? Label 17(5)(f)-(i) holds (5), (5)(g) and (); not (6)."""
    if len(label.path) < len(path):
        return False
    for i, part in enumerate(path):
        if label.end and i == len(label.path) - 1:
            if not in_range(part, label.path[i], label.end):
                return False
        elif part != label.path[i]:
            return False
    return True


def text_has_parts(document: Document, parts: tuple[str, ...]) -> bool:
    """Does the law's text, leaving out the chunk's header line, show each '(a)'?"""
    body = document.page_content.split("\n", 1)[-1]
    return all(f"({part})" in body for part in parts)


def chunk_order(document: Document) -> tuple[bool, int, str]:
    """A section's text in order, then its tables. Ids of cut units end in the chunk's place (':5');
    a unit left whole has no number, and is the only chunk of its unit."""
    place = document.id.rsplit(":", 1)[1]
    return document.metadata["kind"] == "table", int(place) if place.isdigit() else 0, document.id


@lru_cache(maxsize=1)
def load_index() -> dict[tuple[str, str, str], list[Entry]]:
    """Every section and rule chunk in the store, by (document, kind, number), each in order. Read once."""
    data = get_store().get(where={"doc_type": {"$in": ["act", "rules"]}})
    documents = [Document(page_content=text, metadata=metadata, id=chunk_id) for chunk_id, text, metadata
                 in zip(data["ids"], data["documents"], data["metadatas"])]
    index: dict[tuple[str, str, str], list[Entry]] = {}
    for document in sorted(documents, key=chunk_order):
        label = read_location(document.metadata["location"])
        if label:
            key = (document.metadata["doc_number"], label.kind, label.number)
            index.setdefault(key, []).append(Entry(label, document))
    return index


def number_parts(text: str) -> tuple[int, ...]:
    """'06/06/2017-CGST' and '6/6/2017' -> (6, 6, 2017); no number -> ()."""
    match = DOC_NUMBER.search(text)
    return tuple(int(part) for part in match.group().split("/")) if match else ()


def reading_order(document: Document) -> tuple:
    """By page, then by id with its numbers read as numbers, so para-2 comes before para-10."""
    pieces = DIGITS.split(document.id)
    return document.metadata["page_start"], [int(p) if p.isdigit() else p for p in pieces]


@lru_cache(maxsize=1)
def load_circulars() -> dict[tuple[int, ...], list[Document]]:
    """Every circular chunk by its number's parts, in reading order. A corrigendum sits under the
    number of the circular it corrects. Read once."""
    data = get_store().get(where={"doc_type": "circular"})
    documents = [Document(page_content=text, metadata=metadata, id=chunk_id) for chunk_id, text, metadata
                 in zip(data["ids"], data["documents"], data["metadatas"])]
    index: dict[tuple[int, ...], list[Document]] = {}
    for document in sorted(documents, key=reading_order):
        parts = number_parts(document.metadata["doc_number"])
        if parts:
            index.setdefault(parts, []).append(document)
    return index


def lookup_circular(citation: Citation, limit: int | None) -> list[Document]:
    """The circular up to `limit`, then its corrigenda whole: a long circular mustn't cut its correction."""
    documents = load_circulars().get(number_parts(citation.number), [])
    is_correction = lambda d: "corrigendum" in d.metadata["doc_number"].lower()
    original = [d for d in documents if not is_correction(d)]
    corrections = [d for d in documents if is_correction(d)]
    return original[:limit] + corrections


def lookup(citation: Citation, limit: int | None = MAX_CHUNKS) -> list[Document]:
    """The chunks holding this citation, in order, up to `limit`. None found -> an empty list."""
    if citation.kind == "circular":
        return lookup_circular(citation, limit)
    entries = load_index().get((LAW_DOCS.get(citation.law), citation.kind, citation.number), [])
    path = citation.path
    hits = [e.document for e in entries if holds(e.label, path)]

    # No label this deep: try the nearest parent, only if its text really has the part asked for.
    for depth in range(len(path) - 1, -1, -1):
        if hits:
            break
        hits = [e.document for e in entries
                if len(e.label.path) == depth and holds(e.label, path[:depth])
                and text_has_parts(e.document, path[depth:])]
    return hits[:limit]
