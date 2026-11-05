"""Try chunking.tables.cut_table() on every table: checks, sizes, and a file to read.
Reads data/units/; every table's pieces go to data/runs/table_preview.txt.

Run: uv run python experiments/try_tables.py
"""

import json
import re

from taxowl.chunking.chunker import MAX_TOKENS
from taxowl.chunking.tables import clean_cell, cut_table, is_column_numbers
from taxowl.config import MANIFEST, ROOT, UNITS
from taxowl.splitting import count_tokens

PREVIEW = ROOT / "data" / "runs" / "table_preview.txt"


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def main() -> None:
    rows = {r["file"]: r for r in map(json.loads, MANIFEST.open())}
    units = {}
    tables = []
    for path in sorted(UNITS.rglob("*.jsonl")):
        if path.name.endswith(".tables.jsonl"):
            tables += map(json.loads, path.open())
        else:
            for line in path.open():
                u = json.loads(line)
                units[u["unit_id"]] = u

    preview, sizes, over, lost, no_data, one_piece = [], [], [], [], [], 0
    pieces_total = 0
    for t in tables:
        unit = units[t["unit_id"]]
        row = rows[unit["doc_file"]]
        reserve = count_tokens(f"{row['number']} — {row.get('title', '')} — {unit['location']} table")
        pieces = cut_table(t, reserve)
        pieces_total += len(pieces)
        if not pieces:
            no_data.append(t["table_id"])
        one_piece += len(pieces) == 1

        for p in pieces:
            n = count_tokens(p.text)
            sizes.append(n)
            if n + reserve > MAX_TOKENS:
                over.append((t["table_id"], p.first_row, n + reserve))
        said = words(" ".join(p.text for p in pieces))
        kept = [clean_cell(c) for r in t["rows"] if not is_column_numbers([clean_cell(c) for c in r]) for c in r]
        missing = words(" ".join(kept)) - said
        if missing:
            lost.append((t["table_id"], sorted(missing)[:5]))

        preview.append(f"\n{'=' * 90}\n{t['table_id']} | {unit['doc_file']} | p.{t['pages']} | belongs to "
                       f"{unit['location']} | {len(t['rows'])} rows -> {len(pieces)} pieces")
        for k, p in enumerate(pieces, 1):
            preview.append(f"\n--- piece {k} of {len(pieces)} | rows {p.first_row}-{p.last_row} | "
                           f"{count_tokens(p.text)} tokens\n{p.text}")

    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text("\n".join(preview) + "\n")

    sizes.sort()
    print(f"{len(tables)} tables -> {pieces_total} pieces; {one_piece} tables are one piece")
    print(f"piece size: median {sizes[len(sizes) // 2]}, p90 {sizes[int(.9 * len(sizes))]}, longest {sizes[-1]}")
    print(f"over {MAX_TOKENS} with the header: {len(over)} {over[:5]}")
    print(f"words lost: {len(lost)} {lost[:5]}")
    print(f"tables with no data: {len(no_data)} {no_data[:5]}")
    print(f"To read: {PREVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
