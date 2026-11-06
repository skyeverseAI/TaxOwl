"""Check the lookup two ways.

1. Every section and rule chunk must be found by its own label, and by the far end of a range.
2. The cases from the design, printed with what we want, so they can be read by eye.

Usage:
    uv run experiments/try_lookup.py
"""

from taxowl.retrieval.citations import Citation
from taxowl.retrieval.lookup import LAW_DOCS, MAX_CHUNKS, load_index, lookup

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
    show_cases()


if __name__ == "__main__":
    main()
