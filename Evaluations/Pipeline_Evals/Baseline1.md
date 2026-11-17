# Pipeline eval — Baseline 1 (cloud and local)

**Date:** 2026-11-18 · **Code:** commit a222fe5 + uncommitted `pipeline_eval.py`, `answer()` returning `model_text` · **Gold:** `eval_results/gold/generator_dev.jsonl` (sha256 `0c1c310c…`, the generator gold plus `"expects": "web"` on 2 rows)

The first score of the WHOLE app on the dev questions. The generator eval asked "is the model good when it gets the right chunks?". This eval asks "is the answer the user sees good?".

## What was measured

```
generator eval:  GOLD chunks          → model                → score   (the model alone)
pipeline eval:   retriever + web (app) → model → + our notes  → score   (what the user reads)
```

- **Same entry point as the app:** `pipeline.answer()`: retrieve, label, web search for rate questions, generate, then `rate_note` / `amended_note` added by code, then `check.py`.
- **Judged text = the full text the user reads**, the answer AND our notes (user's call: the notes are claims too).
- **Same judge as the generator eval:** DeepEval, gpt-4.1-mini via OpenRouter, threshold 0.7, same `judge()` function. So the two tables can be compared line by line.
- **Gold set:** the generator gold (40 rows, Codex claims). One change: codex-034 (earbuds) and codex-038 (3D printers) are GST rate questions our corpus can't answer, but the app searches the web for exactly these. They are now marked `"expects": "web"`: the app must answer AND cite a WEB [S#]. claude-037 (RoDTEP rate) also triggers the web search but isn't GST, so refusing it stays correct. That is why the label lives in the gold, not in code.

**New scores, beyond the generator eval's:**
- **gold found:** did any gold chunk reach the model? This is the retriever's hit, counted inside the pipeline (the budget and the web sources included).
- **blame:** for each answerable row, which part to fix:

```
                 complete (Completeness ≥ 0.7)   incomplete or refused
gold found            ok                          generator
gold not found        ok (other chunks / web)     retriever
```

## Cloud (gpt-4o-mini) — run `eval_results/runs/pipeline_cloud_20261118_030606.json`

| category | n | refusal ok | checks failed | sec | ₹ | Faithfulness | Relevancy | Completeness | gold found |
|---|---|---|---|---|---|---|---|---|---|
| exact | 9 | 1.00 | 0 | 8.2 | 0.71 | 0.93 | 0.95 | 0.98 | 1.00 |
| hinglish | 6 | 1.00 | 0 | 6.7 | 0.39 | 0.94 | 0.93 | 0.93 | 0.67 |
| multi | 4 | 1.00 | 1 | 4.3 | 0.25 | 0.93 | 1.00 | 0.94 | 1.00 |
| none | 8 | 0.88 | 1 | 3.4 | 0.44 | 0.92 | 1.00 | - | - |
| scenario | 13 | 1.00 | 0 | 4.0 | 0.80 | 0.97 | 0.95 | 0.92 | 0.92 |
| **ALL** | **40** | **0.97** | **2** | **5.3** | **2.59** | **0.95** | **0.95** | **0.94** | **0.91** |

Judge cost $0.20. Median 4.5 s per answer (max 24.4 s; the first row of a fresh process takes much longer while the embedder loads, 101 s in the no-judge run). Median 12 sources per answer, 135 words.

**Blame (32 answerable rows):** ok 29 · generator 2 · retriever 1.

### Next to the generator eval (same 40 questions, same judge)

| | generator eval (Improvement 1) | pipeline eval |
|---|---|---|
| refusal ok | 1.00 | 0.97 |
| Faithfulness | 0.93 | 0.95 |
| Answer Relevancy | 0.97 | 0.95 |
| Completeness | 0.99 | **0.94** |
| ₹ / 40 questions | 1.24 | **2.59** |

- **Completeness 0.99 → 0.94** is the cost of real retrieval. With gold chunks the model leaves almost nothing out; with the app's own sources it does, on 3 rows.
- **Cost doubles**: a median of 12 sources instead of the 1-4 gold chunks, so the model reads more tokens.
- **Faithfulness rose slightly.** That isn't a better model: it is judge noise on different rows (see the judge errors below).

## Flagged rows, read by hand

| row | flag | bucket | what happened |
|---|---|---|---|
| claude-033 | Completeness 0.60, Relevancy 0.57 | **retriever miss** | Hinglish interest question: section 50 not retrieved. "rate" in the question started a web search, so the answer came from the web plus a 2020 COVID-period circular. The cash-ledger relief and its exception are missing. In the generator eval (gold chunks) this row scored 1.0. |
| claude-015 | Completeness 0.67, Relevancy 0.60 | **generator miss + our bug** | Gold chunks found, but the model quoted the circular and dropped the Commissioner's one-year extension (1.0 in the generator eval, where only the gold chunks were given). Three amended notes were added, and the rule 45 note appeared twice (one per chunk, [S11] and [S12]). The judge counted the notes as off-topic, which lowered Relevancy. |
| codex-012 | Completeness 0.33 | **generator miss (known)** | Drops the "one property across States → by area" exception, as in both generator runs. |
| codex-038 | answered, no WEB [S#] | **real; the code caught it, the judge didn't** | Says "18%", cites no source, then ends "the documents I have don't answer this". `cites_or_refuses` failed, while the judge gave Faithfulness 1.0. |
| codex-004 | Faithfulness 0.67 | judge error | The answer quotes section 12(8) word for word; the judge mixed in the registered-recipient rule. |
| claude-026 | Faithfulness 0.86 + `no_new_citation` | judge error + small real slip | The judge's reason contradicts itself ("not blocked" vs "not excluded"). The check failure is real: the answer names section 2(19), which no cited source contains. |

**Lucky rows:** codex-019 and codex-020 missed their gold chunk but scored Completeness 1.0 from other chunks that say the same thing. The retriever eval counts these as misses; the user wouldn't notice.

## What we learned

1. **More sources, more dropped exceptions.** claude-015 was complete with 2 gold chunks and incomplete with 12 sources. The prompt's "keep the exceptions" rule holds less well when the exception sits in a different chunk from the main rule.
2. **"Rate" sends interest questions to the web.** `wants_web()` was meant for product tax rates; "interest kitne rate se" matched too (claude-033). When retrieval also misses, the web decides the answer.
3. **The free checks earn their place.** On codex-038 the judge gave 1.0 to an answer with no citation that contradicts itself; `check.py` caught it.
4. **Our own notes can hurt the score and the reader.** A duplicate line, and three warnings under a short answer. Fixed: one line per provision, listing every [S#] (`amended_note`, 2026-11-18). The notes' relevance is still open.
5. **The judge was wrong about 2 times in 34**, as in the generator eval. Flagged rows must be read before acting.

## Fixed after this run (not in the numbers above)

- `amended_note`: one line per provision (claude-015's duplicate).
- Eval runner: answers are saved BEFORE the judge runs, and the judge gets `max_tokens` 4000 (a low OpenRouter balance failed the first judged run with 402 and lost the paid answers).

## Local (qwen2.5:7b-instruct) — run `eval_results/runs/pipeline_local_20261118_035755.json`

Same code, with the local budget (6000 bge tokens of sources). The amended_note dedupe was already in.

| category | n | refusal ok | checks failed | sec | ₹ | Faithfulness | Relevancy | Completeness | gold found |
|---|---|---|---|---|---|---|---|---|---|
| exact | 9 | 1.00 | 3 | 33.4 | 0 | 0.91 | 0.84 | 0.79 | 1.00 |
| hinglish | 6 | 1.00 | 0 | 31.0 | 0 | 0.85 | 0.94 | 0.93 | 0.67 |
| multi | 4 | 1.00 | 1 | 30.8 | 0 | 0.97 | 0.96 | 0.81 | 1.00 |
| none | 8 | 0.88 | 1 | 21.9 | 0 | 1.00 | 1.00 | - | - |
| scenario | 13 | 0.85 | 3 | 27.9 | 0 | 0.87 | 0.91 | 0.67 | 0.92 |
| **ALL** | **40** | **0.93** | **8** | **28.7** | **0** | **0.90** | **0.91** | **0.77** | **0.91** |

Judge cost $0.19. Median 27.4 s per answer (max 49.8 s). Median 12 sources (the budget didn't cut below cloud's median), 101 words.

**Blame (32 answerable rows):** ok 22 · generator 8 · retriever 2.

### Cloud vs local

| | cloud | local |
|---|---|---|
| gold found | 0.91 | 0.91 |
| Completeness | 0.94 | **0.77** |
| Faithfulness | 0.95 | 0.90 |
| blame: generator | 2 | **8** |
| checks failed | 2 | 8 |
| median seconds | 4.5 | 27.4 |
| ₹ / 40 questions | 2.59 | 0 |

- **Same sources, weaker model.** gold found is the same 0.91, so the retriever gave both models the same chance. The 17-point Completeness gap is the 7B model.
- **Refusing when the answer is there** is the main local failure: claude-019, codex-008 and codex-023 had their gold chunk and still refused (cloud: 1.0 on all three).
- **Wrong facts:** claude-015 says inputs must come back in "three years" (one year; three is for capital goods). claude-017, codex-022 and codex-025 each got a Faithfulness drop for a misread rule.

### A measurement bug the local run exposed

qwen often writes the refusal as **"The documents I have don't answer."** (no "this"). `is_refusal()` is an exact match on "...don't answer this.", so:

| row | expects | qwen wrote | eval counted | really |
|---|---|---|---|---|
| codex-040 | refuse | "...don't answer." | answered a 'none' question | correct refusal |
| claude-019 | answer | "...don't answer." | answered, Completeness 0 | wrong refusal |
| codex-008 | answer | assumed-law line + "...don't answer this." | answered (mixed_refusal) | wrong refusal |

So the local "refusal ok" (0.93) is not exact: none is really 1.00, the answerable rows are lower. The blame and Completeness are still right (a refusal scores 0 either way). The same exact match runs in the app's `check.py`, so the user sees a `cites_or_refuses` failure on a correct local refusal.

## Open, for later

- claude-033: Hinglish retrieval (known since the retriever eval), and the `wants_web()` match on "interest rate".
- claude-015 / codex-012: exceptions dropped when sources are many.
- codex-038: a web answer with no [S#]. Could a prompt line ("cite the WEB source you use") fix it?
- Should amended notes appear only when the answer actually relies on the changed rule?
- `is_refusal()`: accept the "don't answer." variant (and a refusal after the assumed-law line), or make the generator force the exact sentence. Changes the app's checks too, so re-run both evals after.
- Local wrong refusals (claude-019, codex-008, codex-023) with the gold in hand: the 7B model with 12 sources. Try fewer sources for local? The deploy runs cloud only, so this is not a v1 blocker.
