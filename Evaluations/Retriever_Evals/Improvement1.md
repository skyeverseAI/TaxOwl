# Retriever eval — Improvement 1

**Date:** 2026-11-08 · **Compared with:** `Baseline1.md` · **Question set:** `eval_results/gold/retriever_dev.jsonl` (40 rows, 32 scored; sha256 `93d4afe1…` after the gold change below)

Three changes, measured one at a time. Hinglish is left for the embedder change.

## Scores, full mode

Run `eval_results/runs/retriever_full_20261108_181748.json`. A second run (`…_181707.json`) gave the same top-10 list for every question, so the number is stable.

| category | n | hit@5 | hit@all | rec@5 | MRR | sec hit@5 | sec MRR |
|---|---|---|---|---|---|---|---|
| exact | 9 | 1.00 (was 0.78) | 1.00 | 0.94 (0.72) | 1.00 (0.65) | 1.00 | 1.00 |
| hinglish | 6 | 0.33 (0.17) | 0.33 | 0.33 | 0.21 | 0.33 | 0.21 |
| multi | 4 | 1.00 | 1.00 | 0.62 | 0.88 (0.75) | 1.00 | 1.00 |
| scenario | 13 | 0.92 (0.85) | 0.92 | 0.83 | 0.63 | 0.92 | 0.76 |
| **ALL** | **32** | **0.84 (0.72)** | **0.84** | **0.74 (0.64)** | **0.69 (0.52)** | **0.84** | **0.75** |

## The three changes

### 1. Exact chunks ordered by closeness to the question (`retriever.py`)

**Problem:** a named section or circular came back in page order (para 1, 2, 3 …), so the para that answers sat at rank 7–8 (claude-005, codex-007).

**Change:** all chunks of a cited document are found, then sorted by closeness to the question (same embedding model), and the top `PER_CITATION = 10` per citation are kept. Chunk vectors are cached in memory, so a chunk is embedded once per process.

**Why not keep page order:** page order is right for reading, wrong for ranking. The answer step still gets the chunks; only the order changes.

**Result:** exact hit@5 0.78 → 1.00, exact MRR 0.65 → 1.00. claude-005 and codex-007 are now at rank 1.

### 2. Gold widened for two rows (user approved)

- **codex-007:** the answer is also in `table-3:2` of the same circular; added.
- **claude-021:** the answer needs paras 3.3 and 3.4 as well as 3.5 (Codex's cross-check said so); added. Now at rank 2.

Both rows are in dev, so the test set is unchanged. Each row's `note` says what was added. This lifts the score a little for a reason other than the retriever; it is named here so nobody counts it as a retriever gain.

### 3. `ef_search` 100 → 500 (`store.py`)

**What it is:** Chroma searches with HNSW, a fast *approximate* nearest-neighbour index. It does not compare the question with every chunk; it walks a graph and keeps `ef_search` candidates. Bigger `ef_search` = closer to exact search, a bit slower.

**Problem:** at Chroma's default 100, the same question could get a different top 10 between runs (codex-019 flipped between hit and miss). Over 6 runs of the 40 dev questions, 2 changed between runs and 3 missed a chunk that exact (brute-force) search found.

**Change:** `EF_SEARCH = 500` in `store.py`, and the existing collection was changed with `collection.modify(...)`. The run JSON now records `ef_search` and `per_citation`.

**Result:** all 40 matched exact search in 6 of 6 runs. With 4,717 chunks, 500 costs nothing we can feel. For a much bigger store this needs measuring again (ANN recall vs exact on a sample).

## Run log

Every run of the day is kept in `eval_results/runs/`, full mode unless said. The `git_commit` in a run's config is the last commit; the change being tested was not committed yet.

| run | what changed before it | ALL hit@5 | MRR | what it showed |
|---|---|---|---|---|
| `…_164547` | first run of the eval script, on a 2-row smoke file (`data/smoke.jsonl`) | 1.00 | 1.00 | the script works end to end |
| `…_172028` | dev set ready (gold `4c9d6527`) | 0.75 | 0.55 | first real number |
| `…_172038` (meaning) | same, vector search alone | 0.66 | 0.50 | the embedding's own skill (in `Baseline1.md`) |
| `…_172234` | nothing (same code, same gold) | 0.72 | 0.52 | a different score from the same setup: the first sign of HNSW noise (codex-019) |
| `…_172354` | nothing | 0.72 | 0.52 | the run used in `Baseline1.md` |
| `…_174820` | change 1: exact chunks by closeness | 0.75 | 0.61 | claude-005 to rank 1; codex-007 and claude-021 still miss because their gold was too narrow |
| `…_175801` | change 2: gold widened (gold `93d4afe1`) | 0.84 | 0.69 | exact 1.00; still at `ef_search` 100 |
| `…_181707` | change 3: `ef_search` 500 | 0.84 | 0.69 | same score as before; the change is about stability, not score |
| `…_181748` | nothing | 0.84 | 0.69 | identical top 10 for every question: the number is stable |

So the score moved with changes 1 and 2. Change 3 did not move it; it made it repeatable (the 6-run test above).

## Misses left (5)

| id | category | why |
|---|---|---|
| claude-029, claude-033, codex-026, codex-028 | hinglish | English-only embedder; next step is a multilingual one (e.g. bge-m3) |
| codex-020 | scenario | right guideline document, different para |

The translation test in `Baseline1.md` showed language is not the only cause (claude-033 fails in English too).

## Not run yet

- Judge (DeepEval ContextualRecall/Precision; Jev through OpenRouter).
- Parent-document retrieval (plan step 7).
- Test set: only for final numbers.
