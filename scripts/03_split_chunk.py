"""Split every document in docs/manifest.jsonl into units (to-do-list.md, A6; chunking joins here in B).

Each file goes to the splitter for its doc_type (src/taxowl/splitting/run.py) and its units are
saved to data/units/<file>.jsonl (+ <file>.tables.jsonl). Then a summary: files, units and
tables per doc_type, the files with warnings, the files whose self-check failed, and the files
the extractor hasn't read yet.

Usage:
    uv run scripts/03_split_chunk.py
"""

import json
import sys
from collections import Counter, defaultdict

from taxowl.config import INGESTED, MANIFEST
from taxowl.splitting.run import save, split_file


def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    count = defaultdict(Counter)  # doc_type -> files / units / tables
    warned, failed, missing = {}, {}, []
    for row in map(json.loads, MANIFEST.open()):
        f, t = row["file"], row["doc_type"]
        if not (INGESTED / f"{f}.json").exists():
            missing.append(f)
            continue
        result = split_file(f, t)
        save(f, result)
        count[t].update(files=1, units=len(result.units), tables=len(result.tables))
        if result.warnings:
            warned[f] = result.warnings
        if result.problems:
            failed[f] = result.problems

    print(f"{'doc_type':<15}{'files':>7}{'units':>8}{'tables':>8}")
    for t, c in sorted(count.items()):
        print(f"{t:<15}{c['files']:>7}{c['units']:>8}{c['tables']:>8}")
    total = sum(count.values(), Counter())
    print(f"{'all':<15}{total['files']:>7}{total['units']:>8}{total['tables']:>8}")

    print(f"\nfiles with warnings: {len(warned)} of {total['files']}")
    for f, ws in warned.items():
        print(f"  {f}: {'; '.join(ws)[:160]}")
    if missing:
        print(f"\n{red}not extracted yet{reset} ({len(missing)}): {missing[:5]}")
    print(f"\nself-check: {green}all passed{reset}" if not failed else f"\nself-check failed in {len(failed)} files:")
    for f, problems in failed.items():
        print(f"  {red}{f}{reset}: {problems}")


if __name__ == "__main__":
    main()
