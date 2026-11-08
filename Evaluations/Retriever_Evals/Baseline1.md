# Retriever eval — Baseline 1

**Date:** 2026-11-08 · **Code:** commit 5580b47 (retriever as built in eb97fec) · **Plan:** `plans/retriever_evals_plan.md`

The first measured score of the retriever. Every later change is compared with these numbers.

## What was measured

- **Question set:** `eval_results/gold/retriever_dev.jsonl`, 40 questions (sha256 `4c9d6527…`). 32 have a right answer in the documents; the 8 "none" questions don't, so the retriever eval skips them (they test refusal in the answer eval).
- **How the set was made:** Claude and Codex each wrote 40 questions from the chunks, with the right chunk ids and the answer as short claims. Each checked the other's set (`crosscheck_*.md`), and the problems were fixed. Duplicates were dropped and 60 questions were picked across categories, then split at random (seed 2026): 40 dev, 20 test. The test set stays unseen until the final numbers. Three stale-law questions went to `validity_traps.jsonl`, for the validity-status step.
- **Retriever:** bge-small-en-v1.5, Chroma collection `corpus-bge-small`, 4,717 chunks. Exact chunks for named citations first (up to 20), then 5 by meaning.
- **Two modes:**
  - **full:** the whole retriever. What the answer step gets, so this is the real score.
  - **meaning:** vector search alone (top 10). Shows the embedding's own skill.

## Scores

**What the scores mean:**
- **hit@5:** was a right chunk in the top 5?
- **hit@all:** was it anywhere in what came back?
- **rec@5:** what share of the right chunks were in the top 5?
- **MRR:** 1 ÷ the rank of the first right chunk.
- **sec:** the same, counting any chunk from the right section, rule or para.

### Full mode (the real score), run `eval_results/runs/retriever_full_20261108_172354.json`

| category | n | hit@5 | hit@all | rec@5 | MRR | sec hit@5 | sec MRR |
|---|---|---|---|---|---|---|---|
| exact | 9 | 0.78 | 1.00 | 0.72 | 0.65 | 0.89 | 0.79 |
| hinglish | 6 | 0.17 | 0.17 | 0.17 | 0.04 | 0.17 | 0.04 |
| multi | 4 | 1.00 | 1.00 | 0.62 | 0.75 | 1.00 | 1.00 |
| scenario | 13 | 0.85 | 0.85 | 0.81 | 0.59 | 0.85 | 0.72 |
| **ALL** | **32** | **0.72** | **0.78** | **0.64** | **0.52** | **0.75** | **0.65** |

### Meaning mode, run `eval_results/runs/retriever_meaning_20261108_172038.json`

| category | n | hit@5 | hit@all | rec@5 | MRR | sec hit@5 | sec MRR |
|---|---|---|---|---|---|---|---|
| exact | 9 | 0.56 | 0.56 | 0.56 | 0.50 | 0.78 | 0.78 |
| hinglish | 6 | 0.17 | 0.33 | 0.17 | 0.07 | 0.33 | 0.08 |
| multi | 4 | 1.00 | 1.00 | 0.62 | 0.88 | 1.00 | 1.00 |
| scenario | 13 | 0.85 | 0.85 | 0.81 | 0.59 | 0.85 | 0.72 |
| **ALL** | **32** | **0.66** | **0.69** | **0.59** | **0.50** | **0.75** | **0.65** |

## What the numbers say

1. **Exact lookup works, but its order is wrong.** In full mode exact has hit@all = 1.00: every named section or circular was found. Two still miss at 5 (claude-005 at rank 8, codex-007 at rank 7). A named circular comes back in page order (para 1, 2, 3 …), so the para that answers falls below rank 5. Possible fix: order a citation's chunks by closeness to the question, not by page.
2. **Hinglish is the weakest part: 1 of 6 found.** The embedding model is English-only. See the translation test below.
3. **Scenario questions are fine (0.85).** Of the two misses, claude-021 got the neighbouring para (3.3 instead of 3.4–3.5) and codex-020 got another para of the right guideline.
4. **Exact lookup lifts the score from 0.66 to 0.72**, all of it in the exact category. The other categories match across the two modes.

## Translation test (one-off, 2026-11-08)

Two Hinglish misses, asked again in English, full mode:

| question | Hinglish: rank of the right chunk | English: rank of the right chunk |
|---|---|---|
| codex-028 (CIRP, old GST dues) | not found | **1** |
| claude-033 (late GSTR-3B, interest) | not found | not found |

- **codex-028:** translation fixes it fully.
- **claude-033:** English fails too, so the problem isn't the language. Circulars about particular interest cases (7/7/2017 para 12 on the 2017 transition; 136/06/2020 on the COVID-period rate) are closer in meaning than section 50 itself. The Act loses to circulars that talk about the same thing in a narrower case.

So translating the question helps some Hinglish misses, not all. Two questions are too few to decide; the next step is to translate all six and measure.

## Not run yet

- The judge (DeepEval ContextualRecall/Precision, and Jev through OpenRouter as the cheap judge). Planned after the first fixes.
- The test set (20 questions): only for final numbers.
