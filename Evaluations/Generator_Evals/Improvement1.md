# Generator eval — Improvement 1: keep the exceptions

**Date:** 2026-11-17 · **Compared with:** `Baseline1.md` · **Gold:** `eval_results/gold/generator_dev.jsonl` (sha256 `4ad4cba0…`), same judge

## The problem

In Baseline 1 both models gave the main rule and dropped its exception or fallback (cloud 2 rows, local 4; codex-012 in both). The prompt said "about 150 words" and said nothing about exceptions, so the exception was the first thing cut.

## The change

One prompt rule in `src/taxowl/answer/generator.py`. Before:

```
- Give information, not legal advice. Keep the answer short: about 150 words.
```

After (the user's wording, with a 250-word cap and "that applies to the question" so it doesn't add exceptions the question didn't ask about):

```
- Give information, not legal advice. Keep the answer short: about 150 words, never more than 250.
Cut background to stay short, never the conditions.
If the sources give an exception, proviso, extension or fallback to the rule you state (words like
"except", "provided that", "unless", "may extend") that applies to the question, include it, even if
the answer goes over 150 words.
Answer the question completely first, then keep it within 250 words.
```

Nothing else changed.

## Cloud (gpt-4o-mini) — run `generator_cloud_20261117_204016.json`

| | Baseline 1 | Improvement 1 |
|---|---|---|
| refusal ok | 0.97 (39/40) | **1.00** |
| checks failed | 0 | 0 |
| Faithfulness | 0.98 | 0.93 |
| Answer Relevancy | 1.00 | 0.97 |
| Completeness | 0.89 | **0.99** |
| words (median / max) | 106 / – | 115 / 176 |
| ₹ / 40 questions | 1.15 | 1.24 |

- Completeness went up because the exceptions now appear.
- codex-020 no longer refuses. This was a side effect: "answer completely first" pushed the model to answer.
- Faithfulness fell on 8 rows, all read by hand:
  - **judge error (5):** claude-003, claude-005, claude-016, claude-025, codex-015. Each answer repeats the source; on claude-005 the judge's own reason says "misinterpretation".
  - **real (2):** claude-033 states the exception backwards ("no interest after proceedings start"; the truth is "the cash-ledger relief doesn't apply then"). claude-029 garbles "90 days or the period applied for, whichever is earlier".
  - **still missing (1):** codex-012 still leaves out the area exception. Completeness wrongly gave it 1.0; Faithfulness caught it.

## Local (qwen2.5:7b-instruct) — run `generator_local_20261117_205720.json`

| | Baseline 1 | Improvement 1 |
|---|---|---|
| refusal ok | 0.97 | 0.93 |
| checks failed | 2 | 2 |
| Faithfulness | 0.95 | 0.98 |
| Answer Relevancy | 0.96 | 0.98 |
| Completeness | 0.91 | 0.90 |
| words (median / max) | 95 / – | 87 / 209 |

- **The rule did nothing for local.** claude-007, claude-015, claude-019 and codex-012 still drop the same exception, word for word as before. claude-026 still refuses.
- **Fixed, probably by chance:** claude-028 now has [S#] markers. codex-019 no longer pastes the whole section.
- **New:** on 2 "none" rows (claude-037, codex-040) the model wrote "The documents I have don't answer." and dropped "this". `is_refusal()` needs the exact sentence, so these count as answers and fail `cites_or_refuses`. The meaning is right; the copying is wrong.

## What we learned

1. A one-line prompt rule fixed the cloud model's main weakness (Completeness 0.89 → 0.99) and cost about 9 words per answer.
2. The 7B model doesn't follow the new rule. Prompt changes help the cloud model more than the local one.
3. Writing out an exception gives the model a new way to get it wrong (claude-033): it flips the condition.
4. The judge is noisy on Faithfulness (5 wrong of 8 drops). A 0.05 move in Faithfulness is not a signal by itself; read the rows.
