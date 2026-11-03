# Stage 2: Splitting and Chunking — plan

## Context
Extraction is done. Each PDF becomes one `ExtractedDoc` JSON in `data/ingested/`, holding page text, tables and a quality report (`src/taxowl/schema.py`). The next step turns those into **chunks**: the pieces we search and cite. We do this in two separate steps, because they answer different questions:

| Step | Question it answers | Output |
|---|---|---|
| **Splitting** | *Where does the law itself divide?* (section, rule, paragraph, table row) | **Units**: one per section, rule or paragraph, with its exact citation |
| **Chunking** | *What size and shape is best for search?* | **Chunks**: units cut or joined to fit the embedder, with context added |

**Why keep them apart:** splitting is about being *correct* (did we find section 16 and all of it?). Chunking is about being *useful* (is the piece the right size, does it carry its heading?). Keeping them apart means each gets its own test, and later we can try a different chunk size without touching the splitter. (Interview line: *"Structure first, size second."*)

**Already decided** (`plans/plan_ingestion.md`, section C): Act → by section; Rules → by rule (Part B forms left out); circulars → by numbered paragraph, with the subject in every chunk; tables → a row view plus a table view; footnotes become `amended_by` / `history` metadata, and "Prior to substitution…" text stays out of the embedded text.

**Time limit:** splitting about 2 days, chunking about 1 day. The bar is ~95% correct on a held-out set, then move on (memory: good enough, then move).

---

## Step 0: Before starting (½ hour)
- [ ] Commit the restructure that's still pending (the `ingestion/` package move and the edited files).
- [ ] Run the extractor over the **whole corpus**. Right now `data/ingested/` holds only 76 circulars of 267, so the splitter would be built on part of the data. (`pipeline.py --corpus`; the user runs it.)
- [ ] Count the files flagged by the quality check, so we know which ones get `quality_ok = False`.

---

## Part A: Splitting (document → units)

### A1. The data shape
- [ ] Add a `Unit` to `src/taxowl/schema.py`: `doc`, `location` ("section 16(2)", "rule 36", "para 4"), `heading`, `text`, `page_start`/`page_end`, `parent` (e.g. Chapter V), `amended_by` / `history` (from footnotes), `table_id`.
  *Why a new shape:* a Unit is "what the law says", before any search decisions. A Chunk keeps its current definition.

### A2. One splitter per document family
Each splitter is a small file of pattern rules. Rules suit this text: legal documents number their own parts, and the numbers are the citation.

| File | Splits by | Hard parts to handle |
|---|---|---|
| `src/taxowl/splitting/act.py` | Section (`16. Eligibility…––`) | Inserted sections (11A, 74A, 128A); "Omitted" sections (42, 43); `1[ … ]` amendment markers and `*\n*` lines stripped; page footnotes ("1. Ins. by Act 8 of 2023…") moved into `amended_by`; Schedules I–III; chapter headings kept as `parent` |
| `src/taxowl/splitting/rules.py` | Rule (`Rule 56. Maintenance of…`) | The ICAI PDF also holds the Acts and the IGST material: take the **CGST Rules part only** (find its page range once and write it down). "Prior to substitution, it read…" goes to `history`, never into `text`. Leave out the Part B forms. |
| `src/taxowl/splitting/circulars.py` | Numbered paragraph (`2.`, `2.1`) | Subject line found once and kept for every unit; letterhead, addressee and signature dropped; instructions and notifications use the same splitter; tables become their own units, linked by `table_id` |

- [ ] Write `act.py`, then run it and look at the output with the user before moving on.
- [ ] Write `rules.py`.
- [ ] Write `circulars.py` (covers instructions and notifications too).
- [ ] Text that fits no pattern is **never dropped**. It becomes a "preamble" or "other" unit and is counted. Silent loss was the worst failure in extraction, so it gets the same rule here.

### A3. Self-checks (run on every document, automatically)
The same idea as the extractor's self-check: the code checks its own output, so nobody has to read 314 files.
- [ ] **Nothing lost:** every word in the ExtractedDoc lands in some unit (or is on the drop list: headers, signatures, footnote markers).
- [ ] **Numbering in order:** Act sections 1→174 with no gaps except the known omitted and inserted ones; rule numbers rise; circular paragraphs go 1, 2, 3…
- [ ] **Expected counts:** the Act gives ≈174 sections plus the inserted ones; every circular gives at least one paragraph.
- [ ] **No old text in the law:** no unit's `text` contains "Prior to substitution".
- A document that fails a check is flagged, not hidden (it gets `quality_ok = False`).

### A4. Eval for the splitter (component eval, for the quality page)
- [ ] **Gold set:** about 10 documents picked to cover the hard cases (the Act's s.16 and s.74A, an omitted section, one long rule with "prior to substitution", circular 238/32/2024 with its long table, a scan circular, an instruction). The answers are written from the **PDF**, not from the splitter's output, and the user checks them.
- [ ] Score: % of units with the right boundaries; % of units with the right citation (`location`); words lost (must be 0).
- [ ] **Held-out draw** (new seed, documents the rules weren't built on). This is the number that goes on the quality page; the gold score may be overfitted.

**Splitting is done when:** held-out ≥ 95% right boundaries and citations, 0 words lost, and every failure is flagged.

---

## Part B: Chunking (units → chunks)

### B1. Decide the size (with the user, from data)
- [ ] Measure the unit lengths, in tokens of the embedding model (bge-small reads at most **512 tokens** and ignores the rest). Print the spread: how many units are too long, and how many are tiny.
  *Why measure first:* if 95% of units already fit, chunking stays almost trivial. If many sections are long, the cutting rule matters more.

### B2. The chunker: `src/taxowl/chunking/chunker.py`
- [ ] **Long units are cut along the law's own lines:** sub-section (1), (2) → clause (a), (b) → sentence, only as a last resort. Each piece keeps its own citation ("section 16(2)(b)").
- [ ] **Tiny units are joined** to the next unit of the same parent (e.g. a two-line circular paragraph) so they aren't useless on their own. They are never joined across sections or rules.
- [ ] **Context header** on every chunk: `CGST Act, s.16 Eligibility and conditions for taking input tax credit` or `Circular 238/32/2024 — <subject> — para 4`. This header goes into `text` (it helps both search and the LLM), and its tokens count toward the size limit.
- [ ] **Tables:** a row view (one chunk per row, every value with its heading: `Issue: … Clarification: …`) and a table view (the table cut into pieces, with headings repeated in each). Nested tables use the saved HTML.
- [ ] **Room for small or local LLMs** (decided 2026-11-03). The answer step may want to give the LLM a chunk's whole section ("search small, read big"). Some sections are huge (s.2 has 120+ definitions), and long input is slow on a laptop and makes answers worse. So: (a) every definition in s.2 is its own unit, and saves its term ("goods", "money"), so the answer step can bring in the definitions a definition uses (2(52) "goods" → "money", "securities", "actionable claim") instead of all 120; (b) every chunk and unit records its token count. The answer step later uses these counts to choose: whole section if it fits the budget, otherwise the chunk plus its neighbours. The budget number is measured later, with the local vs cloud choice.
- [ ] Fill every `Chunk` field: `chunk_id` stable (re-running makes no duplicates), `official_url` from the manifest, `status = in_force` until the day-3 detector runs, plus `ocr`, `quality_ok` and `source_sha256`.

### B3. The runner
- [ ] **One script, two steps** (decided 2026-11-03): `scripts/03_split_chunk.py` calls `split()` then `chunk()`; no file saved in between. The two steps stay separate functions with separate tests, so a bad chunk can be traced to the step that made it, and the chunk size can change without touching the splitter.
- [ ] It reads `data/ingested/*.json` and writes `data/chunks.jsonl`, then prints the count per `doc_type` and the length spread. With a `__main__` guard; the user runs it.

### B4. Checks for the chunker
- [ ] No chunk is over the token limit; none is empty; every `chunk_id` is unique.
- [ ] Every chunk has `official_url`, `status` and `location`.
- [ ] Cutting and joining loses nothing: all chunks of a unit, put back together, equal the unit's text.
- [ ] **Spot-check 10 random chunks** against the PDF page (the user does this; section E of plan_ingestion).

**Chunking is done when:** all of the checks pass and the 10 spot-checks look right. Retrieval quality (does the right chunk come back?) is measured later with the evalset, not here.

---

## Not in this stage
- Embedding and loading into Chroma (section D of `plan_ingestion.md`), which comes next.
- The withdrawal detector (day 3); `status` stays `in_force` until then.
- Trying different chunk sizes. That's a later experiment, once the evalset exists to judge it.

## Files
| New | Changed | Reused |
|---|---|---|
| `src/taxowl/splitting/{act,rules,circulars}.py`, `src/taxowl/chunking/chunker.py`, `scripts/03_split_chunk.py`, `eval_results/gold/splitting_gold.json`, `eval_results/check_splitting.py` | `src/taxowl/schema.py` (add `Unit`), `plans/plan_ingestion.md` (point to this file), README "Where things are" | `ExtractedDoc` / `Table` / `Chunk` (schema.py); `docs/manifest.jsonl` for metadata; the gold → held-out → score pattern from `check_ingestion.py` |

## How we work through it
One splitter at a time: explain → write → the user runs it → look at the output together → next one. Stop after each to-do and ask before going on.
