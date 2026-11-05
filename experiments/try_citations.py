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
    for row in rows:
        expected = [to_citation(c) for c in row["expected"]]
        got = read_citations(row["question"])
        if got != expected:
            failed += 1
            print(f"\nFAIL  {row['question']}")
            print(f"  expected: {expected}")
            print(f"  got:      {got}")
    print(f"\n{len(rows) - failed} of {len(rows)} passed")


if __name__ == "__main__":
    main()
