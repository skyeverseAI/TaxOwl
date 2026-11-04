# Extraction: how we got here

The extractor's job: **PDF in → clean text + tables out** (one `ExtractedDoc` per file). Splitting into sections or paragraphs, chunking and search come later and aren't covered here.

Each step below says **what we did, why, and what came out.** The steps are in the order we did them. The last section is what's left, and why.

Detailed records: `plans/plan_ingestion.md` (sections A–C3), `eval_results/heldout_runs.md`, `archive/notes/paddle_results.md`.

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
13. Wire OCR into pipeline →  scans 94.3% in the real pipeline; OcrMac removed
14. Upload guard          →  re-read scanner layers on uploads only (corpus layers are good)
15. Snap fixes            →  ")" and word order; held-out 97.8% / 97.9%
16. Batch the OCR         →  3.0 → 1.75 s/page, same results
17. Pin versions          →  exact versions + `uv sync --frozen`
18. Final scores          →  extractor done
19. Join spread lines     →  justified words back on one line; scores unchanged (found by the splitter)
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

- **What:** `scripts/02_check_scans.py` counted the letters in each page's text layer.
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

- **What:** `src/taxowl/ingestion/extract.py` and `tables.py`, scored by `eval_results/check_ingestion.py` against a **gold set**. The gold set has 11 cases, 13 pages and 230 checks, written from page images and verified by the user.
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

- **What:** a cheap **gate** (`gate.py`) looks for signs of a complex table: merged cells, nesting, colour, white boxes, scans, broken grids. Only flagged pages go to Gemini; PyMuPDF reads the rest. All of this is wired into `src/taxowl/ingestion/pipeline.py`.
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

- **What:** `archive/experiments/docling_trial.py`. It throws away the hidden layer, re-reads every page with OCR (Docling + OcrMac, the setup LERAGS used), and lets Docling build the tables.
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

## 13. Wire Docling + RapidOCR into the pipeline (2026-11-02)

- **What:** the reader moved from the trial script into `src/taxowl/ingestion/ocr.py`, and the old OcrMac code was deleted. A file with a row in the manifest counts as a **foundation file**. The first time a foundation file is read, its OCR result (text and tables) is saved to `docs/ocr/<file>.json`, keyed by the PDF's sha256, so it's never read again. Uploads are never saved. `ingestion/ocr_scans.py` was no longer needed and was removed.
- **Why:** the decision only existed in a test script. The pipeline was still calling OcrMac.
- **Result:**
  - **Corpus scans: 94.3%**, exactly the trial's score with the same failures, now running in the project's own Python 3.14 env.
  - Held-out scores held.
  - The pipeline was scored on **gold** for the first time: **94.1%**. 11 of the 15 misses are Gemini tables on typed pages (254, 182, 133), which this change never touched. The old 256/256 was the PyMuPDF-only extractor, whose rules were built while looking at those exact pages. The other 4 misses are Docling dropping the subject line and three paragraph starts on 229, page 1.

## 14. Upload guard (2026-11-02)

- **What:** two jobs.
  1. **Clean rejections.** A PDF with no pages gets a clear error. Uploads also get one if they're over 500 MB or over 1,000 pages. (The first limit was 100 MB, and it blocked a real 200-page petition of 164 MB. High-resolution scans take about 0.8 MB a page.) The "not a PDF" and "password" checks were already there.
  2. **A new page type, `hidden`:** a picture covers more than 80% of the page **and** more than half the text is drawn invisible. That's a scanner's own OCR hidden behind the picture, so the page is read fresh, like a scan.
- **Why:** the hidden layer was the cause of the petition losses (step 10).
- **Checked before building:** all 20 petition pages that carry text show both signs at 100%. Across the 314 corpus files, **no** typed page has a full-page picture, so the rule can't misfire on a typed page.
- **A surprise:** 25 of our own files (84 pages) carry the same kind of layer. Re-reading them **lost 21 held-out checks.** CBIC's scanner layer was good. Docling moved letterheads to the end of the page (and the checker reads in order), garbled one subject line, and lost one table's headings.
- **Decision:** the `hidden` rule runs on **uploads only.** Our files keep their measured-good layer; uploads always get fresh OCR, because we can't know how good their scanner was. After this change, every held-out score was back where it had been.

## 15. Snap fixes (2026-11-02)

- **What:** two bugs in the code that fills Gemini's grid with the PDF's own words (`vlm.py`).
  1. **")" lost at the end of a heading.** `Recoveries made till date (Rs.)` came out as `…(Rs.`, because the code took `(Rs.` from the column before. **Fix:** a word is used once per heading, and a word that spells only the start of the model's word is a **dead end** unless the PDF's next word continues it (`Sup` + `plier` still joins).
  2. **Words in the wrong order.** `Statement 3 under…` came out as `3 under … Statement`, because "Statement" was taken from the `Statement 3A` line below. **Fix:** of two complete matches, the one whose words follow each other in the PDF wins.
- **Why:** these are wrong-text errors in table headings and cells, which are exactly what search and citations depend on.
- **Result:** gold went from 94.1% to **94.5%**; held-out 2029–33 from 97.6% to **97.8%**; 2034–36 from 97.1% to **97.9%**. No set went down.
- **What went wrong first:** the first fix for bug 1 ("choose words near this heading's other words") fixed one page and broke a narrow blank form (106/2019, 4 checks lost). Only the full test caught it. The dead-end rule replaced it.

## 16. Batch the OCR (2026-11-02)

- **What:** consecutive scan pages go to Docling together, up to 50 at a time, in one call. Before, every page was its own call, and each call re-opened the whole PDF.
- **Why:** a 453-page petition was opening the full PDF 453 times. Users won't wait 45 minutes for an upload.
- **A bug the test caught:** when Docling reads pages together, it joins a paragraph that runs over a page break into one piece, and that piece was tagged with only the first page. A sentence and the number "10,41,411" moved from page 22 to page 21. **Fix:** Docling records which part of the paragraph sits on each page (a character span), so the paragraph is split back by those spans.
- **Result:** **3.0 → 1.75 seconds per page**, with identical output (7 corpus pages matched page-by-page reading exactly, and petition C matched the trial exactly, 102/123).
- **For background uploads:** `ingest(progress=...)` now reports pages done, total pages and seconds so far. The future app will use it to show "200 of 453 pages read" while the user waits. The app itself is a deployment task.

## 17. Pin versions (2026-11-02)

- **What:** exact versions (`==`) in `pyproject.toml` for docling, docling-core, docling-ibm-models, rapidocr, onnxruntime and pymupdf. The README now says to install with `uv sync --frozen`.
- **Why:** in step 12, the same OCR scored 84% or 74% depending only on the versions of `docling-core` and `docling-ibm-models`. `uv.lock` already pinned everything; the `==` rules stop an accidental upgrade, and `--frozen` makes a server install exactly what we measured.

## 18. Final scores (2026-11-02)

| Set | Score |
|---|---|
| Gold (pipeline) | 94.5% |
| Held-out 2029–33, pooled | 97.8% |
| Held-out 2034–36 (fresh), pooled | 97.9% |
| Corpus scans | 94.3% |
| Private petitions (uploads, 854 pages) | **82.6%** (was 73.1% before the guard; the Docling + RapidOCR trial gave the same 82.6%) |
| Numbers, held-out | 100% |

## 19. Join spread lines (2026-11-03, found while building the splitter)

- **What:** in a justified line with wide gaps, PyMuPDF gave every word its own line. The Act's heading `1[158A. Consent based sharing of information furnished by taxable person.—` came out as ten one-word lines. The user spotted it by comparing the splitter's output with the PDF.
- **How common:** 240 places in 84 corpus files (four or more one-word lines in a row).
- **Fix (`extract.join_spread_lines`):** join a piece onto the line before it when they're in the same block, at the same height, the piece is to the right, and the gap is at most 3x the text height. Runs of one-word lines: 728 → 209 (7,719 pieces joined in 290 files). It also puts paragraph numbers back with their text (`3.` + `Accordingly, it is…`), which the circular splitter needs.
- **What went wrong first:** without the gap limit, the Rules running header (`278` at one end of the page, `GST & Indirect Taxes Committee` at the other, 16x apart) became one line that differs on every page, so `strip_headers` stopped removing it. Held-out fell 5 + 3 checks. The full test caught it; the gap limit (justified text is about 1x) fixed it.
- **Result:** gold 94.5%, held-out 2029–33 939/960 (97.8%), 2034–36 650/664 (97.9%), all exactly as before. The checks compare words, not line breaks, so the gain shows up in the splitter, not here.
- **Lesson:** fix at the root, then re-run every test. A downstream step (the splitter) is a good test of the step before it.

---

## The extractor today

```
                PDF
                 │
     upload? ──► GUARD: reject unreadable / too big
                 │
     per page:
        │ typed                        │ scan, or (uploads) hidden scanner layer
        ▼                              ▼
   PyMuPDF text + tables         Docling + RapidOCR, 50 pages per call
        │                          text + tables
   gate → Gemini grid,             foundation files: saved to docs/ocr/
   words snapped from the PDF
        └──────────────┬───────────────┘
                       ▼
                 ExtractedDoc + self-check
```

Foundation files (Act, Rules, circulars) and user uploads go through the **same pipeline**. A file is a foundation file if it has a row in `docs/manifest.jsonl`. To add a new notification: download it with `scripts/01_download.py`, which adds its manifest row, run the pipeline, and commit `docs/ocr/` if it had scan pages.

**Known gaps we're deferring:**
- an image inside a typed page is ignored (rare);
- the Rules' chapter running header isn't removed (10 checks across the held-out runs);
- Gemini tables with two-row headings or a table continued from the page before (182, 251) still lose a few cells;
- Docling drops the subject line on one scanned page (229, page 1);
- uploads take about 1.75 s per scanned page on a laptop CPU, so a 1,000-page upload is about 30 minutes. A GPU, or sending scan pages to Gemini, is a deployment decision;
- the web server in front of the app (for example Nginx, 1 MB by default) needs its own upload limit raised to 500 MB at deployment.

None of these blocks calling the extractor done.

---

## Lessons (for interviews)

1. **Measure before choosing.** Every tool choice here (PyMuPDF, Gemini, the gate, RapidOCR) came from a score on hand-checked pages, not from a guess.
2. **Hold out pages you never tuned on.** Gold said 100%; held-out said 85.6%. The honest number is the one that matters.
3. **Words come from the PDF.** Models decide the layout, never the text, so a model can't change "18%" into "28%".
4. **Cheap first, heavy only where needed.** The gate sends only complex pages to Gemini, and only scan pages go to Docling.
5. **Change one thing at a time.** The OCR shoot-out kept Docling fixed and swapped only the engine. That's how we caught both the paragraph-number bug and the library-version problem.
6. **Check your own measuring tools.** One "Docling is bad" result turned out to be a bug in our own trial script.
7. **Pin versions.** The same code and model scored 10 points apart in two environments.
8. **A rule that's right for one source can be wrong for another.** Re-reading hidden scanner layers fixed the petitions but hurt CBIC's files. So the rule depends on where the file came from.
9. **Run the full test after every fix.** The first ")" fix fixed one page and broke another. Only the full held-out run showed it.
10. **Speed fixes need correctness checks too.** Batching OCR silently moved a paragraph to the wrong page. Comparing against the page-by-page output caught it.
