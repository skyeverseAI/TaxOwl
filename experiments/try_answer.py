"""Quick check by eye: answer test questions with both models and print everything.

Not the eval: these questions were drafted with ChatGPT / Codex, so they never join the test split.

Two question sets:
  default   the 10 try_search questions (expected source written as text)
  --file    a JSONL file such as eval_results/gold/answer_trial_questions.jsonl (Codex, 2026-11-07:
            5 each of easy, medium, hard, super hard, blunder). Each question then gets two more lines:
              source found   did the retriever bring an expected source? (retriever, not the model)
              refusal        did the model refuse exactly when it should have?

Usage (Ollama must be running for "local"):
    uv run experiments/try_answer.py                         10 questions, both models
    uv run experiments/try_answer.py cloud                   one model
    uv run experiments/try_answer.py cloud \
        --file eval_results/gold/answer_trial_questions.jsonl
    ... --level hard                                         only one level from the file
"""

import argparse
import json

from try_search import (
    QUESTIONS,  # same folder: the same 10 questions as the retriever check
)

from taxowl.answer.check import REFUSAL
from taxowl.answer.pipeline import answer


def load(path: str | None, level: str | None) -> list[dict]:
    """Every question as {id, question, expected, sources, must_refuse}."""
    if path is None:
        return [{"id": str(n), "question": q, "expected": e, "sources": None, "must_refuse": None}
                for n, (q, e) in enumerate(QUESTIONS, 1)]
    questions = []
    with open(path) as file:
        lines = file.readlines()
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        if level and r["level"] != level:
            continue
        expected = "; ".join(f"{s['doc_number']}, {s['location']}" for s in r["expected_sources"])
        if r["trap"]:
            expected = f"{expected or 'refuse'} (trap: {r['trap']})"
        questions.append({"id": r["id"], "question": r["question"], "expected": expected,
                          "sources": {(s["doc_number"], s["location"]) for s in r["expected_sources"]},
                          "must_refuse": r["must_refuse"]})
    return questions


def show(result: dict, q: dict, score: dict) -> None:
    print(f"\n--- {result['model']}   expected: {q['expected']}")
    print(result["answer"])
    print()
    for s in result["sources"]:
        print(f"   [S{s['number']}] {s['label']}")
    failed = [c for c in result["checks"] if not c["passed"]]
    print("   checks: " + ("all passed" if not failed else
                          "; ".join(f"FAIL {c['name']}: {c['why']}" for c in failed)))

    if q["sources"] is not None:  # only questions from a --file have these
        if q["sources"]:
            found = {(s["doc_number"], s["location"]) for s in result["sources"]} & q["sources"]
            score["found"] += bool(found)
            print(f"   source found: {'yes' if found else 'NO'}")
        refused = result["answer"].strip().strip("*_\"' ") == REFUSAL
        right = refused == q["must_refuse"]
        score["refusal_ok"] += right
        print(f"   refusal: {'ok' if right else 'WRONG'} (refused={refused}, should={q['must_refuse']})")
    print(f"   {result['seconds']} s, {result['input_tokens']} in / {result['output_tokens']} out tokens, "
          f"₹{result['cost_inr']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=["cloud", "local"])
    parser.add_argument("--file", help="JSONL of questions, e.g. eval_results/gold/answer_trial_questions.jsonl")
    parser.add_argument("--level", help="only this level: easy, medium, hard, super_hard, blunder")
    args = parser.parse_args()

    questions = load(args.file, args.level)
    with_source = sum(bool(q["sources"]) for q in questions)
    totals = {m: {"seconds": 0.0, "cost": 0.0, "failed": 0, "found": 0, "refusal_ok": 0} for m in args.models}
    for q in questions:
        print(f"\n\n========== {q['id']}. {q['question']}")
        for which in args.models:
            result = answer(q["question"], which)
            show(result, q, totals[which])
            totals[which]["seconds"] += result["seconds"]
            totals[which]["cost"] += result["cost_inr"]
            totals[which]["failed"] += any(not c["passed"] for c in result["checks"])

    n = len(questions)
    print("\n\n========== totals")
    for which, t in totals.items():
        line = (f"{which:6} {t['seconds'] / n:.1f} s per answer, ₹{t['cost']:.3f} in all, "
                f"{t['failed']}/{n} answers with a failed check")
        if args.file:
            line += f", source found {t['found']}/{with_source}, refusal right {t['refusal_ok']}/{n}"
        print(line)


if __name__ == "__main__":
    main()
