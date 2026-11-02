# Extraction: how we got here

The extractor's job: **PDF in → clean text + tables out** (one `ExtractedDoc` per file). Splitting into sections or paragraphs, chunking and search come later and aren't covered here.

Each step below says **what we did, why, and what came out.** The steps are in the order we did them. The last section is what's left, and why.

Detailed records: `plans/plan_ingestion.md` (sections A–C3), `evals/heldout_runs.md`, `evals/paddle_results.md`.

---

## The flow at a glance

```
1. Get the documents      →  314 files, one manifest
2. Find the scans         →  8 scanned files (~37 pages)
3. OCR the scans          →  OcrMac, text saved in docs/ocr/
4. Find the tables        →  ~110 of 304 files have tables
5. Compare table tools    →  no single winner → our own strategy
6. Build the extractor    →  gold 256/256 (100%)
7. Test on unseen pages   →  held-out 85.6% → tables are the weak spot
8. Try vision models      →  Gemini 95.9% ✅   PaddleOCR-VL 87.8% ❌
9. Gate + pipeline        →  97.3%, then 97.7% on a fresh set
10. Stress test: uploads  →  private petitions 62.6% → hidden scanner layer is the problem
11. Docling + OCR trial   →  petitions 82.3% (re-reading the page fixes it)
12. OCR engine shoot-out  →  Docling + RapidOCR chosen (scans 94.3%, runs on Linux)
13. What's left           →  wire it in, upload guard, small bugs, pin versions, final check
```

---

## 1. Get the documents (2026-10-24)

- **What:** we chose the sources and downloaded everything.
  - The Act from India Code (as of 11-06-2026).
  - The Rules from the ICAI Bare Law, 12th edition (as of 31-03-2026).
  - All CBIC CGST circulars, GST instructions and 2 later notifications, from the CBIC portal's JSON API (`scripts/01_download.py`).
- **Why:** we need the law as it reads today. Every file gets a record of where it came from (link, date, sha256), so answers can cite it.
- **Result:** `docs/manifest.jsonl` has **314 rows**: 267 circulars, 43 instructions, 2 notifications, the Act and the Rules. All of them are valid PDFs.

## 2. Find the scans (2026-10-24)

- **What:** `ingestion/check_scans.py` counted the letters in each page's text layer.
- **Why:** a scanned page is only a picture. It has no words inside it, so it needs OCR (a program that reads the picture).
- **Result:** **8 files are real scans** (about 37 pages). We checked all 8 by eye. Some files only *look* scanned but have a hidden text layer behind the picture (for example 56/2018). We noted those for later.

## 3. OCR the scans (2026-10-25)

- **What:** `ingestion/ocr_scans.py` read the 8 scans with **OcrMac** (Apple's built-in OCR) and saved the text in `docs/ocr/`.
- **Why:** it's free and accurate, and our Macs have it.
- **Problems we fixed along the way:**
  - paragraph numbers were skipped, so we re-read the left margin;
  - lines got merged on tilted pages;
  - a number sometimes sat alone on its own line;
  - date ordinals ("15th") came out garbled;
  - "SI. No." was read in place of "Sl. No.".
- **Result:** every paragraph sequence is complete, and rates and notification numbers are correct. The saved text means the server never needs to OCR these files again.

## 4. Find the tables (2026-10-24)

- **What:** two separate methods ran on every page: PyMuPDF's table finder, and a count of drawn lines. Where they disagreed, we checked by eye.
- **Why:** a table only makes sense with its headings. "Delhi | 70% | 10,00,000" means nothing unless you know the columns. LERAGS lost the headings on 55.6% of rows by flattening tables into plain text.
- **Result:** **about 110 of 304 files have tables.** Of 28 "no table" files checked by eye, none had a table we'd missed. We also found the hard kinds: tables split across pages, tables inside tables, blank forms, and two-row headings.

## 5. Compare table tools (2026-10-25)

- **What:** PyMuPDF plus our own rules, against Docling, on the 9 hardest table files.
- **Why:** we wanted to choose a tool from evidence, not from a guess.
- **Result:** **no single winner.**
  - PyMuPDF joined a 7-page table correctly, but made junk rows on tables with no drawn lines.
  - Docling read those tables cleanly, but **silently dropped a whole table** in 123/2019.
- **What we learned** (written up in `plan_ingestion.md` C2):
  1. **Words come from the PDF, never from a tool's guess.** A tool may decide where the rows and columns are, but the cell text is copied from the PDF.
  2. **Use the cheap tool first, and the heavy one only where the cheap one fails.**
  3. **Every result checks itself, and silent loss is the worst failure.**

## 6. Build the extractor (2026-10-27)

- **What:** `src/taxowl/extract.py` and `tables.py`, scored by `evals/check_ingestion.py` against a **gold set**. The gold set has 11 cases, 13 pages and 230 checks, written from page images and verified by the user.
- **Why:** we need a score to know whether a change helps or hurts.
- **Result:** **gold 256/256 (100%).** All 314 files ran in about 2 minutes, and no file lost words. But the rules were built while looking at the gold pages, so 100% could be overfitting: the rules might only fit those pages.

## 7. Test on unseen pages (2026-10-28)

- **What:** held-out sets. Each one is 10 pages drawn at random (5 table, 1 scan, 2 plain, 1 Act, 1 Rules), with the gold written fresh and no fixes made between runs.
- **Why:** this is the honest score: how the extractor does on pages it has never seen.
- **Result:** the 5 runs pooled gave **85.6%**, with a range of 65.7–96.9%.
  - Plain text, the Act and the Rules score about 99%.
  - **Almost all the loss is in tables:** coloured backgrounds read as grid lines, multi-level headings, rows glued wrongly.
  - Worse, the self-check flagged **none** of the worst table failures. They would have gone into the index silently.

## 8. Try vision models for table grids (2026-10-29)

- **What:** a vision model looks at the page image and returns only the grid (rows and columns). The cells are then filled with the PDF's own words ("snapping"). We tried Gemini 3.5 Flash Lite (cloud) and PaddleOCR-VL 1.6 (local).
- **Why:** PyMuPDF's grid was the weak spot. A model that *sees* the page can tell a coloured box from a real line.
- **Result:**

  | | Pooled score | Time per page | Cost (125 pages) |
  |---|---|---|---|
  | PyMuPDF only | 85.6% | 0.1 s | 0 |
  | Gemini | **95.9%** (after a box fix) | 4.4 s | $0.15 |
  | PaddleOCR-VL | 87.8% | 6.8 s | 0 |

  Gemini won. Numbers were 100% correct in every set. **PaddleOCR-VL was dropped.**

## 9. Gate + pipeline (2026-10-29 / 30)

- **What:** a cheap **gate** (`gate.py`) looks for signs of a complex table: merged cells, nesting, colour, white boxes, scans, broken grids. Only flagged pages go to Gemini; PyMuPDF reads the rest. All of this is wired into `src/taxowl/ingestion_pipeline.py`.
- **Why:** to save money and time, and because simple tables are read *more* exactly by PyMuPDF than by any model.
- **Result:**
  - The gate caught every real bad table and sends 56% of table pages to Gemini.
  - Held-out pooled score: **97.3%** with the gate, against 95.9% for Gemini on every page.
  - A **fresh** held-out set (seeds 2034–36) scored **97.7%**. The scores held up on new pages.

## 10. Stress test: what a user might upload (2026-10-30)

- **What:** 25 pages from 4 private writ petitions (sets A–D), with gold in `data/private/`, which is never committed. They include tables, stamps, signatures, Kannada and Hindi letterheads, and scanned pages.
- **Why:** user uploads will be messier than CBIC's clean PDFs. We wanted to know where the pipeline breaks before users find out.
- **Result:**

  | | Score |
  |---|---|
  | PyMuPDF only | 62.6% |
  | PyMuPDF + Gemini | 73.1% |

  **The cause:** petitions A–C carry a **hidden text layer added by the scanner**, and our pipeline trusts it. That layer is often wrong ("Section SO" for 50). Gemini only fixes the grid, never the words, so it can't help.

## 11. Docling + OCR trial (2026-10-30)

- **What:** `evals/docling_trial.py`. It throws away the hidden layer, re-reads every page with OCR (Docling + OcrMac, the setup LERAGS used), and lets Docling build the tables.
- **Why:** if the hidden layer is the problem, reading the page fresh should fix it.
- **Result:**
  - **Petitions: 82.3%**, up from 73.1%. Reading the page again works.
  - **Corpus scans: 79.6%**, against 93.4% for OcrMac on its own. Docling looked worse on scans.

## 12. OCR engine shoot-out: OcrMac vs RapidOCR (2026-10-30 / 11-02)

- **What:** we added `--ocr rapid` to the trial script. Docling stays exactly the same and only the OCR engine changes, so any difference in the score comes from the engine.
- **Why:** OcrMac runs **only on a Mac**, and the server will be Linux, so uploads need an engine that runs on Linux. RapidOCR does.
- **Two surprises along the way:**
  1. **A bug in our own trial script.** Docling stores a paragraph number ("2.1", "15.") separately from the paragraph's text, and the script was only taking the text. So the earlier note that "Docling drops para numbers" was wrong. After the fix, both engines scored higher.
  2. **Library versions matter.** OcrMac scored 83.8% in the LERAGS venv but **73.6%** in a fresh env with newer Docling libraries (docling-core 2.105 against 2.78). RapidOCR scored the same in both.
- **Result** (after the fix, same env):

  | | Petitions (25 pages) | Corpus scans (13 cases) | Speed |
  |---|---|---|---|
  | OcrMac alone (old pipeline) | n/a | 93.4% | fast |
  | Docling + OcrMac | **83.8%** | 86.3% | 1.5 s/page |
  | Docling + RapidOCR | 82.6% | **94.3%** | 3.0 s/page |

- **Decision (2026-11-02): Docling + RapidOCR, for scan pages only.** OcrMac is dropped completely. The reasons:
  - It's the best on scans, and tied with OcrMac on petitions (a 1-point gap is about 7 checks out of 599).
  - It runs on Linux, so there's no Mac dependency. New foundation files can be added from any machine, or by GitHub Actions later.
  - It gives **tables on scan pages**, which our old OCR code couldn't do. Petitions often have tables on scanned pages.
  - It's stable across library versions.
  - The cost: it's heavy (torch, about 1–2 GB) and 2× slower than OcrMac. The server size gets decided at deployment. Typed pages never touch Docling, so the extra load only falls on scan pages.
  - We also checked that Docling installs on the project's Python 3.14.

---

## The extractor today

```
                PDF
                 │
     upload? ──► GUARD (todo)
                 │
     per page: real text?
        │ yes                          │ no (scan)
        ▼                              ▼
   PyMuPDF text + tables         Docling + RapidOCR (todo: wire in)
        │                          text + tables
   gate → Gemini grid (done)
        └──────────────┬───────────────┘
                       ▼
                 ExtractedDoc
```

Foundation files (Act, Rules, circulars) and user uploads go through the **same pipeline**. Uploads also pass through the guard first, because we don't control what users send.

---

## What's left, and why

| # | Step | Why |
|---|---|---|
| 1 | **First git commit** | There's no commit yet. We need a safety net before a big change, so we can go back if something breaks. Private data (`data/private/`, `sep_docs/`) must never enter this public repo. |
| 2 | **Wire Docling + RapidOCR into the pipeline.** Move `read_page` and `to_table` from the trial script into `src/taxowl/ocr.py`, re-read the corpus scans into `docs/ocr/`, and remove ocrmac from `pyproject.toml`. | The decision only exists in a test script today. The pipeline still calls OcrMac. |
| 3 | **Upload guard.** Spot a bad hidden scanner layer and send that page to OCR. Reject broken, encrypted or empty files with a clear message. | This was the cause of the petition losses (step 10). A crash on a bad file is worse than a clear "can't read this". |
| 4 | **Snap bugs:** ")" gets dropped, and words inside a table cell come out in the wrong order. | Small, known losses. Cheap to fix. |
| 5 | **Pin library versions.** | Step 12 showed that the same tool can score 84% or 74% depending only on library versions. The server must run exactly what we measured. |
| 6 | **Final check:** re-run the gold set, the held-out sets, the corpus scans and the petitions. | The extractor counts as **done** only if no score drops. |

**Known gaps we're deferring:**
- an image inside a typed page is ignored (rare);
- the Rules' chapter running header isn't removed (10 checks across the held-out runs).

Neither one blocks calling the extractor done.

---

## Lessons (for interviews)

1. **Measure before choosing.** Every tool choice here (PyMuPDF, Gemini, the gate, RapidOCR) came from a score on hand-checked pages, not from a guess.
2. **Hold out pages you never tuned on.** Gold said 100%; held-out said 85.6%. The honest number is the one that matters.
3. **Words come from the PDF.** Models decide the layout, never the text, so a model can't change "18%" into "28%".
4. **Cheap first, heavy only where needed.** The gate sends only complex pages to Gemini, and only scan pages go to Docling.
5. **Change one thing at a time.** The OCR shoot-out kept Docling fixed and swapped only the engine. That's how we caught both the paragraph-number bug and the library-version problem.
6. **Check your own measuring tools.** One "Docling is bad" result turned out to be a bug in our own trial script.
7. **Pin versions.** The same code and model scored 10 points apart in two environments.
