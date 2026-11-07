"""Check the lookup two ways.

1. Every section and rule chunk must be found by its own label, and by the far end of a range.
   Every circular must be found from its own number, read from a sentence by the citation reader.
2. The cases from the design, printed with what we want, so they can be read by eye.

Usage:
    uv run experiments/try_lookup.py
"""

from collections import Counter

from taxowl.retrieval.citations import Citation, read_citations
from taxowl.retrieval.lookup import LAW_DOCS, MAX_CHUNKS, get_store, load_index, lookup

MAX_SHOWN = 20  # failures printed by the first check

# (law, kind, number, path, the labels we want)
CASES = [
    ("CGST Act", "section", "16", ("4",), ["section 16(4)"]),
    ("CGST Act", "section", "76", ("5",), ["section 76(4)-(8)"]),
    ("CGST Act", "section", "17", ("5", "g"), ["section 17(5)(f)-(i)"]),
    ("CGST Act", "section", "17", ("5",), ["section 17(5)", "section 17(5)(b)-(c)", "section 17(5)(d)-(e)",
                                           "section 17(5)(f)-(i)"]),
    ("CGST Act", "section", "16", (), ["section 16(1)", "section 16(2)", "section 16(2)(b)-(c)", "section 16(2)(d)",
                                       "section 16(3)", "section 16(4)", "section 16(5)", "section 16(6)"]),
    ("CGST Act", "section", "16", ("2", "a"), ["section 16(2)"]),
    ("CGST Rules", "rule", "3", ("3A",), ["rule 3(3A)"]),
    ("IGST Rules", "rule", "3", ("3A",), []),
    ("CGST Act", "section", "999", (), []),
]


def check_every_chunk() -> None:
    """Build a citation from each chunk's own label: the lookup must return that chunk."""
    laws = {document: law for law, document in LAW_DOCS.items()}
    tried = failed = 0
    for (document, kind, number), entries in load_index().items():
        for entry in entries:
            label = entry.label
            paths = [label.path]
            if label.end:
                paths.append(label.path[:-1] + (label.end,))
            for path in paths:
                tried += 1
                found = lookup(Citation(kind, number, path, laws[document]), limit=None)
                if entry.document.id not in [d.id for d in found]:
                    failed += 1
                    if failed <= MAX_SHOWN:
                        print(f"  NOT FOUND  {document}, {entry.document.metadata['location']}, asked {kind} {number}{path}")
    print(f"Found by own label: {tried - failed} of {tried}\n")


def check_every_circular() -> None:
    """Each document in the store, asked for by its printed number: its chunks must come back."""
    numbers = {m["doc_number"] for m in get_store().get(where={"doc_type": "circular"}, include=["metadatas"])["metadatas"]}
    missed = []
    for number in sorted(numbers):
        found = [d for c in read_citations(f"What does Circular {number} say?") for d in lookup(c, limit=None)]
        if number not in {d.metadata["doc_number"] for d in found}:
            missed.append(number)
    print(f"Circulars found by their own number: {len(numbers) - len(missed)} of {len(numbers)}")
    for number in missed:
        print(f"  NOT FOUND  {number}")
    print()


def show_circulars() -> None:
    """Different ways of writing a number; each line shows which documents came back."""
    for question in ["Circular 6/6/2017", "Circular 147/3/2021", "Circular No. 76/50/2018-GST", "Circular 130/2019",
                     "138/08/2020-GST", "dated 12/10/2024", "Instruction 03/2022-GST", "Circular 999/1/2024"]:
        found = [d for c in read_citations(question) for d in lookup(c)]
        print(f"{question}: {dict(Counter(d.metadata['doc_number'][:50] for d in found))}")
    print()


def show_cases() -> None:
    """The design's cases: OK when the labels are exactly the ones we want."""
    for law, kind, number, path, wanted in CASES:
        got = [d.metadata["location"] for d in lookup(Citation(kind, number, path, law))]
        print(f"{'OK  ' if got == wanted else 'DIFF'}  {law}, {kind} {number}{path}")
        print(f"      got: {got}")
        if got != wanted:
            print(f"      want: {wanted}")

    many = lookup(Citation("section", "2", (), "CGST Act"))
    print(f"\nCGST Act, section 2: {len(many)} chunks returned (limit {MAX_CHUNKS})")


def main() -> None:
    check_every_chunk()
    check_every_circular()
    show_circulars()
    show_cases()


if __name__ == "__main__":
    main()
