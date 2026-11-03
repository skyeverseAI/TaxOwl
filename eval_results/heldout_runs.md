# Held-out runs: honest accuracy on unseen pages

Every run scores the same extractor (no fixes between runs) on 10 freshly drawn pages that were never used to build or fix it. 5 table pages, 1 scan, 2 plain, 1 Act, 1 Rules each. Gold written from page images, then each phrase/number/cell checked against the raw PDF text layer.

Command per run: `uv run eval_results/check_ingestion.py data/ingested --gold eval_results/gold/ingestion_heldout_<seed>.json`

## Scores

| Run | Seed | Score | Accuracy |
|---|---|---|---|
| earlier | 2026 | 152/164 | 92.7% |
| earlier | 2027 | 145/157 | 92.4% |
| earlier | 2028 | 178/204 | 87.3% |
| #1 | 2029 | 172/186 | 92.5% |
| #2 | 2030 | 192/218 | 88.1% |
| #3 | 2031 | 142/216 | 65.7% |
| #4 | 2032 | 154/159 | 96.9% |
| #5 | 2033 | 129/143 | 90.2% |
| **#1-#5 pooled** | | **789/922** | **85.6%** |

Mean of the five runs: 86.7%. Range 65.7-96.9%: one bad table page can sink a run, because table checks are many per page.

## What pulled each run down

Numbers in brackets = failed checks.

### Run #1 (seed 2029): 92.5%
- **36/10/2018 p.7 [12]**: blank form with two heading levels (Details of the Entity -> Name | UIN; Time Period -> From | To). Got 11 columns instead of 10 and the heading words shifted into the wrong columns ('Name of the' glued onto Central Tax, State Tax, ...). *Multi-level headings.*
- **Rules p.301 [2]**: chapter running header ('Ch-X : Refund', 'Rules 89-97A') not removed. *Known.*

### Run #2 (seed 2030): 88.1%
- **26/26/2017 p.10 [16]**: coloured grid with three heading levels. The third level (Confirmed Submission / Cash Ledger Updated / ...) became data row 1, so every row shifted by one; and the Stage 3-4 merged cell's text ('Return was filed.') was copied down into rows where it doesn't belong. *Multi-level headings + horizontal merged cell filled vertically.*
- **72/46/2018 p.3 [7]**: table whose rows start with 'Case 1', 'Case 2' (not a serial number). Both data rows were swallowed into the heading row: 0 data rows, the dates sit in the headings. *Rows not recognised as data.*
- **Rules p.242 [2]**: chapter running header not removed. *Known.*
- **Instruction 04/2022 (OCR) [1]**: 'hereby' read as 'hercby'. *OCR noise.*

### Run #3 (seed 2031): 65.7%
- **98/17/2019 p.2 [39]**: two coloured tables. Background colour boxes read as table lines: 9 and 12 columns instead of 4 and 3, every heading and cell in the wrong column. *Filled rectangles read as grid lines (same as 179 in run 2028).*
- **170/02/2022 p.7 [25]**: continuation page of a numeric ITC table. All 6 rows on p.7 were glued into the last row of p.6, and different columns' numbers merged into one cell ('125,500 10,000 2,64,500'). No row starts on p.7, so even the numbers can't be found there. *Continuation join glued real rows.*
- **51/25/2018 p.2 [8]**: scanned page with an embedded text layer; grid read as 5 columns instead of 2. *Scan-with-text-layer grid.*
- **Rules p.224 [2]**: chapter running header not removed. *Known.*

### Run #4 (seed 2032): 96.9%
- **24/24/2017 p.2 [2]**: two blank forms extracted with the right column counts (5 and 13) but no data rows, so the checker can't place them on the page. *Checker limitation, not an extractor error.*
- **Rules p.214 [2]**: chapter running header not removed. *Known.*
- **Instruction 01/2024 (OCR) [1]**: 'initiated' read as 'initioted'. *OCR noise.*

### Run #5 (seed 2033): 90.2%
- **Corrigendum to 76/50/2018 p.1 [5]**: 3-column table read as 9 columns, each text line a row (8 rows instead of 1). *Grid lines from fills / line = row.*
- **02/2021-22 ISP p.4 [3]**: scanned page with an embedded (and itself error-prone) text layer; 6-column table read as 2 columns. *Scan-with-text-layer grid.*
- **Rules p.253 [2]**: chapter running header not removed. *Known.*
- **Instruction 01/2020-21 (OCR) [2]**: a wrapped code number moved to the front of the next line ('1.2 Code 1.2'). *OCR line order.*
- **106/25/2019 p.7 [1]**: blank 24-column form with no data rows; checker can't place it. *Checker limitation.*
- **Instruction 04/2024 p.2 [1]**: the signature line 'Commissioner' was dropped by the header/footer remover (a real content line lost). *Header stripper false positive.*

### Earlier run (seed 2028): 87.3%
- **179/11/2022 p.4 [14]**: white/grey fill rectangles behind each text line read as grid lines: 5 columns x 6 rows instead of 3 x 3, column 1 copied down. `lines_strict` gets it right. Not flagged by the self-check.
- **228/22/2024 (OCR) [7]**: superscript ordinals dropped ('17th' -> '17'), stray 'S.l'. *OCR noise.*
- **16/16/2017 [2]**: checker bug: a comma before 'S.No. 24' made it look like the tail of a bigger number. *Checker.*
- **Act p.55 [1]**: PDF stores '––' (two en dashes), gold had '—'. *Checker/gold dash style.*
- **Rules p.350 [2]**: chapter running header not removed. *Known.*

## Causes across runs #1-#5 (133 failed checks)

| Cause | Failed checks | Runs hit | Fixable how |
|---|---|---|---|
| Filled/coloured rectangles read as grid lines (extra columns, line = row) | 44 | #3, #5 (+2028) | prefer `lines_strict` when it gives fewer columns and keeps every word |
| Multi-level headings / merged heading cells | 28 | #1, #2 | heading rows: take all levels; fill merged cells only in their own direction |
| Rows glued wrongly (continuation join; 'Case 1' rows taken as headings) | 32 | #2, #3 | treat label-first rows as data; join only the first non-data line, never several rows |
| Scanned pages with an embedded text layer: grid misread | 11 | #3, #5 | flag as low quality (or VLM for structure in v1.1) |
| Chapter running header not removed | 10 | all | repeat-within-chapter rule |
| OCR noise (letters, superscripts, line order) | 4 | #2, #4, #5 | accept (numbers survived) |
| Checker limitation: blank forms with no data rows | 3 | #4, #5 | let the checker place a table by its heading page |
| Header stripper removed a real line | 1 | #5 | don't strip lines that are not on most pages' edges |

Most of the loss is in tables. Plain text, Act and Rules pages score ~99% apart from the chapter header. The self-check flagged none of the worst table failures (98, 170, 72, 26, 179), so these would reach the index silently today.

## Vision-model grids on runs #1-#5 (2026-10-29)

Same pages and the same snapping to PDF words (`archive/experiments/vlm_tables.py`); only the grid's source
changes. Paddle = PaddleOCR-VL 1.6 run locally (MLX, M5 Mac). Tested and dropped; full results,
setup and conversion rules in `archive/notes/paddle_results.md` (its code was removed).

| Run | PyMuPDF | Gemini 3.5 Flash Lite | PaddleOCR-VL 1.6 |
|---|---|---|---|
| #1 2029 | 92.5% | 97.3% | 91.2% (156/171) |
| #2 2030 | 88.1% | 98.7% | 89.3% (201/225) |
| #3 2031 | 65.7% | 94.0% | 93.4% (199/213) |
| #4 2032 | 96.9% | 93.4% | 82.9% (131/158) |
| #5 2033 | 90.2% | 86.1% | 78.2% (111/142) |
| **pooled** | **85.6%** | **94.4%** | **87.8% (798/909)** |
| time per page | ~0.1 s | 4.4 s, 8 at a time | 6.8 s, one at a time |
| cost, 125 pages | 0 | $0.15 | 0 |

Why Paddle lost points. Most of the loss is in our conversion and snapping code, not in the
model's reading; no number was misread.
- **Table box swallowed the page** (24/24 p.2 0/12, Corrigendum 76 1/17, 106 p.7): page text
  missing. A table's box is the outline of the words its cells took, so one cell snapped far away
  stretches the box over the page, and every word inside it leaves the page text. Gemini is exposed
  to the same bug. Fix: a box from the model's own bbox, or drop outlier cells.
- **LaTeX in cells** (`$ 1^{{st}} $` for "1st", 72 p.3; 179): the cell doesn't snap, so dates are
  lost. Fix: strip `$`, `^{}` and braces before snapping.
- **Heading rows guessed wrong**: Paddle doesn't mark headings. 26 p.10: a third heading level
  without spanning cells became data rows. 199, 181, 31: Q&A tables' headings shifted one column.
- **98 p.2 table 2**: the model returned plain text instead of a table (dropped).
- **94 p.3, 36 p.7**: table not matched (continuation/heading rules).

### Gemini after the box fix (2026-10-29)

Fix in `archive/experiments/vlm_tables.py`. On a blank form, the table's area is now found from its
headings. Headings are never looked for on the whole page. A table's box stays within 2 lines of
its PyMuPDF area. The Gemini answers came from the cache, so the model was not asked again.

| Run | Before | After |
|---|---|---|
| #1 2029 | 97.3% | 98.4% (183/186) |
| #2 2030 | 98.7% | 98.7% (222/225) |
| #3 2031 | 94.0% | 94.0% (204/217) |
| #4 2032 | 93.4% | 98.3% (178/181) |
| #5 2033 | 86.1% | 88.7% (134/151) |
| **pooled** | **94.4%** | **95.9% (921/960)** |

Numbers: 100% in every set. No set went down.

What is left:
- Rules running header (`text_not`): 2 checks in every set, 10 in all.
- 2031 cells (10): 98 p.2 table 1 lost row (III), which the lite model dropped.
- 2033 (17): the ISP scan page's text layer, 106's split-letter headings, and OCR line order.

### The ingestion pipeline: PyMuPDF + gate → Gemini (2026-10-29)

`src/taxowl/ingestion/pipeline.py`, output in `data/ingested/`. Gemini reads only the pages the
gate sends, plus the pages their tables run onto. PyMuPDF reads the rest.

| Run | PyMuPDF only | Gemini on every page of table files | Pipeline (gate) |
|---|---|---|---|
| #1 2029 | 92.5% | 98.4% | 98.9% (184/186) |
| #2 2030 | 88.1% | 98.7% | 98.7% (222/225) |
| #3 2031 | 65.7% | 94.0% | 99.1% (215/217) |
| #4 2032 | 96.9% | 98.3% | 98.3% (178/181) |
| #5 2033 | 90.2% | 88.7% | 89.4% (135/151) |
| **pooled** | **85.6%** | **95.9%** | **97.3% (934/960)** |

Numbers: 100% in every set.
- **Why the pipeline beats Gemini-everywhere:** simple tables stay with PyMuPDF, which reads them
  exactly.
- **Why 2031 rose:** partly because the model was asked again. The cache is now keyed by file
  hash, and this time the lite model kept 98 p.2's row (III).
- **Same exposure:** that lucky retry is one more reason to confirm on a fresh set.

Left (26 checks):
- Rules chapter running header: 10.
- 2033 (16): the ISP scan's text layer, 106's split-letter headings, OCR line order, and the
  Corrigendum.
- 2029, 2030, 2032: one text check each.
