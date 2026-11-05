"""Split every document in docs/manifest.jsonl into units, then chunk them (to-do-list.md, A6, B).

Each file goes to the splitter for its doc_type (src/taxowl/splitting/run.py) and its units are
saved to data/units/<file>.jsonl (+ <file>.tables.jsonl). Its units and tables then become chunks
(src/taxowl/chunking/run.py), all saved to data/chunks.jsonl. Then a summary: files, units, tables
and chunks per doc_type, the files with warnings, the files whose self-check failed, the chunk
checks, and the files the extractor hasn't read yet.

Usage:
    uv run scripts/03_split_chunk.py
"""

import json
import sys
from collections import Counter, defaultdict

from taxowl.chunking import run as chunking
from taxowl.config import CHUNKS, INGESTED, MANIFEST, ROOT
from taxowl.splitting.run import save, split_file


def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    count = defaultdict(Counter)  # doc_type -> files / units / tables
    warned, failed, missing = {}, {}, []
    chunks, lost = [], []
    for row in map(json.loads, MANIFEST.open()):
        f, t = row["file"], row["doc_type"]
        if not (INGESTED / f"{f}.json").exists():
            missing.append(f)
            continue
        result = split_file(f, t)
        save(f, result)
        made, problems = chunking.chunk_file(row, result.units, result.tables)
        chunks += made
        lost += problems
        count[t].update(files=1, units=len(result.units), tables=len(result.tables), chunks=len(made))
        if result.warnings:
            warned[f] = result.warnings
        if result.problems:
            failed[f] = result.problems

    chunking.save(chunks)

    print(f"{'doc_type':<15}{'files':>7}{'units':>8}{'tables':>8}{'chunks':>8}")
    for t, c in sorted(count.items()):
        print(f"{t:<15}{c['files']:>7}{c['units']:>8}{c['tables']:>8}{c['chunks']:>8}")
    total = sum(count.values(), Counter())
    print(f"{'all':<15}{total['files']:>7}{total['units']:>8}{total['tables']:>8}{total['chunks']:>8}")

    print(f"\nfiles with warnings: {len(warned)} of {total['files']}")
    for f, ws in warned.items():
        print(f"  {f}: {'; '.join(ws)[:160]}")
    if missing:
        print(f"\n{red}not extracted yet{reset} ({len(missing)}): {missing[:5]}")
    print(f"\nself-check: {green}all passed{reset}" if not failed else f"\nself-check failed in {len(failed)} files:")
    for f, problems in failed.items():
        print(f"  {red}{f}{reset}: {problems}")

    sizes = sorted(c.token_count for c in chunks)
    kinds = Counter(c.kind for c in chunks)
    print(f"\n{len(chunks)} chunks ({kinds['text']} text, {kinds['table']} table): median {sizes[len(sizes) // 2]} "
          f"tokens, p90 {sizes[int(.9 * len(sizes))]}, longest {sizes[-1]}. Saved: {CHUNKS.relative_to(ROOT)}")
    checks = chunking.check_chunks(chunks)
    if lost:
        checks["text_lost"] = f"{len(lost)}: {lost[:3]}"
    print(f"chunk checks: {green}all passed{reset}" if not checks else f"{red}chunk checks failed{reset}: {checks}")


if __name__ == "__main__":
    main()
