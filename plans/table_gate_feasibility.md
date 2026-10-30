# Feasibility: PyMuPDF first, a vision model only where a table looks wrong

Idea (2026-10-29): PyMuPDF reads every page and its tables. A confidence check scores each table.
Only low-confidence tables go to a vision model (Gemini or PaddleOCR-VL), whose grid is snapped to
the PDF's own words as in `ingestion/vlm_tables.py`. The same path must work for a PDF a user
uploads later, not only for our corpus.

Update, same day: PaddleOCR-VL was tested and dropped. It scored 87.8% against Gemini's 94.4%
(`evals/paddle_results.md`), so Gemini is the model here. Paddle's numbers below are kept for the
privacy and speed trade-off.

Verdict: **feasible, with one condition.** The check must catch nearly every bad table, and today's
self-check doesn't. It needs new signals and a measurement on the gold sets before we trust it.

## The numbers that decide it

From the PyMuPDF run over the whole corpus (`data/extracted`):

| | |
|---|---|
| PDFs / pages | 314 / 1,829 |
| Pages with a table | 278 (15%) |
| Tables | 259 |
| Documents the self-check flagged | 20 (sparse tables, missing headings, repeated cells) |

Speed per page, measured on the held-out runs:

| Reader | Per page | All 278 table pages | All 1,829 pages |
|---|---|---|---|
| PyMuPDF | ~0.1 s | seconds | ~3 min |
| Gemini 3.5 Flash Lite, 8 at a time | 4.4 s | ~2.5 min, ~$0.35 | ~17 min, ~$2 |
| PaddleOCR-VL on this Mac, one at a time | ~6 s | ~28 min, $0 | ~3 h |

Only 15% of pages hold a table. So "send every table page to the model" is already cheap with
Gemini: a typical 4-page circular with one table page takes ~0.1 s plus ~5 s. A gate saves time
mainly for a slow model (Paddle on a Mac) or a large upload.

## The risk: a gate that says "fine" when it isn't

On the held-out runs the self-check flagged **none** of the worst tables: 179, 98, 170, 72 and 26
(`evals/heldout_runs.md`). Those would have passed the gate and reached the index wrong, silently.
A gate is only as good as its misses, so the measure that matters is **recall**: of the tables that
are actually wrong, how many does it send to the model? Aim for ~100%. **Precision** (how many of
the sent tables were really wrong) only costs time.

## New signals, one for each known cause

Each is cheap: it uses only what PyMuPDF already has (drawings, words, the grid).

| Cause (failed checks in runs #1-#5) | Signal | Would it have caught |
|---|---|---|
| Filled or coloured boxes read as grid lines (44) | Filled rectangles inside the table area; or `lines` and `lines_strict` give different column counts | 179, 98, Corrigendum, 26 |
| Rows glued at a page break (part of 32) | The table touches the top of the page and was joined to the previous page; or a cell holds several separate numbers ("125,500 10,000 2,64,500") | 170 |
| Data rows read as headings (part of 32) | A table with 0 data rows, or headings that contain numbers or dates | 72 |
| Multi-level headings (28) | More than one heading row, or empty heading cells next to filled ones | 36, 26 |
| Scan with a text layer (11) | A page-size image under the text | 51, ISP 02/2021-22 |
| PyMuPDF finds no table at all (251/08/2025) | Gap: needs a table *detector*, see below | not caught |

Caution: the right-hand column is hindsight. The signals were picked after seeing those failures, so
they must be scored on sets they weren't built from (seed 2034 onwards).

The last row is the hard one. A gate can only judge tables that PyMuPDF found. A table without
lines that PyMuPDF misses never reaches the gate. Two fixes:
(a) send every page that has column-like text (word positions that line up) to the model; or
(b) run Paddle's small layout model (PP-DocLayoutV3, 123 MB) on every page only to ask "is there a
table here?". Its speed alone is not measured yet.

## What changes for a user's upload

- **Scanned PDF, no text layer**: there are no PDF words to snap to. The model's text would be the
  only source, so numbers could change. Mark it as OCR (`ocr=True`, lower trust), as the 8 scans
  in the corpus already are. Never present it as exact.
- **Privacy**: Gemini means the user's PDF goes to Google, through OpenRouter. Paddle runs on our own
  machine. For uploads this may decide the model, more than accuracy does
  (`lerags-lessons`: private-data boundary).
- **Waiting**: process uploads in the background and show a status ("reading tables..."). A
  20-page PDF with 3 table pages takes ~5 s with Gemini, ~20 s with Paddle on a Mac. On a GPU
  server Paddle would be faster, but that server costs money to run.
- **Unknown layouts**: user PDFs won't look like CBIC circulars. Generic signals (filled boxes,
  0 data rows, glued numbers) carry over; tuned thresholds may not.

## How to check it before building it (no model calls, ~1-2 h)

1. Compute the signals on the PyMuPDF output of the 8 held-out sets (2026-2033).
2. For each gold table, record: flagged or not, and right or wrong according to the checker.
3. Report recall, precision, and the share of table pages the gate would send.
4. Decide:
   - recall ~100% and few pages sent: build the gate;
   - recall ~100% but most table pages sent anyway: skip the gate and send every table page;
   - recall clearly below 100%: the gate isn't safe; send every table page.

## Recommendation

Shape: PyMuPDF on everything, then (gate or not) a model on table pages, with the PDF's words always
kept. Then a rule per table: keep the model's grid if it passes the word checks, keep PyMuPDF's if
the model fails, and flag the table if both fail.

Run the check above first. If it doesn't clearly win, the simplest safe option is to send every
table page to the model. That's 15% of pages, about 2.5 min for the whole corpus with Gemini. A gate
mostly earns its keep with a slow local model or a very large upload.

## Result of the gate test (2026-10-29, `evals/gate_test.py --corpus`)

Signals: merged, nested, colour, white_boxes, scan, broken, self_check. `multi_page` was dropped
after the first run: it fired on 17 of 25 good cases, and its two bad catches were caught by other
signals too. Cases: 8 held-out sets plus the dev set (`ingestion_gold.json`, which has the nested
133 p.5).

| | Result |
|---|---|
| Bad tables (PyMuPDF failed a table check) caught | 13 of 14. The miss, 16/16/2017, is a checker bug (a comma before "S.No. 24"), not a table error. So every real table error was caught. |
| Good tables sent anyway | 9 of 31 (only costs time) |
| Known nested pages (136, 133, 123, 75 p.10 and 13) | all flagged `nested` and sent |
| Corpus table pages sent | 189 of 336 (56%): ~1.7 min and ~$0.23 with Gemini, vs ~3.1 min and ~$0.40 for every table page |

Most useful signals: `broken` (11 of 14 bad) and `merged` (9 of 14). `self_check` added no catch of
its own, so it can be left out of the gate.

Verdict: the gate is safe on these sets and halves the pages sent. With Gemini it saves little
(about 1.4 min and $0.17 for the whole corpus). It matters more for uploads and for a slower or
local model.

Caveat: the signals were chosen after seeing these failures. Confirm on a fresh set (seed 2034)
before trusting it.
