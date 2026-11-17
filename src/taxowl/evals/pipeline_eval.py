"""Pipeline eval: the WHOLE app on each question (retrieve + web + generate + our notes), scored on what
the user sees.

    uv run python -m taxowl.evals.pipeline_eval --gold eval_results/gold/generator_dev.jsonl --which cloud
    ... add --judge for DeepEval's scores (costs money, about ₹50 per run on the dev set)
    ... add --ids claude-029,codex-020 to run only those rows (cheap trial)

The difference from generator_eval.py is where the sources come from:

    generator eval:  GOLD chunks           -> model                     -> score   (only the model)
    pipeline eval:   retriever + web (app) -> model -> + our notes      -> score   (the whole app)

It calls pipeline.answer(), the same function the app's logic uses, so a change anywhere (retriever,
web, prompt, notes) shows up here.

Scores (same names as generator_eval.py, so the two tables can sit side by side):

  WHAT EACH ROW EXPECTS ("expects"):
    answer   the row has gold chunks
    web      a "none" row marked "expects": "web" in the gold: a GST rate our corpus doesn't have, but
             the app searches the web for exactly these, so it must answer AND cite a WEB [S#] (user's
             call, 2026-11-17: codex-034 earbuds, codex-038 3D printers). Marked in the gold, not taken
             from web.wants_web(): claude-037 (RoDTEP rate) also triggers the web search but isn't GST,
             so refusing it is right. No claims, so no Completeness; Faithfulness against the web text
             is what catches a weak or self-contradicting answer.
    refuse   any other "none" row

  by code, free, every row:
    refusal_correct  did the row get what it expects: refuse / answer / answer citing the web. Read from
                     the MODEL's text (model_text): our rate_note can follow a refusal, and is_refusal()
                     is an exact match.
    checks_failed    check.py's 5 rule checks, on the full text
    gold_found       answerable rows: did ANY gold chunk reach the model? (the retriever's hit, here)
    seconds, cost    the whole answer() call: retrieval + web + model

  by DeepEval's judge (--judge), "answer" and "web" rows the model did not refuse, on the FULL text the user
  reads (answer + rate_note / amended_note; the user's call, 2026-11-17: the notes are claims too):
    Faithfulness     full text -> supported by the sources the app actually used (PDF + web)?
    AnswerRelevancy  full text -> about the question?
    Completeness     GOLD claims -> said in the full text?

BLAME, per answerable row (needs --judge): which part to fix when the answer falls short.

                       complete (>= threshold)   incomplete or refused
    gold found              ok                    generator
    gold not found          ok (web / luck)       retriever
"""

import argparse
import time
from collections import Counter
from pathlib import Path

from taxowl.answer.check import cited_numbers, is_refusal
from taxowl.answer.pipeline import answer
from taxowl.config import ROOT, RUNS
from taxowl.evals.generator_eval import COMPLETENESS, config, judge, save, summarise
from taxowl.evals.generator_eval import show as show_table
from taxowl.evals.retriever_eval import JUDGE_MODEL, THRESHOLD, check_gold, load_gold, load_units


def run(gold_path: Path, which: str, use_judge: bool = False, judge_model: str = JUDGE_MODEL,
        ids: list[str] | None = None, out: Path | None = None) -> dict:
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
        expects = "answer" if answerable else row.get("expects", "refuse")
        reply = answer(row["question"], which)
        sources = reply["sources"]

        refused = is_refusal(reply["model_text"])
        found = [g for g in row["gold_chunks"] if g in {s["chunk_id"] for s in sources}]
        cites_web = any(s.get("web") and s["number"] in cited_numbers(reply["model_text"]) for s in sources)
        correct = {"answer": not refused, "refuse": refused, "web": not refused and cites_web}[expects]
        results.append({
            "id": row["id"], "category": row["category"], "question": row["question"],
            "answerable": answerable, "expects": expects, "refused": refused, "cites_web": cites_web,
            "refusal_correct": correct,
            "checks_failed": [c["name"] for c in reply["checks"] if not c["passed"]],
            "gold_found": bool(found) if answerable else None,
            "gold_found_ids": found, "gold_chunks": row["gold_chunks"],
            "answer": reply["answer"], "notes_added": reply["answer"] != reply["model_text"],
            "claims": row["claims"],
            "sources": [{"number": s["number"], "label": s["label"], "chunk_id": s["chunk_id"],
                         "web": bool(s.get("web"))} for s in sources],
            "seconds": reply["seconds"], "input_tokens": reply["input_tokens"],
            "output_tokens": reply["output_tokens"], "cost_inr": reply["cost_inr"],
        })
        if expects in ("answer", "web") and not refused:
            cases.append({"id": row["id"], "question": row["question"], "answer": reply["answer"],
                          "contexts": [f"[S{s['number']}] {s['label']}\n{s['text']}" for s in sources],
                          "claims": row["claims"]})
        extra = {"answer": ", gold found" if found else ", gold NOT found",
                 "web": ", cites web" if cites_web else ", NO web cited", "refuse": ""}[expects]
        print(f"  {i}/{len(rows)} {row['id']}: {'refused' if refused else 'answered'}{extra} ({reply['seconds']} s)")

    run_config = config(gold_path, which, use_judge, judge_model, ids)
    run_config["eval"] = "pipeline"
    if use_judge:
        if out:  # answers first, so a judge failure doesn't lose them (generator_eval.save)
            save({"config": run_config, "summary": summarise_all(results), "rows": results,
                  "judge_pending": True}, out)
        judged = judge(cases, judge_model) if cases else {}
        for result in results:
            if result["expects"] == "web" and not result["refused"]:
                result["judge"] = judged.get(result["id"], {})   # Faithfulness + Relevancy, no blame box
            if not result["answerable"]:
                continue
            if result["refused"]:  # as in generator_eval: a refusal has no claims to judge
                result["judge"] = {COMPLETENESS: {"score": 0.0, "reason": "refused (scored by code)", "cost": 0.0}}
            else:
                result["judge"] = judged.get(result["id"], {})
            result["blame"] = blame(result)

    return {"config": run_config, "summary": summarise_all(results), "rows": results}


def blame(result: dict) -> str | None:
    """'ok', 'generator' or 'retriever' (see the box in the docstring); None if the judge gave no score."""
    score = result.get("judge", {}).get(COMPLETENESS, {}).get("score")
    if score is None:
        return None
    if score >= THRESHOLD:
        return "ok"
    return "generator" if result["gold_found"] else "retriever"


def summarise_all(results: list[dict]) -> dict:
    """generator_eval's summary, plus gold_found and the blame counts per category."""
    summary = summarise(results)
    for name, line in summary.items():
        members = [r for r in results if name in ("ALL", r["category"]) and r["answerable"]]
        if members:
            line["gold_found"] = round(sum(r["gold_found"] for r in members) / len(members), 3)
        counts = Counter(r["blame"] for r in members if r.get("blame"))
        if counts:
            line["blame"] = dict(counts)
    return summary


def show(run_result: dict) -> None:
    """generator_eval's table and 'To look at' list, then gold found and the blame box."""
    show_table(run_result)
    summary = run_result["summary"]
    print(f"\n{'category':<10}{'gold found':>12}   blame (answerable rows)")
    for name in sorted(summary, key=lambda n: (n == "ALL", n)):
        line = summary[name]
        if "gold_found" in line:
            print(f"{name:<10}{line['gold_found']:>12.2f}   {line.get('blame', '-')}")

    # generator_eval's list says "answered a 'none' question" for any wrong "none" row; for web rows say why
    web_rows = [r for r in run_result["rows"] if r["expects"] == "web"]
    if web_rows:
        print("\nWeb (rate) rows: must answer and cite a WEB source")
        for r in web_rows:
            state = "ok" if r["refusal_correct"] else "refused" if r["refused"] else "answered, NO web [S#]"
            print(f"  {state:<22} {r['id']} {r['question'][:80]}")

    misses = [r for r in run_result["rows"] if r.get("blame") in ("generator", "retriever")]
    if misses:
        print("\nBlame:")
        for r in misses:
            print(f"  {r['blame']:<10} {r['id']} [{r['category']}] {r['question'][:80]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline eval: the whole app, scored on what the user sees")
    parser.add_argument("--gold", type=Path, required=True, help="e.g. eval_results/gold/generator_dev.jsonl")
    parser.add_argument("--which", choices=["cloud", "local"], default="cloud")
    parser.add_argument("--judge", action="store_true", help="also run DeepEval's judge (costs money)")
    parser.add_argument("--judge-model", default=JUDGE_MODEL, help="OpenRouter model name for the judge")
    parser.add_argument("--ids", help="comma-separated row ids to run only those, e.g. claude-029,codex-020")
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    out = RUNS / f"pipeline_{args.which}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    result = run(args.gold, args.which, args.judge, args.judge_model, ids, out)
    show(result)

    save(result, out)
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
