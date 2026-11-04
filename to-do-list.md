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
Where it stands: Act units done (act.py); ICAI footnotes done (icai.py steps 1–2); NOT done: rule units (A4 step 3 on), circulars (A5), runner (A6), eval (A7).
Pending decision: the IGST, UTGST and Compensation Acts now come from India Code (known_docs.json keeps only the CGST and IGST Rules from ICAI). Download them by hand to `docs/`, check each copy includes the Finance Act, 2026 (ICAI is as of 31-03-2026; an older India Code copy would hold text since omitted); if one doesn't, take that Act from ICAI or mark its `as_of`. Links: indiacode.nic.in handles 7773 (IGST), 7776 (UTGST), 7772 (Compensation).

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
- [x] `scripts/03_split_chunk.py`: manifest → the right splitter per `doc_type` → `data/units/*.jsonl`; prints counts per `doc_type` and every file with warnings. The choice lives in `src/taxowl/splitting/run.py` (`split_file(file, doc_type)`), so the upload path and the server call the same function. First run: 314 files, 4,224 units, 248 tables; 38 files with warnings, 1 failed (175/07/2022); output identical to the splitters' own runs (diff 0)

**A7. Splitter eval** (component eval, for the quality page)
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
- [ ] Extractor: join a table split across pages when the two pages used different readers (Rules p.260 + p.261)
- [ ] Extractor: a merged cell that crosses a page break is not filled down (Rules p.358–359, table-15: rows 5–7 share "Amount equivalent to twenty-five per cent of tax evaded"; rows 6–7 came out empty). Gemini sees one page at a time. Likely fix, together with the 53 made-up headings: show Gemini both pages of a split table at once. Not "fill empty cells from above": some cells are really empty
- [ ] Font as a signal (bold headings, small footnotes): try first in the upload splitter
- [ ] Exact positions (bbox) per unit; structured citation fields; structured `amended_by`
- [ ] Mixed upload documents (petition + annexed order + forms) split per region
- [ ] Embedding experiment: bge-small vs InLegalBERT (+ synthetic-query training), in `plans/plan_ingestion.md` section D
