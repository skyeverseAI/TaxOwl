"""Generator eval: give the model the RIGHT chunks, and score only what it writes.

    uv run python -m taxowl.evals.generator_eval --gold eval_results/gold/retriever_dev.jsonl --which cloud
    ... add --judge for DeepEval's scores (costs money, about ₹50 per run on the dev set)
    ... add --ids claude-003,codex-034 to run only those rows (cheap trial)

ISOLATION (as in evals_project/evals/eval_generator.py): answerable questions get their GOLD chunks,
not the retriever's. The context is known to be right, so a low score is the generator's fault.

Two kinds of score:

  by code, free, every row (40):
    refusal_correct  "none" question -> must refuse; answerable question -> must NOT refuse (over-refusal)
    checks_failed    how many of check.py's 5 rule checks failed (made-up [S#], invented citation, ...)

  by DeepEval's judge (--judge), answerable rows the model did not refuse:
    Faithfulness     answer's claims -> supported by the sources?     (made anything up?)
    AnswerRelevancy  answer's statements -> about the question?       (off-topic padding?)
    Completeness     GOLD claims -> said in the answer?               (left anything out?)
                     DeepEval has no metric by this name. ContextualRecall does the same check
                     ("is each expected sentence supported by this text?"), so we pass the ANSWER as
                     its text. The retriever eval used the same metric with the chunks as the text.

  An answerable question the model refused gets completeness 0 by code and no judge call: a refusal
  has no claims, so the judge would score it 1.0 on faithfulness and hide the miss.

"none" questions have no gold chunks, so they get the retriever's chunks: near the topic but without
the answer, which tempts the model to stretch. No web search here (that is the pipeline eval's job),
and none of the notes our code adds under an answer (rate_note, amended_note): only the model is scored.

Shape like retriever_eval.py: load gold -> run -> metrics -> summary -> JSON in eval_results/runs/.
judge() takes plain cases (question, answer, source texts, claims), so the pipeline eval can import it
and only change where the chunks come from.
"""

import argparse
import json
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

from taxowl.answer.check import check, is_refusal
from taxowl.answer.generator import CLOUD_MODEL, LOCAL_MODEL, generate
from taxowl.answer.pipeline import BUDGET, as_text, assumed, get_retriever, pick, to_sources
from taxowl.config import ROOT, RUNS
from taxowl.evals.retriever_eval import JUDGE_MODEL, THRESHOLD, check_gold, file_hash, load_gold, load_units
from taxowl.retrieval.store import get_store

COMPLETENESS = "Completeness"   # our name for ContextualRecall run on the answer


# ---------------------------------------------------------------- the sources

def gold_sources(row: dict, which: str) -> list[dict]:
    """The gold chunks, fetched from the store and labelled as the app labels them."""
    found = {doc.id: doc for doc in get_store().get_by_ids(row["gold_chunks"])}
    docs = [found[chunk_id] for chunk_id in row["gold_chunks"]]  # keep the gold order
    return to_sources(pick(docs, BUDGET[which]))


def retrieved_sources(row: dict, which: str) -> list[dict]:
    """For "none" rows: what the retriever brings back (no web)."""
    return to_sources(pick(get_retriever().invoke(row["question"]), BUDGET[which]))


# ---------------------------------------------------------------- the judge (optional)

def judge(cases: list[dict], judge_model: str = JUDGE_MODEL) -> dict[str, dict]:
    """cases: [{"id", "question", "answer", "contexts": [source text, ...], "claims": [...]}]
    -> {id: {metric name: {"score", "reason", "cost"}}}. Reused by the pipeline eval."""
    from deepeval import evaluate  # imported here: the free scores must run even without deepeval
    from deepeval.metrics import AnswerRelevancyMetric, ContextualRecallMetric, FaithfulnessMetric
    from deepeval.models import OpenRouterModel
    from deepeval.test_case import LLMTestCase

    from taxowl.ingestion.vlm import load_key

    model = OpenRouterModel(model=judge_model, api_key=load_key(), temperature=0)
    options = dict(threshold=THRESHOLD, model=model, include_reason=True)
    by_question = {case["question"]: case["id"] for case in cases}
    scores: dict[str, dict] = defaultdict(dict)

    def keep(result, rename: str | None = None):
        for test in result.test_results:  # DeepEval may reorder them, so match by the question text
            for m in test.metrics_data:
                scores[by_question[test.input]][rename or m.name] = {
                    "score": m.score, "reason": m.reason, "cost": m.evaluation_cost}

    # Faithfulness + AnswerRelevancy: the answer against the sources and the question
    keep(evaluate(test_cases=[
        LLMTestCase(input=c["question"], actual_output=c["answer"], retrieval_context=c["contexts"])
        for c in cases], metrics=[FaithfulnessMetric(**options), AnswerRelevancyMetric(**options)]))

    # Completeness: the gold claims against the ANSWER (the answer is passed as the "retrieved" text)
    keep(evaluate(test_cases=[
        LLMTestCase(input=c["question"], actual_output=c["answer"],
                    expected_output=" ".join(c["claims"]), retrieval_context=[c["answer"]])
        for c in cases], metrics=[ContextualRecallMetric(**options)]), rename=COMPLETENESS)
    return dict(scores)


# ---------------------------------------------------------------- the run

def run(gold_path: Path, which: str, use_judge: bool = False, judge_model: str = JUDGE_MODEL,
        ids: list[str] | None = None) -> dict:
    rows = load_gold(gold_path)
    check_gold(rows, load_units())
    if ids:
        unknown = set(ids) - {row["id"] for row in rows}
        if unknown:
            raise SystemExit(f"ids not in {gold_path}: {sorted(unknown)}")
        rows = [row for row in rows if row["id"] in ids]

    results, cases = [], []
    for i, row in enumerate(rows, 1):
        answerable = bool(row["gold_chunks"])
        sources = gold_sources(row, which) if answerable else retrieved_sources(row, which)

        start = time.perf_counter()
        reply = generate(row["question"], as_text(sources), which, assumed(sources))
        seconds = time.perf_counter() - start

        refused = is_refusal(reply["text"])
        checks = check(reply["text"], sources, row["question"])
        results.append({
            "id": row["id"], "category": row["category"], "question": row["question"],
            "answerable": answerable, "refused": refused,
            "refusal_correct": refused != answerable,  # refuse exactly when it can't be answered
            "checks_failed": [c["name"] for c in checks if not c["passed"]],
            "answer": reply["text"], "claims": row["claims"],
            "sources": [{"number": s["number"], "label": s["label"], "chunk_id": s["chunk_id"]} for s in sources],
            "seconds": round(seconds, 1), "input_tokens": reply["input_tokens"],
            "output_tokens": reply["output_tokens"], "cost_inr": reply["cost_inr"],
        })
        if answerable and not refused:
            cases.append({"id": row["id"], "question": row["question"], "answer": reply["text"],
                          "contexts": [f"[S{s['number']}] {s['label']}\n{s['text']}" for s in sources],
                          "claims": row["claims"]})
        print(f"  {i}/{len(rows)} {row['id']}: {'refused' if refused else 'answered'} ({seconds:.1f} s)")

    if use_judge:
        judged = judge(cases, judge_model) if cases else {}
        for result in results:
            if not result["answerable"]:
                continue
            if result["refused"]:  # see the docstring: a refusal has no claims to judge
                result["judge"] = {COMPLETENESS: {"score": 0.0, "reason": "refused (scored by code)", "cost": 0.0}}
            else:
                result["judge"] = judged.get(result["id"], {})

    return {"config": config(gold_path, which, use_judge, judge_model, ids),
            "summary": summarise(results), "rows": results}


def summarise(results: list[dict]) -> dict:
    """Per category and overall. Judge scores are averaged over the rows that have them."""
    groups = defaultdict(list)
    for result in results:
        groups[result["category"]].append(result)
        groups["ALL"].append(result)
    summary = {}
    for name, members in groups.items():
        line = {"n": len(members),
                "refusal_correct": round(mean(m["refusal_correct"] for m in members), 3),
                "checks_failed": sum(len(m["checks_failed"]) for m in members),
                "seconds": round(mean(m["seconds"] for m in members), 1),
                "cost_inr": round(sum(m["cost_inr"] for m in members), 2)}
        for metric in sorted({metric for m in members for metric in m.get("judge", {})}):
            values = [m["judge"][metric]["score"] for m in members
                      if m.get("judge", {}).get(metric, {}).get("score") is not None]
            if values:
                line[metric] = round(mean(values), 3)
        line["judge_cost_usd"] = round(sum(v.get("cost") or 0 for m in members
                                           for v in m.get("judge", {}).values()), 4)
        summary[name] = line
    return summary


def config(gold_path: Path, which: str, use_judge: bool, judge_model: str, ids: list[str] | None) -> dict:
    """What was measured, saved with the scores: two runs are comparable only if these match."""
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    return {"which": which, "generator_model": CLOUD_MODEL if which == "cloud" else LOCAL_MODEL,
            "budget_tokens": BUDGET[which], "gold_file": str(gold_path), "gold_sha256": file_hash(gold_path),
            "only_ids": ids, "judge_model": judge_model if use_judge else None, "threshold": THRESHOLD,
            "git_commit": commit, "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def show(run_result: dict) -> None:
    """A table per category, then every wrong refusal, failed check and low judge score."""
    summary = run_result["summary"]
    judge_cols = [c for c in ("Faithfulness", "Answer Relevancy", COMPLETENESS)
                  if any(c in line for line in summary.values())]
    print(f"\n{'category':<10}{'n':>4}{'refusal ok':>12}{'checks failed':>15}{'sec':>6}{'₹':>7}"
          + "".join(f"{c[:16]:>18}" for c in judge_cols))
    for name in sorted(summary, key=lambda n: (n == "ALL", n)):
        line = summary[name]
        print(f"{name:<10}{line['n']:>4}{line['refusal_correct']:>12.2f}{line['checks_failed']:>15}"
              f"{line['seconds']:>6}{line['cost_inr']:>7.2f}"
              + "".join(f"{line[c]:>18.2f}" if c in line else f"{'-':>18}" for c in judge_cols))
    if judge_cols:
        print(f"\njudge cost: ${summary['ALL']['judge_cost_usd']}")

    print("\nTo look at:")
    for r in run_result["rows"]:
        problems = []
        if not r["refusal_correct"]:
            problems.append("refused an answerable question" if r["answerable"] else "answered a 'none' question")
        if r["checks_failed"]:
            problems.append("checks failed: " + ", ".join(r["checks_failed"]))
        for metric, v in r.get("judge", {}).items():
            if v["score"] is not None and v["score"] < THRESHOLD:
                problems.append(f"{metric} {v['score']:.2f}: {(v['reason'] or '')[:160]}")
        if problems:
            print(f"\n  {r['id']} [{r['category']}] {r['question'][:90]}")
            for p in problems:
                print(f"    - {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generator eval: gold chunks in, answer scored")
    parser.add_argument("--gold", type=Path, required=True, help="e.g. eval_results/gold/retriever_dev.jsonl")
    parser.add_argument("--which", choices=["cloud", "local"], default="cloud")
    parser.add_argument("--judge", action="store_true", help="also run DeepEval's judge (costs money)")
    parser.add_argument("--judge-model", default=JUDGE_MODEL, help="OpenRouter model name for the judge")
    parser.add_argument("--ids", help="comma-separated row ids to run only those, e.g. claude-003,codex-034")
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    result = run(args.gold, args.which, args.judge, args.judge_model, ids)
    show(result)

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"generator_{args.which}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
