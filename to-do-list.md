# To-do: splitting and chunking (2026-11-03)

Detailed reasoning: `plans/stage2_splitchunk.md`. This file is the working checklist, up to chunking.
How we work: one step at a time. Explain → write → the user runs it → look at the output together → next.

## The shape: two pipelines, shared ends

```
PDF ─► Extractor (done, shared) ─► ExtractedDoc
          ├─► FOUNDATION pipeline: act.py / rules.py / circulars.py  (we run it; type from the manifest)
          └─► UPLOAD pipeline: upload splitter                        (user's petitions, SCNs, orders; after v1)
                    ▼
       Unit ─► Chunker ─► (embed, store: next stage)                  (shared code)
                    ▼
       public store (corpus)   |   private store per user (uploads, never mixed)
```

- Law documents (Act, Rules, circulars, instructions, notifications) come only through the foundation pipeline, which we control. Uploads are the user's own case papers.
- Rules everywhere: text only from the PDF, never from a model; nothing silently lost; a model (Jev) may only decide, never write text; no invented legal citation.

## Done
- [x] Extractor for corpus + uploads (gold 94.5%, held-out 97.8% / 97.9%)
- [x] Stage 2 plan (`plans/stage2_splitchunk.md`)
- [x] `Unit` in `src/taxowl/schema.py`
- [x] `act.py`: 337 units, self-check all passed
- [x] Extractor fix: justified words joined back into one line (scores unchanged)

## A. Foundation pipeline: splitting (now)

**A1. Unit: add fields** (before more splitters are built on it)
- [x] `unit_id`: stable, e.g. `act-12-of-2017:section-16`
- [x] `source_sha256`: which version of the PDF it came from
- [x] `token_count`: bge tokens (for the chunker and the answer step's context budget)
- [x] `warnings`: list of short notes (skip in numbering, odd boundary …)
- [x] `table_ids` (list) in place of `table_id`: a paragraph can hold more than one table
- [x] Update `act.py` to fill them; re-run, still all passed

**A2. act.py: tidy for the new rules**
- [x] File name passed in, not hard-coded
- [x] A skip in the section numbers becomes a warning, not a silent pass
- [x] Two new self-checks: no text appears twice; every section unit starts with its own number
- [x] Re-run: all passed (before/after diff: 337 units, 0 changes)

**A3. Known-file facts in config, not in code**
- [x] `src/taxowl/splitting/known_docs.json`: the ICAI PDF's five parts and their pages (checked by the user in Preview)
- [x] `known_parts()` reads it; `finish(..., part=)` puts the part's name in every id (`igst-rules-2017:rule-2`), so two parts never collide
- [x] Scope (decided 2026-11-03): IGST Act + Rules, UTGST Act and the Compensation Act join v1, all from ICAI (simple: one source, one format, as of 31-03-2026)

**PAUSED 2026-11-03 (user's call): splitter left here for now; come back if later stages show problems.**
Resumed 2026-11-04: rule units, circulars and the runner are done (A4-A6 below); only the eval (A7) is left.
Decided 2026-11-04 (user): the IGST, UTGST and Compensation Acts come from ICAI for now (known_docs.json: IGST Act p.364-391, UTGST Act p.404-423, Compensation Act p.424-435; split by icai.py, all self-checks passed: 28 + 29 + 15 sections). Later, if wanted: swap for India Code copies (indiacode.nic.in handles 7773 IGST, 7776 UTGST, 7772 Compensation), checking each includes the Finance Act, 2026. Each Act schedule is now one `schedule` unit (Compensation Act p.434-435, its cess rates, was inside section 14). Left out on purpose (user, 2026-11-04): the Compensation Act's running title ("The Goods and Services Tax (Compensation To States) Act, 2017", top of each page) stays in the text of 8 of its 17 units, because the header rule doesn't know it; the self-check uses the same rule, so its "passed" doesn't cover this. Why not fixed: citations and the law's meaning don't change, search barely does (the chunk header carries the Act's name anyway), and the general fix (a line repeating at the top of 3+ pages is a header) touches every ICAI part. Cost of leaving it: a stray line mid-text, possibly in a verbatim quote or at a chunk cut. Fix if retrieval results show it. Left out: the Constitution (101st Amendment) Act, 2016 (p.436-440).

**A4. icai.py: the ICAI Rules (CGST Rules, IGST Rules)** — DONE 2026-11-04
- [x] **Step 1, footnotes:** done 2026-11-03. Pages whose footnote numbers match their marks: built-on parts 96.7–100%, held-out (ICAI's copy of the CGST Act, p.20–181, never looked at) 95.9%; "Prior to" in law text: 0 in both. The mismatches left are the check's own blind spots: marks inside tables, glued marks (`Authority21[`), `30(b)`, nested `6[7[`. For later steps: `clean()` must handle glued marks, and marks inside a table give that table unit its `amended_by`. The text rule finds the first numbered footnote ("10 Inserted vide …") and takes everything from there to the page end. Font size (read from the PDF inside `icai.py` only; the extractor is not changed) is checked only just above that line, where a long footnote carried over from the previous page sits with no number (23 pages, 335 lines; the text rule alone gets 96.9%). Small text elsewhere on the page is never used. Self-checks: a table inside the footnote area, "Prior to" left in the law text
- [x] **Step 2, footnotes → numbers, marks cleaned:** done 2026-11-03. Each footnote split into `said` (what changed → `amended_by`) and `old` ("Prior to …" → `history`). Symbol footnotes (`*`, `@`, `#`) are notes on another footnote's old text, joined to it (look back first, 3 pages either side; stars after a digit or `[` are deleted words, not marks). `act.clean()` now takes a mark pattern and keeps a space at glued marks (`14[six]months`); act.py output unchanged (diff 0). Law marks matched: 583/583 in the five parts, 348/351 held-out; checks 0 everywhere. Left as warnings on purpose (fixing them would be overfitting): p.291 `[@@`, p.341 `:@]`, p.292 `30(`, held-out `^1[`, `16[1]`, `6[7[`
- [x] **Step 3, rule units:** done 2026-11-04. CGST Rules 212 rules + 5 definitions + 1 other; IGST Rules 9 rules + 1 other; all self-checks passed (no mark, old text or running header left in text; nothing lost or doubled; every unit starts with its own number; ids unique). Saved to `data/units/GST Act(s) and Rule(s)-Bare Law.pdf.jsonl`. Held-out (ICAI's CGST Act split by the same code, compared with act.py's India Code sections): **188/190 on the first, blind run**; 190/190 after allowing a mark in two more places (`15Section 51.`, `Section 13[168A.`), so 100% is a tuned number, 98.9% is the held-out score. Tokens: median 238, 55 of 228 over 512 (rule 138 e-way: 3,577), for the chunker
- [x] **Step 4, tables:** done 2026-11-04, 14/14 against the user's answers (10 current tables linked to their rule and saved cleaned in `data/units/<file>.tables.jsonl` with their unit_id; 4 old ones, 8pt in footnotes, into history: rule 7's p.190 and rule 138's p.331/332/334). Plan (decided 2026-11-04: finish the splitter, go on to retriever + generator, then fix by what the results show):
  - link each table to the rule that starts above it on its page; gold from the user (p.197 → 10B, p.215 → 31D, p.260–261 → 61, one table, p.275 → both 83A)
  - the three old e-way tables (8pt, p.331/332/334) → rule 138's history, never current
  - clean the marks in table cells (`Up to 4[200 km.]`)
  - known extractor gap, not fixed now: 53 of 561 corpus tables (all Gemini) have made-up headings "Column 1 | Column 2"; 5 are surely a table split across pages (Rules p.260–261). The user is checking them by hand: `eval_results/tables_made_up_headings.md`
- [x] The original checklist, all covered by steps 1–4: units start `Rule N.` (typos too); one unit per rule, rule 2 per definition with `term`; running headers and chapter titles out, chapter into `parent`; "Prior to …" into `history`; old tables into `history`; forms outside the page range; tables linked by `table_ids` (their row views are made by the chunker, B5); self-check per part, ids unique. The Acts left this file: they come from India Code (act.py)

**A5. circulars.py** (covers instructions and notifications) — DONE 2026-11-04
- [x] Subject line found once (`Subject:`, `Sub.-`, `Sub–`, up to 4 lines) and kept as every paragraph's `parent`
- [x] Letterhead + addressees + "Madam/Sir," → one "other" unit; signature → one "other" unit, copy-to list after it → another; one unit per annexure
- [x] One unit per numbered paragraph (`2.`, `2.1`); the unnumbered first paragraph is "para 1"; `(i)` stays inside its paragraph. Starts chosen as the longest run of numbers in order, so a numbered list of issues at the top (177/09/2022, 164/20/2021) stays inside para 1. Tables linked to the paragraph above them (238 tables), saved in `<file>.tables.jsonl`
- [ ] Scans (OCR) and the flagged files → `quality_ok = False`: carried through by the chunker (B6), from the ExtractedDoc
- [x] Self-check on all 312 files: 311 passed (3,659 units). Left on purpose: 175/07/2022 (a stray "05." line on p.3). Warnings: 30 files with a gap in numbering (10 have the missing paragraph inside a table the extractor made from a two-column page; some are CBIC's own typos, e.g. 177/09/2022 prints 15.2 twice), 8 with no numbered paragraph (corrigenda), 3 with no subject line. Not fixed, kept as warnings: numbers glued to text (`2.1Sanction`, `11.Further`) and with no dot (`2 In this regard`), 3–5 files. For the answer step: show the para number only when the file has no warning; otherwise circular + page

**A6. Runner** — DONE 2026-11-04
- [x] `scripts/03_split_chunk.py`: manifest → the right splitter per `doc_type` → `data/units/*.jsonl`; prints counts per `doc_type` and every file with warnings. The choice lives in `src/taxowl/splitting/run.py` (`split_file(file, doc_type)`), so the upload path and the server call the same function. First run: 314 files, 4,224 units, 248 tables; 38 files with warnings, 1 failed (175/07/2022); output identical to the splitters' own runs (diff 0). With the three ICAI Acts: 314 files, 4,300 units, 249 tables; same 38 warned, same 1 failed

**A7. Splitter eval** (component eval, for the quality page) — after the retriever (decided 2026-11-04)
- [ ] Act and Rules: the contents lists are free gold for boundaries
- [ ] Circulars: ~8 dev documents + ~10 held-out whole documents, answers written from the PDF, checked by the user
- [ ] `eval_results/check_splitting.py`: boundary precision / recall, citation accuracy, coverage, and "catastrophic" errors counted separately (two sections merged, one cut in half, old text in current text, table on the wrong unit)

## B. Foundation pipeline: chunking (now, after A)

- [ ] **B1. Measure** unit lengths in bge tokens; decide the size together (bge reads at most 512)
- [ ] **B2. Cut long units** along the law's own lines: sub-section → clause → sentence (last resort); each piece keeps its own citation ("section 16(2)(b)")
- [ ] **B3. Join tiny units** to the next one with the same parent; never across sections or rules
- [ ] **B4. Context header** in every chunk's text: `CGST Act, s.16 Eligibility …` / `Circular 238/32/2024 — <subject> — para 4`
- [ ] **B5. Tables:** row view (`Issue: … Clarification: …`) and table view (pieces with headings repeated); nested tables use the saved HTML
- [ ] **B6. Fill every Chunk field:** stable `chunk_id`, `official_url` from the manifest, `status = in_force` until the withdrawal detector, `ocr`, `quality_ok`, `source_sha256`, `token_count`; `history` and `amended_by` never embedded
- [ ] **B7. Checks:** none over the limit, none empty, ids unique, every chunk has `official_url` / `status` / `location`, a unit's chunks put back together equal the unit
- [ ] **B8. Spot-check 10 random chunks** against the PDF (user)
- [ ] Commit; next stage: embed + public store

## R. Embeddings, store and retriever — DONE 2026-11-07 (commit eb97fec, pushed)

- [x] **R1. Embedder + store:** bge-small via LangChain (`retrieval/embedder.py`, `store.py`), Chroma collection `corpus-bge-small`; `scripts/04_embed_store.py` rebuilds the whole store each run (4,717 chunks, ~1.3 min on the Mac)
- [x] **R2. Citation reader** (`retrieval/citations.py`): sections, rules, circulars named in a question; no law named → CGST Act, `law_assumed=True`. Blind scores 36/40, 29/30, 48/50 (gold in `eval_results/gold/citations_*.jsonl`)
- [x] **R3. Exact lookup** (`retrieval/lookup.py`): a citation → its chunks, ranges handled (`section 76(4)-(8)`), circulars by number parts + their corrigenda. Checks 1696/1696, 266/266
- [x] **R4. Retriever** (`retrieval/retriever.py`, LangChain `BaseRetriever`): exact chunks first (max 20, shared across citations), then 5 by meaning; labels `found_by`, `citation`, `law_assumed`, `distance`
- [x] **R5. Check by eye** (`experiments/try_search.py`, 10 questions): 16(4), 36(4) now rank 1; rule 7 + its table exact; meaning search good on 5–8
- [ ] **R6. Retriever eval** (recall@5, MRR) on the user's evalset — at eval time, together with A7
- [ ] **R7. Plain-language misses** left on purpose until the evalset measures them: 17(1) (machine partly personal use), 76/32 (GST collected by mistake). Q1's meaning chunks all came from one circular: watch at eval
- [ ] **R8. Embedding comparison** at eval time (list in "Later / not now")
- [ ] Later, after v1: split into a standalone `legal_retriever` module (no GST facts in the generic logic, so the split stays cheap)
- [ ] More misses seen in the generator trial (Codex questions, 2026-11-07): hard-02 (162/18/2021 para 3, got sections 73/74), super_hard-01 (Hinglish, 16(2) + 36(4) not found), super_hard-03 (158/14/2021, got 95/14/2019, and the answer from it was wrong)
- [ ] Exact chunks flood the context: a question that only mentions "section 73" brings all of section 73 (10 chunks, ~6k tokens). Lower EXACT_CHUNKS or keep only chunks that match the asked sub-section, measured with the evalset

## G. Generator (answer step) + UI — built 2026-11-07

Plan: `plans/stage7_generator.md`. Same shape as `evals_project` (generator + pipeline), differences explained in each file.

- [x] **G1. `answer/generator.py`:** gpt-4o-mini (OpenRouter) and qwen2.5 7B (Ollama), temperature 0; faithfulness-first prompt, `[S#]` markers, one refusal sentence, Markdown, reply in the question's language; `generate()` and `generate_stream()`; cost from OpenRouter's own reply
- [x] **G2. `answer/pipeline.py`:** retrieve → label (`[S1] <doc>, <location>, p.N`, made by code, not the model) → generate → check; the "assumed law" line is chosen by code; token budget 6,000 for the local model
- [x] **G3. `answer/check.py`:** made_up_source, cites_or_refuses, no_new_citation (citation reader + lookup), mixed_refusal, says_assumed
- [x] **G4. `app.py` (Streamlit):** one question, both models streamed one after the other, time / cost / checks, sources with links. `uv run streamlit run app.py`
- [x] **G5. Trial** (`experiments/try_answer.py`): 10 try_search questions, both models, 0/10 failed checks after two fixes ("assumed" said everywhere; a guess followed by the refusal). Codex's 25 questions (`eval_results/gold/answer_trial_questions.jsonl`, sources and quotes checked against the chunks), cloud: easy 5/5, medium 5/5, source found 18/22, refusal right 20/25, ~3 s and ~₹0.04 per answer
- [ ] **G6. Over-refusal:** hard-01 (54(3): the answer is "no"), hard-05, blunder-04 (should correct the premise) refused though the source was there. Prompt: "no" and a correction are answers; refuse only when the sources don't touch the topic
- [ ] **G7. hard-03 no_new_citation FAIL** ("section 73" with only the circular cited): likely a false alarm in the check, look at the circular's text
- [ ] For the judge at eval time (rules can't catch these): an added line not in any source (Q1 "ensuring registered persons are aware"); local answers that miss items (Q8: 3 of 4 rates); local over-refusal (Q6)
- [ ] Small: instruction labels with no number are cut mid-word ("…under Rule 86A of t"); both models side by side in the UI (threads)

## C. Upload pipeline, up to chunking (after v1)

- [ ] **C1. Upload splitter:** headings (FACTS, GROUNDS, PRAYER, ANNEXURE P-1 …) + numbered paras; `location` = "para 12", `parent` = "Grounds", page; never a made-up section citation
  - Footnotes in uploads (ChatGPT review, 2026-11-03): font size is one signal, not the decision. Add the separator line above footnotes, position near the page bottom, a footnote carried over from the previous page, and the number sequence. Classify blocks, not lines. When unsure, mark the block `uncertain_footnote` and keep it out of the current-law text. Test on 20–30 labelled upload-like PDFs (3–5 pages each): footnote precision/recall, carry-over accuracy. Scans have no font, so they use the text rule plus a warning
- [ ] **C2. Law references:** find "section 16(2)(c)", "rule 36(4)", "Circular No. 183/15/2022" and link them to corpus units
- [ ] **C3. Annexures** that are corpus documents (e.g. an annexed circular) → link to the corpus copy, don't split again
- [ ] **C4. Self-checks + warnings** shown to the user (nobody reviews uploads by hand)
- [ ] **C5. Jev as tie-breaker** for unclear headings or boundaries, only with the user's consent (petitions are private; Jev is an external API). Measured: ~$0.00002 per decision, ~0.5 s
- [ ] **C6. Same Unit + chunker**; chunks go to a private, per-user, deletable store (next stage)
- [ ] **C7. Eval** on the private petitions in `data/private/` (gold stays private, never in the repo)

## Later / not now
- [ ] Tests (`tests/` folder) and CI: after the project is built (user, 2026-11-04). Until then each splitter's self-check is the guard
- [ ] Extractor: join a table split across pages when the two pages used different readers (Rules p.260 + p.261)
- [ ] Extractor: a merged cell that crosses a page break is not filled down (Rules p.358–359, table-15: rows 5–7 share "Amount equivalent to twenty-five per cent of tax evaded"; rows 6–7 came out empty). Gemini sees one page at a time. Likely fix, together with the 53 made-up headings: show Gemini both pages of a split table at once. Not "fill empty cells from above": some cells are really empty
- [ ] Font as a signal (bold headings, small footnotes): try first in the upload splitter
- [ ] Exact positions (bbox) per unit; structured citation fields; structured `amended_by`
- [ ] Mixed upload documents (petition + annexed order + forms) split per region
- [ ] Embedding experiment: bge-small vs InLegalBERT (+ synthetic-query training), in `plans/plan_ingestion.md` section D
  - At eval time (added 2026-11-07), on the same evalset, each model in its own collection, compare recall@5 and MRR:
    `BAAI/bge-small-en-v1.5` (now), `BAAI/bge-base-en-v1.5`, `BAAI/bge-m3` (also gives keyword scores, like BM25),
    `Qwen/Qwen3-Embedding-0.6B`, `law-ai/InLegalBERT`, and OpenAI `text-embedding-3-large` via OpenRouter (cloud: costs per query, needs internet, data leaves the machine)
  - Scores from two models can't be compared, only their rankings on the evalset. Run each twice to see the noise
  - Download before (slow net): `uv run --no-sync hf download <model>` for each local model
