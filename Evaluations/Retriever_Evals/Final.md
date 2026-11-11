# Retriever eval — Final (v1)

**Date:** 2026-11-09 to 2026-11-11 · **Compared with:** `Improvement1.md` · **Question sets:** dev `eval_results/gold/retriever_dev.jsonl` (32 scored), test `eval_results/gold/retriever_test.jsonl` (20 rows, 16 scored; never used for tuning)

Two changes after Improvement 1: more chunks by meaning (5 → 8) and a new embedder (bge-small → bge-m3).

## v1 retriever

| setting | value | where |
|---|---|---|
| embedder | `BAAI/bge-m3` (1024 numbers, multilingual) | `embedder.py`, env `TAXOWL_EMBEDDER` |
| store | Chroma collection `corpus-bge-m3`, cosine, `ef_search` 500 | `store.py` |
| exact chunks | up to 20 in all, 10 per citation, closest first | `retriever.py` |
| meaning chunks | **8** (was 5) | `retriever.py` `MEANING_CHUNKS` |

## Final numbers, test set (full mode)

Runs `eval_results/runs/retriever_full_20261111_131458.json` (bge-m3) and `…_131802.json` (bge-small). Both with 8 meaning chunks.

| category | n | bge-small hit@5 | **bge-m3 hit@5** | bge-small MRR | **bge-m3 MRR** |
|---|---|---|---|---|---|
| exact | 4 | 1.00 | 1.00 | 0.83 | 1.00 |
| hinglish | 3 | 0.33 | 0.33 | 0.33 | 0.11 |
| multi | 2 | 1.00 | 1.00 | 0.60 | 0.38 |
| scenario | 7 | 0.57 | **0.86** | 0.36 | **0.76** |
| **ALL** | **16** | **0.69** | **0.81** | **0.50** | **0.65** |

Recall with exact + 8 meaning chunks (what the answer step gets): bge-small 0.62, **bge-m3 0.71**.

## Change 1: meaning chunks 5 → 8

**Problem:** the answer step gets every chunk the retriever returns. A right chunk at meaning rank 6–8 never reached it. recall@5 can't show this (it looks at the top 5 only, and more chunks are added *below* them).

**How we chose 8:** one dev run with `--meaning-chunks 15` (`…_20261109_222637.json`, bge-small), then the recall of "exact chunks + the first N by meaning" for each N:

| N | recall | tokens the meaning chunks add per question |
|---|---|---|
| 5 | 0.76 | ~1250 |
| **8** | **0.81** | ~1970 |
| 10 | 0.81 | ~2400 |
| 15 | 0.84 | ~3600 |

5 → 8 gained 2 questions for ~700 tokens; 8 → 10 gained none; 15 gained one more for double the tokens and more off-topic text for the generator. Tokens are counted with bge-small's tokenizer, so use them to compare cuts, not as a bill.

**Test set:** recall 0.68 → 0.71 with bge-m3 (multi 0.50 → 0.75).

## Change 2: bge-small → bge-m3

**Why try it:** Hinglish misses and plain-English misses where the right chunk wasn't in the list at all. A reranker can't fix those: it only reorders what came back.

**How:** the embedder is chosen by `TAXOWL_EMBEDDER`; each model has its own Chroma collection, so both stores sit side by side. Chunks are unchanged (sizes still counted with bge-small's tokenizer, ≤512; bge-m3 reads 8192).

**Dev set (full mode):** hit@5 0.84 → 0.88, MRR 0.69 → 0.65, recall@8 0.81 → 0.83. Meaning mode alone: hit@5 0.75 → 0.81, hit@all 0.78 → 0.88. Too small to decide on (1–3 questions), so the test set decided.

**Rule set before the test run:** bge-m3 only if it is clearly ahead (2+ questions) on test. It was: 13 vs 11. The two it fixed are everyday English questions:
- claude-011: credit taken, supplier not paid for six months (rule 37)
- codex-011: details a tax invoice must show (rule 46)

**How sure is this? Not proven.** Question by question (full mode, hit@5), bge-m3 fixed 4 and broke 1 over dev + test (48 questions); the other 43 came out the same. If the two models were really equal, a 4–1 split would still happen by chance about 19% of the time. So the result *leans* to bge-m3; it doesn't prove it. Meaning mode leans the same way (3 fixed, 1 broken on dev). Chosen for v1 because it is almost never worse and is the larger, multilingual model. To settle it in v1.1: a bigger test set, or real user questions from the deployed app's logs.

**Overfitting sign:** bge-small fell from 0.84 (dev) to 0.69 (test); bge-m3 from 0.88 to 0.81. The dev-set changes fitted bge-small's dev misses more than the general case.

**Cost:**
- model ~2.3 GB; needs ~2–3 GB RAM on the server (bge-small: ~200 MB). Free hosting tiers won't run it.
- median retrieval 0.058 s vs 0.009 s (dev runs); still small next to the LLM.

## Misses left

| id | set | category | why |
|---|---|---|---|
| claude-029, claude-033, codex-019 | dev | hinglish | right chunk not in list; bge-m3 fixed codex-026 and codex-028 but lost codex-019 |
| claude-031, codex-030 | test | hinglish | right chunk not in list |
| codex-020 | dev | scenario | right guideline, different para (para 3.1, chunk 1 at rank 5; gold is chunk 4) |
| claude-020 | test | scenario | rule 36(4) not in list |

Hinglish is still the weak spot (1 of 3 on test). It is left for v1.1.

## Looked at, not done for v1

- **Section-limit / MMR** (fewer chunks from one section): the 8 meaning chunks usually come from 5–8 sections already. One question (codex-020) had 5 from rule 147, but its gold para was not in the top 15, so freeing slots wouldn't bring it in.
- **Parent-document retrieval:** cut to v1.1 for time (2026-11-09). Wouldn't fix codex-020 either (no chunk of the gold para came back).
- **Reranker:** fixes order, not reach. On the dev set most misses were reach. Revisit with the judge's precision numbers in v1.1.
- **Judge** (DeepEval contextual recall/precision) on the final setup: not run; id scores were enough to decide.

## Run log

| run | set | embedder | meaning chunks | hit@5 | note |
|---|---|---|---|---|---|
| `…_20261109_222637` | dev | bge-small | 15 | 0.84 | the N table above |
| `…_20261109_235453` | dev | bge-small | 8 | 0.84 | new baseline at N=8 |
| `…_20261109_235518` | dev | bge-m3 | 8 | 0.88 | |
| `…_20261109_235528` (meaning) | dev | bge-small | — | 0.75 | embedder alone |
| `…_20261109_235542` (meaning) | dev | bge-m3 | — | 0.81 | embedder alone |
| `…_20261111_131802` | test | bge-small | 8 | 0.69 | |
| `…_20261111_131458` | test | bge-m3 | 8 | 0.81 | **v1 number** |

All runs record `git_commit` 60bdaac: the changes were not committed yet when they ran.
