"""B1: how long are the units? The answer decides the chunk size (to-do-list.md, section B).

Prints the length spread per document group, then the longest and the tiniest units.
Reads data/units/ only; changes nothing. token_count is already on every unit (splitting.finish()).

Run: uv run python experiments/measure_units.py
"""

import json
from collections import defaultdict

from taxowl.config import MANIFEST, UNITS

BGE_LIMIT = 510    # bge reads 512, and 2 of those go to its own [CLS] and [SEP] markers
BUCKETS = [100, 256, 400, BGE_LIMIT]  # the upper ends of the length groups printed below
TINY = 20          # under this many tokens a unit may be too short to find on its own
SHOW = 15          # how many of the longest and the tiniest to list


def load_units() -> list[dict]:
    """Every unit in data/units/; tables have their own files and are measured in B5."""
    units = []
    for path in sorted(UNITS.rglob("*.jsonl")):
        if not path.name.endswith(".tables.jsonl"):
            units += map(json.loads, path.open())
    return units


def group_of(unit: dict, doc_types: dict[str, str]) -> str:
    """The doc_type; the ICAI book holds several laws, so its units go by law ("igst-rules-2017")."""
    doc_type = doc_types[unit["doc_file"]]
    return unit["unit_id"].split(":")[0] if doc_type == "rules" else doc_type


def spread_row(name: str, sizes: list[int]) -> str:
    sizes = sorted(sizes)
    at = lambda share: sizes[int(share * (len(sizes) - 1))]
    over = sum(s > BGE_LIMIT for s in sizes)
    return (f"{name:<28}{len(sizes):>6}{at(.5):>8}{at(.9):>7}{at(.99):>7}{sizes[-1]:>8}"
            f"{over:>7}{over / len(sizes):>7.1%}")


def main() -> None:
    doc_types = {r["file"]: r["doc_type"] for r in map(json.loads, MANIFEST.open())}
    units = load_units()

    groups = defaultdict(list)
    for u in units:
        groups[group_of(u, doc_types)].append(u["token_count"])
    all_sizes = [u["token_count"] for u in units]

    print(f"{'group':<28}{'units':>6}{'median':>8}{'p90':>7}{'p99':>7}{'longest':>8}"
          f"{'over':>7}{'share':>7}")
    for name in sorted(groups):
        print(spread_row(name, groups[name]))
    print(spread_row("ALL", all_sizes))

    print(f"\nLength groups (tokens), all {len(units)} units:")
    low = 0
    for high in BUCKETS:
        n = sum(low < s <= high for s in all_sizes)
        print(f"  {low + 1:>5}-{high:<6}{n:>6}  {n / len(units):>6.1%}")
        low = high
    n = sum(s > low for s in all_sizes)
    print(f"  {'over ' + str(low):<12}{n:>6}  {n / len(units):>6.1%}")
    empty = sum(s == 0 for s in all_sizes)
    print(f"  empty       {empty:>6}")

    print(f"\nLongest {SHOW}:")
    for u in sorted(units, key=lambda u: -u["token_count"])[:SHOW]:
        print(f"  {u['token_count']:>6}  {u['unit_id']}")

    tiny = sorted((u for u in units if u["token_count"] < TINY), key=lambda u: u["token_count"])
    print(f"\nUnder {TINY} tokens: {len(tiny)} units. The first {SHOW}, with their text:")
    for u in tiny[:SHOW]:
        print(f"  {u['token_count']:>6}  {u['unit_id']}  |  {u['text'][:70]!r}")


if __name__ == "__main__":
    main()
