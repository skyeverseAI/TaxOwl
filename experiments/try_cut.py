"""Try chunker.cut() on every unit: checks, the spread of sizes, and a few real examples to read.
Reads data/units/; every cut unit's pieces, in full, go to data/runs/cut_preview.txt for reading.
Tables and the real context header come in later steps, so the header's room here is an estimate
from the document's number, title and the unit's location.

Run: uv run python experiments/try_cut.py
"""

import json
import random
from collections import Counter

from taxowl.chunking.chunker import MAX_TOKENS, cut
from taxowl.config import MANIFEST, ROOT, UNITS
from taxowl.splitting import count_tokens

PREVIEW = ROOT / "data" / "runs" / "cut_preview.txt"

SHOW = ["act-12-of-2017:section-129", "instruction-no-03-2022-gst:para-2-2"]
RANDOM_EXAMPLES = 3
SEED = 2026


def load_units() -> list[dict]:
    units = []
    for path in sorted(UNITS.rglob("*.jsonl")):
        if not path.name.endswith(".tables.jsonl"):
            units += map(json.loads, path.open())
    return units


def squeeze(text: str) -> str:
    return " ".join(text.split())


def show(unit: dict, pieces: list) -> None:
    print(f"\n=== {unit['unit_id']} ({unit['token_count']} tokens) -> {len(pieces)} pieces")
    for p in pieces:
        print(f"  [{p.location}] {count_tokens(p.text)} tokens, repeated {count_tokens(' '.join(p.repeated))}")
        print(f"     starts: {p.lines[0][:90]!r}")
        print(f"     ends:   {p.lines[-1][-90:]!r}")


def save_preview(cut_units: list[str], results: dict) -> None:
    out = []
    for unit_id in cut_units:
        unit, pieces = results[unit_id]
        out.append(f"\n{'=' * 90}\n{unit_id} | {unit['doc_file']} | p.{unit['page_start']}-{unit['page_end']} | "
                   f"{unit['token_count']} tokens -> {len(pieces)} pieces")
        for k, p in enumerate(pieces, 1):
            out.append(f"\n--- piece {k} of {len(pieces)} | {p.location} | {count_tokens(p.text)} tokens")
            if p.repeated:
                out.append("[REPEATED FOR CONTEXT]\n" + "\n".join(p.repeated) + "\n[ITS OWN TEXT]")
            out.append("\n".join(p.lines))
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text("\n".join(out) + "\n")
    print(f"All cut units, in full: {PREVIEW.relative_to(ROOT)}")


def main() -> None:
    rows = {r["file"]: r for r in map(json.loads, MANIFEST.open())}
    units = load_units()
    sizes, too_long, lost, cut_units, same_citation = [], [], [], [], 0
    results = {}
    for u in units:
        row = rows[u["doc_file"]]
        reserve = count_tokens(f"{row['number']} — {row.get('title', '')} — {u['location']} {u['heading']}")
        pieces = cut(u["text"], u["location"], reserve)
        results[u["unit_id"]] = (u, pieces)
        if len(pieces) > 1:
            cut_units.append(u["unit_id"])
            same_citation += sum(p.location == u["location"] for p in pieces)
        for p in pieces:
            n = count_tokens(p.text)
            sizes.append(n)
            if n + reserve > MAX_TOKENS:
                too_long.append((u["unit_id"], p.location, n + reserve))
        if squeeze(" ".join(" ".join(p.lines) for p in pieces)) != squeeze(u["text"]):
            lost.append(u["unit_id"])

    sizes.sort()
    cut_pieces = sum(len(results[i][1]) for i in cut_units)
    print(f"{len(units)} units -> {len(sizes)} pieces; {len(cut_units)} units were cut into {cut_pieces} pieces")
    print(f"piece size: median {sizes[len(sizes) // 2]}, p90 {sizes[int(.9 * len(sizes))]}, longest {sizes[-1]}")
    print(f"cut pieces without a finer citation: {same_citation} of {cut_pieces}")
    print(f"over {MAX_TOKENS} with the header: {len(too_long)} {too_long[:5]}")
    print(f"text lost or changed: {len(lost)} {lost[:5]}")
    print("pieces per cut unit:", sorted(Counter(len(results[i][1]) for i in cut_units).items())[-5:])

    save_preview(cut_units, results)

    random.seed(SEED)
    for unit_id in SHOW + random.sample(cut_units, RANDOM_EXAMPLES):
        if unit_id in results:
            show(*results[unit_id])


if __name__ == "__main__":
    main()
