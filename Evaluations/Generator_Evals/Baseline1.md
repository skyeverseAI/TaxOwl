# Generator eval — Baseline 1 (cloud and local)

**Date:** 2026-11-17 · **Code:** commit 2a47624 + uncommitted `generator_eval.py`, `to_sources()`, `is_refusal()` · **Gold:** `eval_results/gold/generator_dev.jsonl` (sha256 `4ad4cba0…`)

The first measured score of the generator (gpt-4o-mini). Every later prompt or model change is compared with these numbers.

## What was measured

- **Isolation:** the generator gets the GOLD chunks, not the retriever's, so a miss is the generator's fault, not retrieval's. The 8 "none" rows get the retriever's chunks (there are no gold chunks) and must refuse. No web search, no code-added notes.
- **Gold set:** same 40 questions and gold chunks as `retriever_dev.jsonl`, claims rewritten by Codex for the generator (`plans/codex_generator_gold_prompt.md`): only what the question asks, one fact per claim, each backed by an exact quote from the chunk. Checked by code (all quotes found) and read by hand; 4 merged claims split, 1 dropped claim restored (claude-008), 1 wording fixed (claude-028). claude-029's "supplies only after the certificate" stays dropped (user's call: not asked).
- **Judge:** DeepEval, gpt-4.1-mini via OpenRouter (not the generator's model: self-preference bias). Threshold 0.7.

**What the scores mean:**
- **refusal ok:** refused when it should (none rows), answered when it should (the rest).
- **checks failed:** `check.py` rules (made-up source, uncited claim, etc.).
- **Faithfulness:** every statement in the answer is backed by the chunks.
- **Answer Relevancy:** the answer sticks to the question.
- **Completeness:** share of gold claims the answer contains (ContextualRecall with answer as context). A refusal on an answerable row scores 0, by code.

## Scores — run `eval_results/runs/generator_cloud_20261117_200553.json`

| category | n | refusal ok | checks failed | sec | ₹ | Faithfulness | Relevancy | Completeness |
|---|---|---|---|---|---|---|---|---|
| exact | 9 | 1.00 | 0 | 3.5 | 0.22 | 0.94 | 1.00 | 0.98 |
| hinglish | 6 | 1.00 | 0 | 3.1 | 0.13 | 1.00 | 1.00 | 0.85 |
| multi | 4 | 1.00 | 0 | 3.7 | 0.12 | 0.96 | 1.00 | 0.81 |
| none | 8 | 1.00 | 0 | 1.8 | 0.39 | - | - | - |
| scenario | 13 | 0.92 | 0 | 3.1 | 0.29 | 1.00 | 1.00 | 0.87 |
| **ALL** | **40** | **0.97** | **0** | **3.0** | **1.15** | **0.98** | **1.00** | **0.89** |

Judge cost $0.11. The first run on the old claims (`generator_cloud_20261117_103803.json`) gave Completeness 0.84 and Relevancy 0.98. The same generator scored higher here only because the gold stopped asking for things the questions didn't ask.

## Flagged rows, read by hand

| row | flag | bucket | what happened |
|---|---|---|---|
| codex-003 | Faithfulness 0.67 | judge error | Judge said "may" should be "must"; the rule's own words are "may, before the expiry of two years". |
| claude-025 | Completeness 0.25 | judge error | Answer has 3 of 4 claims; judge tripped on "credit" vs "debit". Real score ≈ 0.75. |
| claude-033 | Completeness 0.60 | generator miss | Gave the cash-ledger relief, left out its exception (not after proceedings start) and "from the day after due". |
| codex-012 | Completeness 0.33 | generator miss | Gave "by nights stayed", left out the exception (one property across States, apportioned by area). Judge also under-counted claim 1. |
| codex-031 | Completeness 0.50 | generator miss (minor) | Left out "that State is the address on record for place of supply". |
| codex-020 | refused | generator miss | "Automatically" vs the chunk's "routine/mechanical": refused in both runs. |

## What we learned

1. **Drops the exception.** The model gives the main rule and leaves out the "but / except" part (claude-033, codex-012). In law that part often matters most.
2. **Over-refuses when words differ.** codex-020, stable across runs.
3. **The judge is wrong about 2 times in 32.** Flagged rows must be read by hand before anyone acts on them.

## Local model (qwen2.5:7b-instruct) — run `eval_results/runs/generator_local_20261117_201951.json`

Same gold, same judge. Gold chunks go through the local token budget (6000).

| category | n | refusal ok | checks failed | sec | ₹ | Faithfulness | Relevancy | Completeness |
|---|---|---|---|---|---|---|---|---|
| exact | 9 | 1.00 | 0 | 8.7 | 0 | 0.94 | 0.99 | 0.94 |
| hinglish | 6 | 1.00 | 0 | 7.4 | 0 | 0.96 | 0.87 | 1.00 |
| multi | 4 | 0.75 | 2 | 10.1 | 0 | 0.82 | 0.96 | 0.69 |
| none | 8 | 1.00 | 0 | 10.3 | 0 | - | - | - |
| scenario | 13 | 1.00 | 0 | 8.2 | 0 | 0.97 | 0.98 | 0.91 |
| **ALL** | **40** | **0.97** | **2** | **8.8** | **0** | **0.95** | **0.96** | **0.91** |

Judge cost $0.11.

| row | flag | bucket | what happened |
|---|---|---|---|
| claude-003 | Faithfulness 0.67 | judge error | Answer is the rule word for word; judge misread "month of issue, not later than 30 Nov". |
| claude-025 | Faithfulness 0.60 | judge error | "Can be released before the year" is right (rule 86A(2)). |
| codex-025 | Faithfulness 0.67 | judge error | Answer says "provided it has not been verified in transit": correct. |
| claude-007 | Completeness 0.67 | generator miss | Left out the exception: penalty-only order, pay 10% of the penalty. |
| claude-015 | Completeness 0.67 | generator miss | Left out the Commissioner's extension. |
| claude-019 | Completeness 0.67 | generator miss | Left out the fallback: no output liability, refund via RFD-01. |
| codex-012 | Completeness 0.50 | generator miss | Same as cloud: left out the one-property-across-States exception. |
| claude-026 | refused | generator miss | Refused; cloud answered it. |
| claude-028 | checks failed | generator miss | Good content, but no [S#] markers at all, so its section/circular names count as uncited. |
| codex-019 | Relevancy 0.44 | style | Pasted the whole section 9(1) (rates, collection) as a quote. |

## Cloud vs local

| | cloud (gpt-4o-mini) | local (qwen 7B) |
|---|---|---|
| Completeness | 0.89 | 0.91 |
| Faithfulness | 0.98 | 0.95 |
| checks failed | 0 | 2 (one row) |
| wrong refusals | 1 (codex-020) | 1 (claude-026) |
| sec / question | 3.0 | 8.8 |
| ₹ / 40 questions | 1.15 | 0 |

On 32 rows with ~3 judge errors per run, 0.89 vs 0.91 is a tie, not a win for local. The real differences: local sometimes forgets [S#] markers and pastes long quotes; cloud is 3x faster.

**Shared weakness: both drop the exception** (cloud 2 rows, local 4 rows; codex-012 in both). That is the first thing to fix.

## Next

- Try one prompt change for point 1 ("state any exception or proviso that applies") and rerun both. Measure it against these numbers, not per question.
