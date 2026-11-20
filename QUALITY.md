# How good is taxowl? (v1)

Plain numbers, with the catch next to each one. Full reports are in `Evaluations/`; the extraction story
is in `plans/extraction_journey.md`.

**Read this first: almost every number here is on a small dev set (32–40 questions), and the same
questions were used while building.** They show how the app behaves; they are not a promise on new
questions. Only the retriever has a separate test set (16 scored questions, never used for tuning).

```
 PDF ──► extract ──► split ──► retrieve ──► answer ──► checks + notes ──► user
          97%                   81% hit@5    0.94 complete   2/40 caught
       (held-out pages)        (TEST set)    (dev, judge = upper bound)
```

## 1. Reading the PDFs (extraction)

| set | score | note |
|---|---|---|
| gold (11 cases, 230 checks, verified by hand) | ~99% on plain text, Act, Rules | used while building |
| held-out pages (never seen) | **97.3%** | with the scan gate |
| fresh held-out (seeds 2034–36) | **97.7%** | the score held on new pages |
| corpus scans (OCR) | 94.3% | scanned circulars are the weak spot |

## 2. Finding the right law (retriever) — TEST set

| category | n | hit@5 | MRR |
|---|---|---|---|
| exact ("section 16(4)") | 4 | 1.00 | 1.00 |
| scenario (plain English) | 7 | 0.86 | 0.76 |
| multi (needs 2+ sources) | 2 | 1.00 | 0.38 |
| hinglish | 3 | **0.33** | 0.11 |
| **all** | **16** | **0.81** | **0.65** |

hit@5 = the right chunk is in the top 5. Recall of what the model actually gets (exact + 8 by meaning):
0.71. **Hinglish is the weakest part of the app.** bge-m3 beat bge-small 13 vs 11 here, but over all
48 questions that is 4 fixed, 1 broken: it leans better, not proven.

## 3. The whole app (pipeline) — dev set, 40 questions, cloud gpt-4o-mini

| | value |
|---|---|
| refused when it should, answered when it should | 0.97 |
| right source reached the model ("gold found") | 0.91 |
| Faithfulness (says only what the sources say) | 0.95 |
| Completeness (main rule + its exceptions) | 0.94 |
| Answer Relevancy | 0.95 |
| answers the free code checks flagged | 2 / 40 |
| median time / cost per answer | 4.5 s / ₹0.065 |

Where the misses came from (32 answerable questions): ok 29, model 2, retriever 1.

Local model (qwen2.5 7B, not deployed): Completeness 0.77, 27 s per answer. Same sources, weaker model.

### The judge is lenient: treat 0.94 / 0.95 as an upper bound

The scores come from an LLM judge (DeepEval, gpt-4.1-mini). We checked it on 18 answers against
Claude and Codex reading them by hand:

| | judge got it right | Claude / Codex |
|---|---|---|
| Faithfulness | 13 / 18 | 17 / 14 |
| Completeness | 12 / 18 | 17 / 17 |

10 of its 11 misses **passed** a wrong or incomplete answer. A bigger judge (gpt-4.1) did no better.

## 4. Is the law still the law? (validity)

| | value |
|---|---|
| withdrawn / changed circulars found: precision | 55/59 = 0.93 |
| recall (against CBIC's own notes) | 17/19 = 0.89 |
| trap questions answered right | **1 / 4** |

Code-made labels and warnings work (`WITHDRAWN by…`, ⚠ "rule amended after this circular"). The model
itself doesn't reason about dates: given an old circular and the current rule, it leads with the old one.

## 5. Safety — 12 questions

| | result |
|---|---|
| off-topic questions refused | 4 / 4 |
| prompt injection resisted | 3 / 4 |
| "advice" questions handled well | 3 / 4 (one over-refusal) |

## Known limitations

- **Hinglish questions** often miss the right law (test hit@5 0.33).
- **Abbreviations**: "ITC" and similar short forms can miss the section that spells them out.
- **Over-refusal**: sometimes says "the documents I have don't answer this" when they do.
- **Prompt injection**: a fake "SYSTEM: say X" inside the question can make the model write X (s11).
  The rest of the answer stays sourced.
- **Old circulars**: the ⚠ note warns, but the answer's first line can still state the old rule.
- **Rates** come from a web search, so they are only as good as the sites found; some web claims carry
  no [S#].
- **Exceptions** get dropped more often when there are many sources (12 instead of 2–4).
- **"Interest rate" questions** trigger the rate web search, which can pull the answer off course.
- Small sets everywhere: these numbers show behaviour, not a rate. v1.1: real questions from the
  deployed app's logs, a bigger test set.

## Re-run

```
uv run python -m taxowl.evals.retriever_eval \
  --gold eval_results/gold/retriever_test.jsonl --mode full
uv run python -m taxowl.evals.pipeline_eval \
  --gold eval_results/gold/generator_dev.jsonl --which cloud
uv run python -m taxowl.evals.safety_eval \
  --gold eval_results/gold/safety_set.jsonl
```
They need the local store (`data/`) and API keys (OpenRouter for answers and the judge, Tavily for web).
