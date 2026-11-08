# Plan: Retriever eval (component eval #1)

## Context

The retriever is done (`src/taxowl/retrieval/retriever.py`, commit eb97fec) and so is the answer step, but the retriever has only been checked by eye with 10 questions (`experiments/try_search.py`). Next we want real numbers: **hit@5 / recall@5** (did the right chunk come in the top 5?) and **MRR** (how high it came). The numbers come from a golden set: questions, each with its right chunk ids and its answer split into claims.

**Audience (user, 2026-11-07):** anyone can ask, from a small trader to a CA or a tax officer. The answer must be complete and exact enough for a CA or an officer to quote (provision numbers, conditions, limits), but written so a layperson understands it. So the questions mix everyday and professional language, and the claims carry the exact provision and every condition.

Decided in chat (2026-11-07):
- **Gold = chunk ids + claims.** Chunk ids are readable labels made from the document number and the section or para (`162-18-2021-gst:para-3-2`), not random. So rebuilding the store, or adding a new circular, keeps them the same. They change only if we change the splitter or chunker, and the eval stops if a gold id is missing.
- **Both kinds of score, studied side by side:**
  - by id, no LLM: hit@5 (headline), recall@5, MRR, at chunk level and at section level;
  - by claims, with DeepEval's judge: ContextualRecall and ContextualPrecision, as in evals_project. This catches a *different* chunk that says the same thing.
- **Section level (parent document):** each chunk carries `unit_id` (its section, rule or para). A section-level hit means "some chunk of the right section came". A big gap between chunk level and section level means the retriever finds the right place but not the right piece.
- **Pool, then split (user, 2026-11-08):** Codex and Claude each write 40 rows with the same Prompt A → duplicates out, 60 kept with the category balance → random split by category, fixed seed: 40 dev, 20 test. The split is made before the retriever is run on them.
- **Checks:** the two AIs cross-check each other's rows; Codex compares every gold chunk with the PDF page text. The user looks only at rows where the AIs disagree.
- Router / separate stores per law: after v1, not now.

## Steps

### 0. Save this plan — DONE
`plans/retriever_evals_plan.md`.

### 1. Two pools of 40
The user pastes **Prompt A** (below) into Codex → `eval_results/gold/pool_codex.jsonl`. Claude writes `eval_results/gold/pool_claude.jsonl` with the same prompt (ids `claude-001`…).

### 2. Cross-check
Claude checks Codex's pool, and Codex checks Claude's: every gold id exists, each claim is in the gold chunks' text, no question copies the chunk's wording, no gold chunk is missing. Codex also compares each gold chunk with the PDF page text (PyMuPDF), which catches extraction errors. Each reports problems and does not edit the other's file. The user decides only the rows where they disagree.

### 3. `experiments/show_chunks.py`: a helper for looking at gold
`uv run experiments/show_chunks.py "162/18/2021" "para 3"` prints matching chunks (id, location, pages, first lines). Used while checking rows. It reads `data/chunks.jsonl` (path from `src/taxowl/config.py`); no store, no model.

### 4. The eval: `src/taxowl/evals/`
- `metrics.py`: LERAGS `src/similarity/metrics.py` copied unchanged (the user wrote it), plus `hit_at_k`.
- `retriever_eval.py`, shaped like `evals_project/evals/evals_retriever.py` (load goldens → run the injected retriever → metrics → summary):
  1. load the jsonl; **stop if any gold id is not in `data/chunks.jsonl`**;
  2. for each question with gold: `retriever.invoke(q)` → ids (store ids = chunk_id, `store.py:37`);
  3. id scores: hit@5, recall@5, MRR, at chunk level and at section level (gold ids → their `unit_id`s);
  4. with `--judge`: DeepEval ContextualRecall + ContextualPrecision (claims joined as `expected_output`, judge `openai/gpt-4.1-mini` via OpenRouter, as in evals_project). Off by default because it costs money and its score moves a little run to run;
  5. averages per category and overall; a printed table, then the misses.
- Two modes, `--mode`:
  - `full`: the whole LawRetriever (exact lookup first, then meaning). What the app uses: the real score.
  - `meaning`: `store.similarity_search(q, k=10)` only. Exact lookup fixes many questions whatever the embedding is, so only this mode shows the embedding's own skill. Used to compare embedding models (R8).
- Rank = position in the returned list. Exact chunks come first and can be up to 20, so the "section 73" flood shows up as a miss.
- Output: `eval_results/runs/retriever_<mode>_<time>.json` with the config (embedding model, collection, chunk count, MEANING_CHUNKS, EXACT_CHUNKS, golden-file sha256, judge model), per-question rows (question, gold, top 10 ids, hit, rank, judge scores) and the summary.
- Differs from evals_project: id scores need no judge, so they run free on every change; the judge is a flag. `run(retriever)` still takes the retriever as an argument, so a reranker or another embedding can be passed in.
- New dependency: `deepeval` (pinned, as in evals_project).
- `__main__` guard. The user runs it:
  `uv run python -m taxowl.evals.retriever_eval --gold eval_results/gold/retriever_dev.jsonl --mode full [--judge]`

### 5. Baseline
Run both modes on dev (with `--judge` once) and write the numbers plus the main misses into `to-do-list.md` section R (R6). This is the number every later change is measured against.

### 6. Merge and split (before step 4 is run on them)
A small script merges the two pools, drops near-duplicate questions, keeps 60 with the category balance, and splits them by category with a fixed seed: `retriever_dev.jsonl` (40) and `retriever_test.jsonl` (20). The test set is run only for final numbers, never while tuning; its sha256 is in every run JSON. With 20 test rows, per-category test numbers are only a hint.

### 7. First improvement: parent-document retrieval
Measured against the baseline on dev: group retrieved chunks by `unit_id` so one section takes one slot (or MMR, which skips near-duplicate chunks), and send only the matched chunk plus its neighbours, not a whole 6k-token section. Kept only if the dev score goes up, then confirmed on test.

### Later (not in this plan)
Reranker; embedding comparison (R8); exact-chunk flood fix; Hinglish misses. Each is measured against the baseline.

## Files
- new: `eval_results/gold/pool_codex.jsonl`, `pool_claude.jsonl`, `retriever_dev.jsonl`, `retriever_test.jsonl`, `experiments/show_chunks.py`, `src/taxowl/evals/__init__.py`, `metrics.py`, `retriever_eval.py`
- edit: `pyproject.toml` (deepeval), `src/taxowl/config.py` (runs path), `to-do-list.md` (R6 results)
- reuse: `make_retriever()`, `get_store()` (`src/taxowl/retrieval/`), LERAGS `metrics.py`, evals_project's DeepEval setup

## Verification
- `metrics.py` `__main__` prints the known values (2/3, 0.5, 0.333…).
- On a hand-made 3-row file: the 16(4) and 36(4) questions get hit@5 = 1 (try_search showed rank 1), and a fake id makes the eval stop.
- Full dev run finishes, the JSON is written, and per-category numbers add up to the overall.

---

## Prompt A: golden-set pool (Codex and Claude, paste as is)

```
You are building a golden set to evaluate a retriever in this repo (taxowl, a RAG over Indian GST law).
Work only from the files; do not use the web. Do NOT run or read the retriever or its outputs
(src/taxowl/retrieval/, experiments/try_search.py, experiments/try_answer.py): the questions must not be shaped by what the retriever already finds.

AUDIENCE
Anyone may ask: a small trader, an accountant, a Chartered Accountant, a tax officer. The final answer must be exact
enough for a CA or officer to quote (provision, conditions, limits, dates), yet plain enough for anyone to follow.
So: questions mix everyday and professional language, and the claims must be complete and exact.

SOURCE OF TRUTH
- data/chunks.jsonl: one JSON chunk per line. Fields you need: chunk_id, unit_id, text, doc_type
  (act | rules | circular | instruction | notification), doc_number, location, page_start, page_end, kind (text | table).
  Each chunk's text begins with a header line ("Circular 162/18/2021-GST — <title> — para 3.2"); that header is not part of the law.
- Work from the chunk text; no need to open the PDFs (a later step compares chunks with the PDFs).

OUTPUT
eval_results/gold/pool_codex.jsonl, 40 rows, one JSON object per line, exactly these keys:
{"id": "codex-001", "category": "...", "question": "...",
 "gold_chunks": ["<chunk_id>", ...], "claims": ["...", ...], "note": "<doc_number>, <location>, page N"}

CATEGORIES (counts are targets)
- exact (10): names a section, rule or circular number, as a CA would: "Under 17(5)(d), is ITC allowed on ...?",
  "What does rule 36(4) require?". Mix CGST Act, CGST Rules, IGST Act/Rules and circulars, including sub-clauses.
- scenario (12): a real client or business situation, naming NO section or circular number. Half in everyday words
  (a trader), half in professional words (a CA: "registered person", "place of supply", "reverse charge").
- multi (6): the answer needs 2-3 different documents together, e.g. a rule plus the circular that clarifies it.
  gold_chunks then has one chunk from each document.
- hinglish (5): like scenario, in Hinglish (Hindi in Roman script mixed with English).
- none (7): plausible, on-topic questions whose answer is NOT in these documents: a court judgment's outcome, a GST
  rate from a rate notification (rate notifications are not in the corpus), income-tax rules, a state's own circular,
  a figure the documents never state. No silly out-of-scope questions. For none rows: gold_chunks = [], claims = [].

RULES
1. Do not copy the chunk's wording into the question. Ask the way the person would from memory.
   Paraphrase legal terms ("subsequently held" -> "later found out myself").
2. gold_chunks = EVERY chunk whose text is needed to answer, and no chunk that only gives background.
   Usually 1, at most 3. Copy chunk_ids exactly from data/chunks.jsonl; every id must exist there.
3. If the same answer appears in another document too (e.g. a circular repeating a rule), list the primary one in
   gold_chunks and name the others in "note" as "also: <chunk_id>, ...".
4. claims: the full answer as 2-5 short, standalone, checkable English sentences, each supported by the gold chunks'
   text. Include the provision number and every condition, limit or date a CA would need to quote. No claim may need
   knowledge outside the gold chunks.
5. Spread: at most 2 rows from any one document (for the CGST Act and the CGST Rules: at most 2 rows per section or
   rule). Cover act, rules, circulars and instructions; at least 4 rows must have a table chunk (kind = table) as gold.
6. Avoid questions whose answer depends on whether a circular was later withdrawn or changed; that check isn't built yet.
7. At most 2 rows on section 2 definitions.

SELF-CHECK BEFORE YOU FINISH (write and run a small script, do not save it in the repo)
- 40 rows, ids codex-001..codex-040, category counts as above, valid JSON on every line.
- Every gold chunk_id exists in data/chunks.jsonl.
- No document breaks the spread rule.
- For every claim, print the gold chunks' text next to it and confirm it is supported. Fix or drop any that is not.
Then print a table: id, category, gold chunk ids, note. List any row you are unsure about and why.
```
