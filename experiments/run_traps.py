"""Validity step 4: the trap questions, through the whole answer pipeline.

Each trap asks about a circular whose law changed later (eval_results/gold/validity_traps.jsonl):
    dev-006, dev-018  rule 36(4): the circulars explain the 2019-2020 limit; the rule was changed in 2022
    dev-014           intermediary place of supply: the IGST provision the circular reads was changed later
    dev-029           drip irrigation rate: 12% in the 2021 circular, 5% from 22 Sep 2025

What a good answer does: answers from the circular AND says the law changed (from the Act/Rules
"as amended" sources, the WEB sources, the dates in the labels, or the rate note).
A person reads each answer and marks it; this script only collects them.

Prints each answer, its sources and failed checks; saves all to eval_results/runs/traps_<time>.json.
Costs a few rupees (one model call each, plus a web search for a rate question).

Run: uv run python experiments/run_traps.py
"""

import json
import re
from datetime import datetime

from taxowl.answer.pipeline import answer
from taxowl.config import GOLD, ROOT, RUNS

TRAPS = GOLD / "validity_traps.jsonl"


def main() -> None:
    rows = [json.loads(line) for line in TRAPS.open(encoding="utf-8")]
    results = []
    for row in rows:
        r = answer(row["question"])
        cited = {int(n) for n in re.findall(r"\[S(\d+)\]", r["answer"])}
        gold_found = [g for g in row["gold_chunks"] if any(s["chunk_id"] == g for s in r["sources"])]
        failed = [c["name"] for c in r["checks"] if not c["passed"]]
        results.append({"id": row["id"], "question": row["question"], "note": row["note"],
                        "trap_note": row.get("trap_note", ""), "answer": r["answer"],
                        "sources": [{k: s[k] for k in ("number", "label", "chunk_id", "url")} for s in r["sources"]],
                        "gold_found": gold_found, "failed_checks": failed, "cost_inr": r["cost_inr"],
                        "ok": "", "why": ""})   # filled in by the person reading

        print(f"\n{'=' * 100}\n{row['id']}  {row['question']}\n  circular: {row['note']}"
              f"{'   trap: ' + row['trap_note'] if row.get('trap_note') else ''}\n{'-' * 100}")
        print(r["answer"])
        print(f"{'-' * 100}\nsources (* = cited):")
        for s in r["sources"]:
            print(f"  {'*' if s['number'] in cited else ' '} [S{s['number']}] {s['label'][:110]}")
        print(f"gold chunk returned: {len(gold_found)}/{len(row['gold_chunks'])}   "
              f"failed checks: {failed or 'none'}   ₹{r['cost_inr']}")

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"traps_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}  (fill `ok` y/n and `why` for each)")


if __name__ == "__main__":
    main()
