"""Read one scanned page with Docling + RapidOCR: its text in reading order, and its tables.

Used by the ingestion pipeline for pages without a text layer (fewer than 100 letters), for
corpus files and uploads alike. Chosen 2026-11-02 over Apple's OcrMac (plans/extraction_journey.md,
step 12): on the corpus scans 94.3% against 86.3%, it runs on Linux, and it gives tables on scan
pages. Measured with archive/experiments/docling_trial.py; this is the same reading, moved here.

Per page:
  1. Docling turns the page into an image, RapidOCR reads every word on it (full-page OCR: any
     text layer the scanner left behind is ignored), and Docling's layout model groups the words
     into paragraphs, headings, lists and tables.
  2. Page text: Docling's body text outside tables. Page headers and footers are left out,
     because Docling puts them in a separate layer.
  3. Tables: headings = the top rows Docling marks as column headers, joined per column
     ("Amount CGST"); if it marks none, headings are "" and every row is a row. A merged cell's
     text is repeated in each row it covers, as in our other tables.

Docling is heavy (torch, layout models), so it's imported on first use and the converter is
built once and reused for every page. Pages go to it in runs of up to CHUNK_PAGES consecutive
pages, one call per run: one call per page re-opened the whole PDF every time, so a 453-page
petition did that 453 times.
"""

import io
import time

CHUNK_PAGES = 50  # pages per Docling call: fewer calls, but memory stays bounded and progress shows

_converter = None


def converter():
    """Full-page RapidOCR, table structure on, CPU. The settings measured in docling_trial.py."""
    global _converter
    if _converter is None:
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.do_table_structure = True
        opts.ocr_options = RapidOcrOptions(force_full_page_ocr=True)
        opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=8)
        _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return _converter


def read_pages(data, pages, name="document.pdf", progress=None):
    """OCR `pages` (1-based page numbers) of the PDF bytes `data`. Returns {page: (text, tables)},
    where each table is {"headings": [...], "rows": [[...], ...]}. `progress`, if given, is called
    after each run with (pages done, pages in all, seconds so far): the hook a server uses to
    show "200 of 453 pages read" while an upload is processed in the background."""
    from docling.datamodel.base_models import DocumentStream
    from docling_core.types.doc import ListItem, TableItem

    out = {p: ([], []) for p in pages}
    started, done = time.time(), 0
    for first, last in runs(sorted(out)):
        stream = DocumentStream(name=name, stream=io.BytesIO(data))
        doc = converter().convert(stream, page_range=(first, last)).document
        for item, _ in doc.iterate_items():
            if not item.prov or item.prov[0].page_no not in out:
                continue
            if isinstance(item, TableItem):
                t = to_table(item)
                if t:
                    out[item.prov[0].page_no][1].append(t)
            elif getattr(item, "text", ""):
                # Docling keeps a numbered para's number ("2.1", "15.", "(a)") in .marker, not .text; put
                # it back. Bullets ("-", "•") have no letter or digit and are skipped.
                marker = item.marker if isinstance(item, ListItem) else ""
                marker = f"{marker} " if any(c.isalnum() for c in marker or "") else ""
                for page, part in split_by_page(item):
                    if page in out and part.strip():
                        out[page][0].append(marker + part.strip())
                    marker = ""  # only the part that starts the para gets its number
        done += last - first + 1
        if progress:
            progress(done, len(out), time.time() - started)
    return {p: ("\n".join(text), tables) for p, (text, tables) in out.items()}


def split_by_page(item):
    """A paragraph that runs over a page break -> its part on each page. Read together, Docling
    joins such a paragraph and records each page's part as a character span; giving all of it to
    the first page lost a sentence and a number from the next (a petition's p.22: "10,41,411")."""
    if len(item.prov) > 1 and all(pr.charspan for pr in item.prov):
        return [(pr.page_no, item.text[pr.charspan[0]:pr.charspan[1]]) for pr in item.prov]
    return [(item.prov[0].page_no, item.text)]


def runs(pages):
    """Sorted page numbers -> (first, last) runs of consecutive pages, each at most CHUNK_PAGES."""
    result = []
    for p in pages:
        if result and p == result[-1][1] + 1 and p - result[-1][0] < CHUNK_PAGES:
            result[-1][1] = p
        else:
            result.append([p, p])
    return [tuple(r) for r in result]


def to_table(item):
    grid = item.data.grid
    if not grid:
        return None
    n = 0
    while n < len(grid) and any(c.column_header for c in grid[n]):
        n += 1
    # No header row marked: the table has none (a list carried over from the last page, a key-value
    # box), so the headings stay empty and every row is a row. (Taking the first row as headings
    # cost the trial a row on 6 such tables.)
    headings = []
    for j in range(len(grid[0])):
        parts = []
        for r in range(n):
            text = grid[r][j].text.strip()
            if text and (not parts or parts[-1] != text):  # a spanning heading repeats in each column row
                parts.append(text)
        headings.append(" ".join(parts))
    return {"headings": headings, "rows": [[c.text.strip() for c in row] for row in grid[n:]]}
