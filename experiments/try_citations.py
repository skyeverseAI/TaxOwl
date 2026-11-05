"""Blind check of the citation reader against the question set ChatGPT wrote.

Prints the score and every question that failed. A fail can be the reader's mistake or a wrong answer
in the set, so each one needs a look.

Usage:
    uv run experiments/try_citations.py
    uv run experiments/try_citations.py eval_results/gold/citations_heldout.jsonl
"""

import json
import sys
from pathlib import Path

from taxowl.retrieval.citations import Citation, read_citations

GOLD = Path("eval_results/gold/citations_gold.jsonl")


def to_citation(row: dict) -> Citation:
    """One answer from the set, in the reader's own form so the two can be compared."""
    return Citation(row["kind"], row["number"], tuple(row["path"]), row["law"], row["law_assumed"])


def main() -> None:
    gold = Path(sys.argv[1]) if len(sys.argv) > 1 else GOLD
    if not gold.exists():
        raise SystemExit(f"{gold} not found. Save ChatGPT's output there first.")

    rows = [json.loads(line) for line in gold.read_text().splitlines() if line.strip()]
    failed = 0
    levels: dict[str, list[int]] = {}  # level -> [passed, total]; older sets have no levels
    for row in rows:
        expected = [to_citation(c) for c in row["expected"]]
        got = read_citations(row["question"])
        level = row.get("level")
        score = levels.setdefault(level, [0, 0]) if level else [0, 0]
        score[1] += 1
        if got == expected:
            score[0] += 1
        else:
            failed += 1
            print(f"\nFAIL{f' [{level}]' if level else ''}  {row['question']}")
            print(f"  expected: {expected}")
            print(f"  got:      {got}")
    print()
    for level, (passed, total) in levels.items():
        print(f"{level}: {passed} of {total}")
    print(f"{len(rows) - failed} of {len(rows)} passed")


if __name__ == "__main__":
    main()
