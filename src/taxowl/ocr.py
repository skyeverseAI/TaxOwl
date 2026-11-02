"""Read one scanned page with Docling + RapidOCR: its text in reading order, and its tables.

Used by the ingestion pipeline for pages without a text layer (fewer than 100 letters), for
corpus files and uploads alike. Chosen 2026-11-02 over Apple's OcrMac (plans/extraction_journey.md,
step 12): on the corpus scans 94.3% against 86.3%, it runs on Linux, and it gives tables on scan
pages. Measured with evals/docling_trial.py; this is the same reading, moved here.

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
built once and reused for every page.
"""

import io

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


def read_page(data, page, name="document.pdf"):
    """OCR page `page` (1-based) of the PDF bytes `data`. Returns (text, tables), where each
    table is {"headings": [...], "rows": [[...], ...]}."""
    from docling.datamodel.base_models import DocumentStream
    from docling_core.types.doc import ListItem, TableItem

    stream = DocumentStream(name=name, stream=io.BytesIO(data))
    doc = converter().convert(stream, page_range=(page, page)).document
    text, tables = [], []
    for item, _ in doc.iterate_items():
        if isinstance(item, TableItem):
            t = to_table(item)
            if t:
                tables.append(t)
        elif getattr(item, "text", ""):
            # Docling keeps a numbered para's number ("2.1", "15.", "(a)") in .marker, not .text; put it
            # back. Bullets ("-", "•") have no letter or digit and are skipped.
            marker = item.marker if isinstance(item, ListItem) else ""
            text.append(f"{marker} {item.text}" if any(c.isalnum() for c in marker or "") else item.text)
    return "\n".join(text), tables


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
