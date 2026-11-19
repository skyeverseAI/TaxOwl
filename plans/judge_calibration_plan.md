# Judge calibration (v1, step 4 of the deploy order)

**Question:** the dev numbers (Faithfulness, Completeness) come from an LLM judge (DeepEval, gpt-4.1-mini).
How often is the judge right?

**How** (`src/taxowl/evals/judge_calibration.py`, no new app answers, the saved run
`eval_results/runs/pipeline_cloud_20261118_030606.json`):

1. `pick`: 18 judged rows: all 11 scored below 1.0 (where a too-harsh judge shows) + 7 random rows
   scored 1.0 (where a too-lenient judge hides). Web rows left out: their page text wasn't saved.
   Written out blind (`blind.jsonl`), the judge's scores kept apart (`judge.json`).
2. Claude and Codex each labelled every row blind: faithful y/n, complete y/n
   (`labels_claude.jsonl`, `labels_codex.jsonl`).
3. `compare`: where Claude, Codex and the judge all agree, that is the truth (20 of 36 labels).
   The other 16 went to `decide.jsonl`; the user decided the 2 hard ones (claude-005 faithful,
   claude-019 complete, both "n"), the other 14 follow Claude's reading of the sources, each with a reason.
4. `rejudge`: the same answers judged by gpt-4.1, scored against the same truth.

A judge score counts as "y" at the eval's pass mark, 0.7.

## Results (2026-11-19)

| metric | gpt-4.1-mini (our judge) | gpt-4.1 | Claude | Codex |
|---|---|---|---|---|
| Faithfulness | 13/18 | 14/18 | 17/18 | 14/18 |
| Completeness | 12/18 | 12/18 | 17/18 | 17/18 |

- **The judge is lenient.** Of its 11 misses, 10 passed a wrong or incomplete answer; 1 failed a right one
  (codex-004: it misread IGST s.12(8)). Often its reason names the gap, but the score stays above 0.7
  (one wrong statement out of seven is 0.86). Pass marks of 0.9 and 1.0 didn't help (12-14/18).
- **A bigger judge didn't fix it.** gpt-4.1 passed all 18 rows on Faithfulness (DeepEval's own summary:
  passed=18), so it caught none of the 4 unfaithful answers; its 14/18 is just the 14 right ones. It fixed
  codex-004 only and made the same lenient misses, so the
  limit is in how the metrics score (a fraction of claims), not the model's size. The judge stays
  gpt-4.1-mini (cheaper, same result).
- **So:** the judge's dev scores are an upper bound. The quality page says so, with these numbers.

## Read with care

- 11 of the 18 rows were picked BECAUSE the judge scored them low: this is the judge on hard rows,
  not its average over the dev set.
- Claude's 17/18 is inflated: 14 of the 16 decided labels follow Claude's reading. For the same
  reason no Claude model was tried as a judge: it would agree with itself.
- 18 rows is small; one row moves a number by ~6 points.

## Later (v1.1)

- A stricter judge: a G-Eval style rubric ("any statement the sources don't support = fail",
  "a missing condition = incomplete") in place of the claim fraction, re-checked with this same set.
