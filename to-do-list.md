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
- [ ] One small config file for facts about one file only (first entry: the CGST Rules' page range inside the ICAI PDF)

**A4. rules.py** (look at the real pages together first)
- [ ] CGST Rules pages only (from A3)
- [ ] One unit per rule (`Rule 56. Maintenance of…`); rule 2 split into definitions with `term`
- [ ] "Prior to substitution, it read …" → `history`, never in `text`
- [ ] Old tables (e-way bill copy on p.331–334?) → `history`; check which copy is old first
- [ ] Part B forms left out (or titles only)
- [ ] Tables become units, linked by `table_ids`
- [ ] Self-check: rule numbers in order, nothing lost, nothing double, no "Prior to substitution" in any `text`

**A5. circulars.py** (covers instructions and notifications; look at real pages first)
- [ ] Subject line found once and kept for every unit
- [ ] Letterhead, addressee, signature, copy-to list → dropped or one "other" unit (never silently)
- [ ] One unit per numbered paragraph (`2.`, `2.1`, `(i)`); tables as their own units
- [ ] Scans (OCR) and the 64 flagged files → `quality_ok = False` carried through
- [ ] Self-check on all 312 files; list the ones that fail

**A6. Runner**
- [ ] `scripts/03_split_chunk.py`: manifest → the right splitter per `doc_type` → `data/units/*.jsonl`; prints counts per `doc_type` and every file with warnings

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
- [ ] **C2. Law references:** find "section 16(2)(c)", "rule 36(4)", "Circular No. 183/15/2022" and link them to corpus units
- [ ] **C3. Annexures** that are corpus documents (e.g. an annexed circular) → link to the corpus copy, don't split again
- [ ] **C4. Self-checks + warnings** shown to the user (nobody reviews uploads by hand)
- [ ] **C5. Jev as tie-breaker** for unclear headings or boundaries, only with the user's consent (petitions are private; Jev is an external API). Measured: ~$0.00002 per decision, ~0.5 s
- [ ] **C6. Same Unit + chunker**; chunks go to a private, per-user, deletable store (next stage)
- [ ] **C7. Eval** on the private petitions in `data/private/` (gold stays private, never in the repo)

## Later / not now
- [ ] Extractor: join a table split across pages when the two pages used different readers (Rules p.260 + p.261)
- [ ] Font as a signal (bold headings, small footnotes): try first in the upload splitter
- [ ] Exact positions (bbox) per unit; structured citation fields; structured `amended_by`
- [ ] Mixed upload documents (petition + annexed order + forms) split per region
- [ ] Embedding experiment: bge-small vs InLegalBERT (+ synthetic-query training), in `plans/plan_ingestion.md` section D
