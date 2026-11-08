# Retriever eval — judge comparison

**Date:** 2026-11-08 · **Goal:** pick the LLM judge for DeepEval's ContextualRecall and ContextualPrecision.
**Question set:** 8 rows of `eval_results/gold/retriever_dev.jsonl`, chosen to cover every category and both misses:
`claude-005, codex-007, claude-026, claude-021, codex-012, codex-020, codex-019, claude-033`.
The retriever was the same in every run (Improvement 1 setup, `ef_search` 500), so the top 10 lists were the same too. Only the judge changed.

## What the two judge scores mean

- **Contextual Recall:** the expected answer is split into sentences, and each sentence is checked: is it supported by the retrieved chunks? Score = the share that is supported.
- **Contextual Precision:** each retrieved chunk is marked useful or not, and useful chunks ranked higher score more. Score near 1 = the useful chunks are at the top.

Unlike hit@5, these scores don't need gold chunk ids. They also give credit when a *different* chunk says the same thing.

## Judges tried

| judge | how it decides | eval_mode |
|---|---|---|
| gpt-4.1-mini (OpenRouter) | an LLM does everything: splits the answer, judges each part, writes the reason | `llm` |
| Jev 1.14 + gpt-4.1-mini | Jev (TypeSafe System One, `typesafe/jev-1.14`) gives the yes/no probabilities; gpt splits the answer, writes the reason, and steps in if Jev fails | `hybrid` |
| Jev 1.14 alone | Jev answers 3 fixed questions about the whole context; the reason text comes from a template; no LLM at all | `system_one` |
| jev-router (OpenRouter) | `typesafe/jev-router`, used as a normal text LLM. It picks the model itself, so neither the model nor the price is fixed | `llm` (before the flag existed) |

Jev is reached through OpenRouter with DeepEval's `TypeSafeModel` (`base_url="https://openrouter.ai/api"`). No adapter was needed. DeepEval doesn't know Jev 1.14's price, so we pass `cost_per_input_token = 0.042 / 1e6` (output is free).

## Runs

| run | judge | cost (8 questions) |
|---|---|---|
| `…_183243` | gpt-4.1-mini | $0.029 |
| `…_190146` | gpt-4.1-mini, again | $0.019 |
| `…_183519` | jev-router | $0.052 |
| `…_183641` | jev-router, again | $0.027 |
| `…_190001` | Jev 1.14 hybrid | $0.008 |
| `…_190050` | Jev 1.14 system_one | $0.0009 |

`…_184417` is also a gpt-4.1-mini run on the same 8 questions, with the same scores (0.81 / 0.81). Its `only_ids` field holds chunk ids by mistake, because of a shell variable mix-up, so the run is kept but not used here.
`183243`, `183519` and `183641` ran before the `--eval-mode` flag was added, so their config shows no `eval_mode`. `183519` and `183641` are **jev-router**, not Jev 1.14.

## Scores per question (Recall / Precision)

| id | hit@5 | gpt 1 | gpt 2 | hybrid | system_one | router 1 | router 2 |
|---|---|---|---|---|---|---|---|
| claude-005 | hit | 1 / .90 | 1 / .90 | 1 / .99 | .88 / .80 | 1 / .88 | 1 / .92 |
| codex-007 | hit | 1 / .64 | 1 / .64 | 1 / .64 | .95 / .71 | 1 / .64 | 1 / .64 |
| claude-033 | **miss** | 0 / 1 | 0 / 1 | .33 / .95 | .20 / .39 | 0 / 0 | 0 / .95 |
| codex-019 | hit | 1 / 1 | 1 / 1 | 1 / 1 | .93 / .83 | 1 / 1 | 1 / 1 |
| claude-026 | hit | 1 / 1 | 1 / 1 | 1 / 1 | .52 / .75 | .8 / 1 | .8 / 1 |
| claude-021 | hit | 1 / 1 | 1 / 1 | 1 / 1 | .65 / .83 | .67 / 1 | .67 / 1 |
| codex-012 | hit | 1 / .76 | 1 / .76 | 1 / .76 | .86 / .59 | 1 / .37 | 1 / .37 |
| codex-020 | **miss** | .5 / .2 | .5 / .2 | .5 / 0 | .23 / .26 | 0 / 0 | 0 / .2 |
| **mean** | | .81 / .81 | .81 / .81 | .85 / .79 | .65 / .64 | | |

## What the runs showed

1. **gpt-4.1-mini gave the same scores in both runs**, on all 16 numbers. With temperature 0 it is repeatable on this set.
2. **Hybrid agrees with gpt on 6 of 8 questions and costs about 40% as much.** It differs only on the two misses:
   - **claude-033:** recall 0.33 vs 0. Section 50 was not retrieved, so 0 is closer to the truth; hybrid gives some credit for a circular that mentions interest.
   - **codex-020:** precision 0 vs 0.2. gpt counted the rank-5 chunk (para 3.4 of the same guideline) as useful; Jev didn't.
3. **system_one scores in a different way.** It doesn't judge each chunk. It asks 3 fixed questions about the whole context and takes their weighted mean, so its scores bunch together (0.20–0.95). Hits still score above misses (both misses are the lowest two). But the 0.7 pass mark doesn't fit its scale: claude-026 is a retriever hit and still "fails" at 0.52. Each answer also comes with a confidence; some are very low (0.08–0.18), which says Jev itself is unsure there.
4. **jev-router is not usable as a judge.** claude-033's precision was 0 in one run and 0.95 in the next, and the cost changed from $0.052 to $0.027 because the router picks a different model each time.
5. **Jev's own numbers move a little** on the same input (0.80 / 0.81 / 0.82 in the earlier probe), so hybrid and system_one are not fully repeatable. The changes are small next to the router's.

## Decision

- **Default judge: hybrid** (`--eval-mode hybrid`). Close to gpt, cheaper, and its reasons are readable.
- **gpt-4.1-mini (`--eval-mode llm`)** when a number goes into a report and must be repeatable.
- **system_one:** keep it only for study. Don't compare its scores with the other two, because the scale is different.

## Limits of this test

- Only 8 questions. The dev set has 40; the 8 "none" rows have no gold and are skipped, so a full run judges 32.
- DeepEval caps the Jev context at Jev 1.13's limits (32k state, 64k request, in `system_one/constants.py`). With 10 or more long chunks a case could go over. Not hit here; not tested.
- OpenRouter's Decisions endpoint is marked alpha, and its docs page returned 404. It may change.

## Full dev run with hybrid (`…_190852`, $0.030)

| category | n | hit@5 | Ctx Recall | Ctx Precision |
|---|---|---|---|---|
| exact | 9 | 1.00 | 1.00 | 0.92 |
| hinglish | 6 | 0.33 | 0.60 | 0.84 |
| multi | 4 | 1.00 | 0.85 | 0.97 |
| scenario | 13 | 0.92 | 0.96 | 0.83 |
| **ALL** | **32** | **0.84** | **0.89** | **0.88** |

Where the judge and hit@5 disagree:
- **codex-026 (Hinglish, credit note and refund):** a miss by id, but recall 1.00. Checked by eye: section 34 and rule 53 don't say it. But Circular 137/07/2020, table row 3 (rank 3), does say something close: when goods are returned, the supplier issues a credit note and adjusts the tax in the return, instead of claiming a refund. The gold (162/18/2021 para 4.4) states the rule directly, for section 77 refunds. So the judge's 1.00 is half right: the idea is there, but for a narrower case. This is the kind of case the judge was added to catch, and also why its score needs a look by eye before we trust it.
- **claude-033:** a miss, recall 0.33 (see point 2 above; likely too generous).
- **claude-029, codex-028:** misses, and the judge agrees (recall 0.25 and 0).
- **claude-024 (multi):** a hit, but recall 0.67. One of its claims is not in the top chunks.
- **Precision near 0.5–0.6 on hits** (claude-019, claude-015, codex-007): the right chunk is found, but useless chunks sit above or between the useful ones. This links to the open question of whether `PER_CITATION = 10` is too many.
