"""Merge the two golden pools into one set of 60 questions, then split it 40 dev / 20 test.

    uv run eval_results/make_retriever_gold.py

Reads  eval_results/gold/pool_claude.jsonl and pool_codex.jsonl (40 rows each, already cross-checked:
       crosscheck_claude_by_codex.md, crosscheck_codex_by_claude.md)
Writes eval_results/gold/retriever_dev.jsonl (40) and retriever_test.jsonl (20),
       and adds Codex's stale rate row to validity_traps.jsonl.

Steps, in order:
  1. Last fixes from the cross-check (FIXES, MOVE_TO_TRAPS); Codex's "plain" becomes "scenario";
     Codex's ids dev-NNN become codex-NNN, so "dev" means only the split.
  2. Drop Codex's copies of questions Claude also wrote (DUPLICATES). Claude's copies are kept
     because their claims were completed in the cross-check.
  3. Pick TARGET rows per category at random (fixed SEED), so the 60 keep a balance of kinds.
  4. Split each category 2/3 dev, 1/3 test, at random with the same seed. Done before the retriever
     has seen any of these questions, so nobody can push the hard ones into dev or test.

Run it again and it gives the same files (same seed). Change SEED only for a reason, and say so.
"""

import json
import random
from collections import Counter

from taxowl.config import CHUNKS, GOLD

SEED = 2026
TARGET = {"exact": 13, "scenario": 20, "multi": 6, "hinglish": 9, "none": 12}  # 60 in all
TEST_SHARE = 1 / 3

# Codex rows that ask what a Claude row already asks (same source chunk, same situation)
DUPLICATES = {"dev-001": "claude-001", "dev-002": "claude-006", "dev-016": "claude-019",
              "dev-006": "claude-013", "dev-018": "claude-016"}
# Codex's dev-029 asks today's GST rate from a 2021 rate circular; rates changed in 2025
MOVE_TO_TRAPS = {"dev-029": "asks today's rate from Circular 155/11/2021; GST rates were revised in 2025"}
FIXES = {
    # dev-018's second claim came from a refund rule, not from the insurer circular
    "dev-018": lambda row: row.update(claims=row["claims"][:1]),
}


def load(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    claude = [{**row, "source": "claude"} for row in load(GOLD / "pool_claude.jsonl")]
    codex = load(GOLD / "pool_codex.jsonl")

    # 1. last fixes; stale row to the traps file (once)
    traps = load(GOLD / "validity_traps.jsonl")
    trap_ids = {row["id"] for row in traps}
    kept_codex = []
    for row in codex:
        if row["id"] in FIXES:
            FIXES[row["id"]](row)
        if row["id"] in MOVE_TO_TRAPS:
            if row["id"] not in trap_ids:
                traps.append({**row, "trap_note": MOVE_TO_TRAPS[row["id"]]})
            continue
        if row["id"] in DUPLICATES:  # 2. Claude's copy stays
            continue
        row = {k: v for k, v in row.items() if k != "split"}
        row.update(id=row["id"].replace("dev-", "codex-"), source="codex",
                   category="scenario" if row["category"] == "plain" else row["category"])
        kept_codex.append(row)
    save(GOLD / "validity_traps.jsonl", traps)

    pool = claude + kept_codex
    available = Counter(row["category"] for row in pool)
    print(f"pool after fixes and duplicates: {len(pool)} {dict(available)}")

    # 3 + 4. pick per category, then split per category
    rng = random.Random(SEED)
    dev, test = [], []
    for category, want in TARGET.items():
        rows = sorted((r for r in pool if r["category"] == category), key=lambda r: r["id"])
        if len(rows) < want:
            raise SystemExit(f"only {len(rows)} '{category}' rows, need {want}")
        picked = rng.sample(rows, want)
        n_test = round(want * TEST_SHARE)
        test += [{**r, "split": "test"} for r in picked[:n_test]]
        dev += [{**r, "split": "dev"} for r in picked[n_test:]]

    # checks: ids exist, no id twice
    with open(CHUNKS, encoding="utf-8") as f:
        ids = {json.loads(line)["chunk_id"] for line in f}
    missing = [(r["id"], g) for r in dev + test for g in r["gold_chunks"] if g not in ids]
    if missing:
        raise SystemExit(f"gold ids not in chunks: {missing}")
    assert len({r["id"] for r in dev + test}) == len(dev) + len(test)

    dev.sort(key=lambda r: (r["category"], r["id"]))
    test.sort(key=lambda r: (r["category"], r["id"]))
    save(GOLD / "retriever_dev.jsonl", dev)
    save(GOLD / "retriever_test.jsonl", test)
    for name, rows in (("dev", dev), ("test", test)):
        print(f"{name}: {len(rows)} {dict(Counter(r['category'] for r in rows))} "
              f"from {dict(Counter(r['source'] for r in rows))}")
    print(f"validity traps: {len(traps)}")


if __name__ == "__main__":
    main()
