"""Retriever eval: ask every golden question, compare the chunks that come back with the right ones.

    uv run python -m taxowl.evals.retriever_eval --gold eval_results/gold/retriever_dev.jsonl --mode full
    uv run python -m taxowl.evals.retriever_eval --gold eval_results/gold/retriever_dev.jsonl --mode meaning
    ... add --judge for DeepEval's scores too (costs money, a few rupees per run)

Two kinds of score, kept side by side so we can study how they differ:

  by id, no LLM (free, the same every run):
    hit@5        any right chunk in the top 5? The headline: one right chunk is often enough to answer.
    recall@5     the share of the right chunks in the top 5 (matters when the answer is spread out)
    MRR          1 / the rank of the first right chunk (1st -> 1.0, 2nd -> 0.5, missing -> 0)
    hit@all      any right chunk anywhere in what came back? In full mode up to 25 chunks come back and
                 the answer step gets all of them, so a right chunk at rank 7 fails hit@5 but passes this.
    section hit@5, section MRR   the same, but a chunk counts as right if it's from the right section,
                 rule or para (its unit_id), and each section takes one place in the ranking.
                 A big gap from the chunk scores = the retriever reaches the right place, not the right piece.

  by claims, with DeepEval's judge (--judge):
    ContextualRecall     is each claim of the right answer somewhere in the retrieved text?
                         Catches a different chunk that says the same thing, which id scores count as a miss.
    ContextualPrecision  are the useful chunks ranked above the useless ones?

Modes:
    full     the whole LawRetriever: exact chunks for named citations first, then 5 by meaning.
             What the answer step gets, so this is the real score.
    meaning  the vector search alone (top 10). Exact lookup fixes many questions whatever the embedding is,
             so only this mode shows the embedding's own skill. For comparing embedding models (R8).

Questions in category "none" have no gold, so they're skipped here; they test refusal in the answer eval.

Shape like evals_project/evals/evals_retriever.py: load goldens -> run the retriever -> metrics -> summary.
Differs: the id scores need no judge, so they run free on every change, and the judge is a flag. run()
still takes the retriever as an argument, so a reranker or another embedding can be passed in later.
"""

import argparse
import hashlib
import json
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

from langchain_core.documents import Document

from taxowl.config import CHUNKS, ROOT, RUNS
from taxowl.evals.metrics import hit_at_k, recall_at_k, reciprocal_rank
from taxowl.retrieval.retriever import EXACT_CHUNKS, MEANING_CHUNKS, PER_CITATION, make_retriever
from taxowl.retrieval.store import COLLECTION, count, get_store
from taxowl.tokens import EMBEDDER

K = 5                                # the cut-off for hit@k and recall@k
TOP = 10                             # meaning mode fetches this many; runs save this many ids per question
JUDGE_MODEL = "openai/gpt-4.1-mini"  # OpenRouter's name; the same judge as evals_project
THRESHOLD = 0.7                      # DeepEval's pass mark, kept from evals_project


# ---------------------------------------------------------------- the golden set

def load_gold(path: Path) -> list[dict]:
    """One question per line: id, category, question, gold_chunks, claims, note."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_units() -> dict[str, str]:
    """chunk_id -> unit_id (its section, rule or para), for the section-level scores."""
    with open(CHUNKS, encoding="utf-8") as f:
        return {c["chunk_id"]: c["unit_id"] for c in map(json.loads, f)}


def check_gold(rows: list[dict], units: dict[str, str]) -> None:
    """Stop if a gold id isn't in data/chunks.jsonl. After a splitter or chunker change, ids can move;
    then a stale id would look like a retrieval miss. Better no score than a wrong one."""
    missing = [(row["id"], gold) for row in rows for gold in row["gold_chunks"] if gold not in units]
    if missing:
        for row_id, gold in missing:
            print(f"  {row_id}: {gold}")
        raise SystemExit(f"{len(missing)} gold chunk ids are not in {CHUNKS}. Fix the golden set first.")


def file_hash(path: Path) -> str:
    """The golden file's fingerprint, saved with every run: a changed test set shows up at once."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- scoring one question

def in_sections(ids: list[str], units: dict[str, str]) -> list[str]:
    """Ranked chunk ids -> ranked sections, each section listed once, at its best place.
    [s17:5, s17:7, rule37:1] -> [section-17, rule-37]: a section with three chunks takes one place."""
    seen, ranked = set(), []
    for chunk_id in ids:
        unit = units.get(chunk_id, chunk_id)
        if unit not in seen:
            seen.add(unit)
            ranked.append(unit)
    return ranked


def score(row: dict, ids: list[str], units: dict[str, str]) -> dict:
    """The id scores for one question. `rank` is where the first right chunk came (None = not returned)."""
    gold = set(row["gold_chunks"])
    gold_sections = {units[g] for g in gold}
    sections = in_sections(ids, units)
    rank = next((i for i, chunk_id in enumerate(ids, 1) if chunk_id in gold), None)
    return {
        "hit@5": hit_at_k(ids, gold, K),
        "hit@all": hit_at_k(ids, gold, len(ids)),
        "recall@5": recall_at_k(ids, gold, K),
        "mrr": reciprocal_rank(ids, gold),
        "section_hit@5": hit_at_k(sections, gold_sections, K),
        "section_mrr": reciprocal_rank(sections, gold_sections),
        "rank": rank,
    }


# ---------------------------------------------------------------- the judge (optional)

def judge(cases: list[tuple[dict, list[Document]]]) -> dict[str, dict]:
    """DeepEval's ContextualRecall + ContextualPrecision for each question -> {row id: {metric: score}}.
    The claims, joined, are the expected answer. The judge sees what the answer step would see."""
    from deepeval import evaluate  # imported here: the id scores must run even without deepeval
    from deepeval.metrics import ContextualPrecisionMetric, ContextualRecallMetric
    from deepeval.models import OpenRouterModel
    from deepeval.test_case import LLMTestCase

    from taxowl.ingestion.vlm import load_key  # taxowl's one way to read the OpenRouter key

    model = OpenRouterModel(model=JUDGE_MODEL, api_key=load_key(), temperature=0)
    test_cases = [
        LLMTestCase(input=row["question"],
                    actual_output="(generator not evaluated in this run)",
                    expected_output=" ".join(row["claims"]),
                    retrieval_context=[document.page_content for document in documents])
        for row, documents in cases
    ]
    metrics = [ContextualRecallMetric(threshold=THRESHOLD, model=model, include_reason=True),
               ContextualPrecisionMetric(threshold=THRESHOLD, model=model, include_reason=True)]
    result = evaluate(test_cases=test_cases, metrics=metrics)

    by_question = {row["question"]: row["id"] for row, _ in cases}
    scores: dict[str, dict] = {}
    for test in result.test_results:  # DeepEval may reorder them, so match by the question text
        scores[by_question[test.input]] = {m.name: {"score": m.score, "reason": m.reason}
                                           for m in test.metrics_data}
    return scores


# ---------------------------------------------------------------- the run

def run(retriever, gold_path: Path, mode: str, use_judge: bool = False) -> dict:
    """Ask every question with gold, score it, and return the whole run (config, rows, summary)."""
    rows = load_gold(gold_path)
    units = load_units()
    check_gold(rows, units)

    results, cases = [], []
    for row in rows:
        if not row["gold_chunks"]:  # "none" questions: nothing to find
            continue
        start = time.perf_counter()
        documents = retriever.invoke(row["question"])
        seconds = time.perf_counter() - start
        ids = [document.id for document in documents]  # store ids are chunk ids (store.py)
        results.append({"id": row["id"], "category": row["category"], "question": row["question"],
                        "gold": row["gold_chunks"], "top": ids[:TOP], "returned": len(ids),
                        "seconds": round(seconds, 3), **score(row, ids, units)})
        # the judge sees what the answer step would get: everything in full mode, the top 5 by meaning
        cases.append((row, documents if mode == "full" else documents[:MEANING_CHUNKS]))

    if use_judge:
        judged = judge(cases)
        for result in results:
            result["judge"] = judged.get(result["id"], {})

    return {"config": config(gold_path, mode, use_judge), "summary": summarise(results), "rows": results}


def summarise(results: list[dict]) -> dict:
    """Averages per category and overall. Judge scores are averaged too when present."""
    groups = defaultdict(list)
    for result in results:
        groups[result["category"]].append(result)
        groups["ALL"].append(result)
    keys = ["hit@5", "hit@all", "recall@5", "mrr", "section_hit@5", "section_mrr"]
    summary = {}
    for name, members in groups.items():
        line = {"n": len(members), **{key: round(mean(m[key] for m in members), 3) for key in keys}}
        for metric in {metric for m in members for metric in m.get("judge", {})}:
            values = [m["judge"][metric]["score"] for m in members
                      if m.get("judge", {}).get(metric, {}).get("score") is not None]
            if values:
                line[metric] = round(mean(values), 3)
        summary[name] = line
    return summary


def config(gold_path: Path, mode: str, use_judge: bool) -> dict:
    """What was measured, saved with the scores: two runs are comparable only if these match."""
    store = get_store()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    return {"mode": mode, "k": K, "embedding_model": EMBEDDER, "collection": COLLECTION,
            "chunks_in_store": count(store),
            "ef_search": store._collection.configuration_json["hnsw"]["ef_search"],
            "meaning_chunks": MEANING_CHUNKS,
            "exact_chunks": EXACT_CHUNKS, "per_citation": PER_CITATION,
            "gold_file": str(gold_path), "gold_sha256": file_hash(gold_path),
            "judge_model": JUDGE_MODEL if use_judge else None, "git_commit": commit,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def show(run_result: dict) -> None:
    """A table per category, then every miss with what came back instead."""
    summary = run_result["summary"]
    judge_cols = sorted({k for line in summary.values() for k in line} -
                        {"n", "hit@5", "hit@all", "recall@5", "mrr", "section_hit@5", "section_mrr"})
    head = f"{'category':<10}{'n':>4}{'hit@5':>8}{'hit@all':>9}{'rec@5':>8}{'MRR':>7}{'sec hit@5':>11}{'sec MRR':>9}"
    print("\n" + head + "".join(f"{c[:18]:>20}" for c in judge_cols))
    for name in sorted(summary, key=lambda n: (n == "ALL", n)):
        line = summary[name]
        print(f"{name:<10}{line['n']:>4}{line['hit@5']:>8.2f}{line['hit@all']:>9.2f}{line['recall@5']:>8.2f}{line['mrr']:>7.2f}"
              f"{line['section_hit@5']:>11.2f}{line['section_mrr']:>9.2f}"
              + "".join(f"{line.get(c, float('nan')):>20.2f}" for c in judge_cols))

    misses = [r for r in run_result["rows"] if not r["hit@5"]]
    print(f"\nMisses at 5: {len(misses)}")
    for r in misses:
        where = f"first right chunk at rank {r['rank']}" if r["rank"] else "right chunk not returned"
        print(f"\n  {r['id']} [{r['category']}] {r['question'][:100]}")
        print(f"    gold: {', '.join(r['gold'])}   ({where}, {r['returned']} returned)")
        print(f"    top 5: {', '.join(r['top'][:5])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retriever eval: hit@5, recall@5, MRR (+ DeepEval with --judge)")
    parser.add_argument("--gold", type=Path, required=True, help="golden set, e.g. eval_results/gold/retriever_dev.jsonl")
    parser.add_argument("--mode", choices=["full", "meaning"], default="full")
    parser.add_argument("--judge", action="store_true", help="also run DeepEval's judge (costs money)")
    args = parser.parse_args()

    if args.mode == "full":
        retriever = make_retriever()
    else:  # LangChain's plain vector-store retriever: no exact lookup
        retriever = get_store().as_retriever(search_kwargs={"k": TOP})

    result = run(retriever, args.gold, args.mode, args.judge)
    show(result)

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"retriever_{args.mode}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
