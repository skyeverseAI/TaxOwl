"""The shapes of the data in ingestion. Every later file reads and writes these.

    PDF ──extract.py──> ExtractedDoc ──parsers + chunker──> Chunk ──> embed ──> Chroma
                        ├── text per page
                        ├── Table (many)
                        └── quality report

Kept simple on purpose (agreed 2026-10-27). Things left for v2 if ever needed: a row's
position on the page, and keeping merged cells as spans instead of copying the value down.
"""

from dataclasses import dataclass, field
from typing import Literal

# Fixed choices, so a typo like "circulr" is caught.
DocType = Literal["act", "rules", "circular", "instruction", "notification"]
ChunkKind = Literal["text", "table", "table_row"]
Status = Literal["in_force", "withdrawn", "partly_modified"]


@dataclass
class Table:
    """One table, joined across pages. The master copy: Markdown, HTML and "Heading: value"
    rows are all made from it (plans/plan_ingestion.md, C2)."""
    table_id: str         # "<doc number>:table-<n>", e.g. "238/32/2024-GST:table-1"
    headings: list[str]   # one per column; two-row headings combined: "Amount CGST"
    rows: list[list[str]]  # one list of cell texts per row; a merged cell's value is copied into each row
    row_pages: list[int]  # the page each row is on, so a row can be cited (the table may span pages 8-14)
    reader: Literal["pymupdf", "docling", "vlm"] = "pymupdf"  # vlm: grid from a vision model, words still from the PDF
    html: str = ""        # filled only for a table with a table inside it (133/03/2020): Markdown can't show that


@dataclass
class ExtractedDoc:
    """What one PDF gave us."""
    file: str           # path under docs/, same as in docs/manifest.jsonl
    sha256: str         # from the manifest; tells us whether the PDF changed since last time
    pages: list[str]    # text of each page OUTSIDE tables (pages[0] is page 1), so nothing appears twice
    tables: list[Table] = field(default_factory=list)
    ocr: bool = False   # text came from docs/ocr/ (the 8 scans), not the PDF's own text layer
    # The self-check (C3): each failed check with a short reason, e.g.
    # {"words_dropped": "page 4: 212 words missing"}. Empty means every check passed.
    quality: dict[str, str] = field(default_factory=dict)


@dataclass
class Chunk:
    """One searchable piece, plus the labels to filter and cite it."""
    # The piece itself
    chunk_id: str  # stable, so re-running doesn't make duplicates: "circular:238/32/2024-GST:para-4"
    text: str      # what gets embedded and what the LLM reads
    kind: ChunkKind

    # Which document (copied from docs/manifest.jsonl)
    doc_type: DocType
    doc_number: str  # "238/32/2024-GST", "CGST Act, 2017"
    doc_date: str    # "2024-10-15" (ISO, so it sorts)
    title: str       # circular subject or Act/Rules name; also written into `text` for context
    official_url: str  # we link to the source, we don't re-host it

    # Where in the document, for the citation
    location: str  # "section 16(2)", "rule 36(4)", "para 4"
    page_start: int
    page_end: int

    # Validity: filled in by the withdrawal detector (day 3); until then every circular is in force
    status: Status = "in_force"
    withdrawn_by: str = ""

    # Links and trust
    tax_area: str = "gst"    # room for other tax areas later (plans/fde_plan.md); costs nothing now
    table_id: str = ""       # for table rows: the way back to the whole Table ("search small, read big")
    ocr: bool = False        # text came from OCR, so it's slightly less trustworthy
    quality_ok: bool = True  # False if the self-check flagged the document this chunk came from
    source_sha256: str = ""

    def metadata(self) -> dict[str, str | int | bool]:
        """Every field except id and text, for Chroma, which only stores plain values
        (text, numbers, true/false). Lists such as a table's rows stay in Table."""
        return {k: v for k, v in vars(self).items() if k not in ("chunk_id", "text")}
