"""Judge calibration: how far can we trust the DeepEval judge's scores (gpt-4.1-mini)?

Step 1 (this file now): pick ~20 judged rows from a SAVED pipeline run (no re-run, no cost) and write
them out BLIND, without the judge's scores, for labelling:

    uv run python -m taxowl.evals.judge_calibration pick \
      --run eval_results/runs/pipeline_cloud_20261118_030606.json

    eval_results/calibration/blind.jsonl    one row per line: question, answer, sources (full text),
                                            gold claims, and empty labels to fill:
                                              faithful  "y" / "n"  every statement backed by the sources?
                                              complete  "y" / "n"  every gold claim said in the answer?
                                              why       one line
    eval_results/calibration/judge.json     the judge's scores for the same rows, kept apart (the key)

Which rows: the judge can be wrong two ways, so both kinds are taken.
    too harsh    a right answer scored low  -> every row scored below 1.0 on Faithfulness or Completeness
    too lenient  a wrong answer scored 1.0  -> a random few of the rows scored 1.0 on both (fixed seed)
Web rows (codex-034, codex-038) are left out: the run didn't save the web pages' text, so they can't
be labelled against what the judge saw.

Labels: Claude and Codex each label blind; where they and the judge disagree, the user decides.
A judge score counts as "y" at THRESHOLD (0.7), the eval's own pass mark.

Step 2: put the three side by side.

    uv run python -m taxowl.evals.judge_calibration compare

    Where Claude, Codex and the judge all agree, that label is the truth. Every other (row, metric)
    goes to eval_results/calibration/decide.jsonl with all three labels and reasons, and an empty
    "truth" for the user to fill ("y" / "n"). Run compare again once they're filled: it prints how
    often the judge matched the truth, per metric (and Claude and Codex too, for comparison).
    decide.jsonl is never overwritten once it exists, so the user's answers are safe.

Step 3 (optional): would a bigger judge do better? Judge the same saved answers again with another
model, then score it against the SAME truth (judge.json + decide.jsonl stay what the truth was built from):

    uv run python -m taxowl.evals.judge_calibration rejudge --model openai/gpt-4.1
    uv run python -m taxowl.evals.judge_calibration compare \
      --judge eval_results/calibration/judge_gpt-4.1.json

Not a Claude model: most of the truth came from Claude's labels, so a Claude judge would agree with
itself, not show it judges better.
"""

import argparse
import json
import random
from pathlib import Path

from taxowl.config import CHUNKS, ROOT
from taxowl.evals.retriever_eval import THRESHOLD

OUT = ROOT / "eval_results" / "calibration"
METRICS = {"faithful": "Faithfulness", "complete": "Completeness"}
SEED = 2026
PERFECT_SAMPLE = 7   # rows scored 1.0 on both, to look for a too-lenient judge


def score(row: dict, metric: str) -> float | None:
    return row.get("judge", {}).get(metric, {}).get("score")


def pick(run_path: Path) -> list[dict]:
    rows = json.loads(run_path.read_text())["rows"]
    judged = [r for r in rows if r.get("judge") and not any(s["web"] for s in r["sources"])]
    low = [r for r in judged if any((score(r, m) or 1.0) < 1.0 for m in METRICS.values())]
    perfect = [r for r in judged if r not in low]
    sample = random.Random(SEED).sample(perfect, min(PERFECT_SAMPLE, len(perfect)))
    chosen = {r["id"] for r in low + sample}
    return [r for r in rows if r["id"] in chosen]   # in the run's order, so low and perfect are mixed


def write(rows: list[dict]) -> None:
    texts = {}
    for line in CHUNKS.read_text().splitlines():
        chunk = json.loads(line)
        texts[chunk["chunk_id"]] = chunk["text"]

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "blind.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            blind = {
                "id": r["id"], "question": r["question"], "answer": r["answer"],
                "sources": [f"[S{s['number']}] {s['label']}\n{texts[s['chunk_id']]}" for s in r["sources"]],
                "claims": r["claims"],
                "faithful": "", "complete": "" if r["claims"] else "-", "why": "",
            }
            f.write(json.dumps(blind, ensure_ascii=False) + "\n")

    write_key({r["id"]: r["judge"] for r in rows}, OUT / "judge.json")


def write_key(judged: dict, path: Path) -> None:
    """{id: {metric name: {"score", "reason"}}} -> the calibration's key file (faithful / complete)."""
    key = {rid: {label: {"score": scores.get(metric, {}).get("score"),
                         "reason": scores.get(metric, {}).get("reason")}
                 for label, metric in METRICS.items()} for rid, scores in judged.items()}
    path.write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")


def rejudge(model: str) -> Path:
    """The saved answers in blind.jsonl, judged again by `model`, with the same judge() the evals use
    (the same sources text and claims it was first given)."""
    from taxowl.evals.generator_eval import judge
    cases = [{"id": r["id"], "question": r["question"], "answer": r["answer"],
              "contexts": r["sources"], "claims": r["claims"]}
             for r in read_jsonl(OUT / "blind.jsonl").values()]
    out = OUT / f"judge_{model.split('/')[-1]}.json"
    write_key(judge(cases, model), out)
    return out


def read_jsonl(path: Path) -> dict:
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines()) if r}


def compare(other_judges: list[Path] = ()) -> None:
    claude, codex = read_jsonl(OUT / "labels_claude.jsonl"), read_jsonl(OUT / "labels_codex.jsonl")
    judge = json.loads((OUT / "judge.json").read_text())
    blind = read_jsonl(OUT / "blind.jsonl")

    table, to_decide = [], []   # table: one entry per (row, metric) with a label from all three
    for rid, key in judge.items():
        for label in METRICS:
            if claude[rid][label] == "-":   # no gold claims: nothing to check for completeness
                continue
            j = "y" if key[label]["score"] >= THRESHOLD else "n"
            entry = {"id": rid, "metric": label, "claude": claude[rid][label], "codex": codex[rid][label],
                     "judge": j, "judge_score": key[label]["score"]}
            table.append(entry)
            if len({entry["claude"], entry["codex"], j}) > 1:
                to_decide.append({**entry, "question": blind[rid]["question"],
                                  "claude_why": claude[rid]["why"], "codex_why": codex[rid]["why"],
                                  "judge_why": key[label]["reason"], "truth": ""})

    decide_path = OUT / "decide.jsonl"
    if not decide_path.exists():
        decide_path.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in to_decide),
                               encoding="utf-8")
        print(f"{len(table)} labels, all three agree on {len(table) - len(to_decide)}.")
        print(f"Wrote {decide_path.relative_to(ROOT)}: {len(to_decide)} to decide. Fill \"truth\" (y/n), "
              f"then run compare again.")
        return

    decided = {(d["id"], d["metric"]): d["truth"] for d in map(json.loads, decide_path.read_text().splitlines())}
    if any(t not in ("y", "n") for t in decided.values()):
        raise SystemExit(f"Some rows in {decide_path.relative_to(ROOT)} have no truth (y/n) yet.")

    others = {}   # more judges to score against the same truth: column name -> key file
    for path in other_judges:
        other = json.loads(path.read_text())
        name = path.stem.removeprefix("judge_")
        for e in table:
            e[name] = "y" if other[e["id"]][e["metric"]]["score"] >= THRESHOLD else "n"
        others[name] = other
    who_all = ["judge", *others, "claude", "codex"]

    print(f"{'metric':<14}" + "".join(f"{w[:12]:>14}" for w in who_all) + "   (matched the truth, out of)")
    for label, metric in METRICS.items():
        rows = [e for e in table if e["metric"] == label]
        truth = [decided.get((e["id"], label), e["judge"]) for e in rows]   # not in decide = all agreed
        hits = {who: sum(e[who] == t for e, t in zip(rows, truth)) for who in who_all}
        print(f"{metric:<14}" + "".join(f"{f'{hits[w]}/{len(rows)}':>14}" for w in who_all))
    misses = [(e["id"], e["metric"]) for e in table if decided.get((e["id"], e["metric"]), e["judge"]) != e["judge"]]
    print("\nJudge wrong on:", ", ".join(f"{i} ({m})" for i, m in misses) or "none")
    for name in others:
        wrong = [(e["id"], e["metric"]) for e in table if decided.get((e["id"], e["metric"]), e["judge"]) != e[name]]
        print(f"{name} wrong on:", ", ".join(f"{i} ({m})" for i, m in wrong) or "none")


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge calibration")
    sub = parser.add_subparsers(dest="step", required=True)
    p = sub.add_parser("pick", help="choose the rows and write them out blind")
    p.add_argument("--run", type=Path, required=True, help="a saved pipeline run judged with --judge")
    c = sub.add_parser("compare", help="Claude vs Codex vs the judge; the user decides the disagreements")
    c.add_argument("--judge", type=Path, action="append", default=[],
                   help="another judge's key file (from rejudge) to score against the same truth")
    r = sub.add_parser("rejudge", help="judge the same saved answers with another model")
    r.add_argument("--model", required=True, help="OpenRouter name, e.g. openai/gpt-4.1")
    args = parser.parse_args()

    if args.step == "pick":
        rows = pick(args.run)
        write(rows)
        low = sum(any((score(r, m) or 1.0) < 1.0 for m in METRICS.values()) for r in rows)
        print(f"{len(rows)} rows: {low} scored below 1.0, {len(rows) - low} scored 1.0 (judge pass mark {THRESHOLD})")
        print(f"Wrote {(OUT / 'blind.jsonl').relative_to(ROOT)} (to label) and "
              f"{(OUT / 'judge.json').relative_to(ROOT)} (the judge's scores, don't open before labelling)")
    elif args.step == "compare":
        compare(args.judge)
    elif args.step == "rejudge":
        out = rejudge(args.model)
        print(f"Wrote {out.relative_to(ROOT)}. Now: compare --judge {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
