"""The shapes of the data in ingestion. Every later file reads and writes these.

    PDF ──extract──> ExtractedDoc ──split──> Unit ──chunk──> Chunk ──> embed ──> Chroma
                     ├── text per page       one per section,
                     ├── Table (many)        rule or paragraph
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
# What kind of piece a Unit is. The splitter sets it from whatever it cut on.
UnitType = Literal["section", "definition", "schedule", "rule", "paragraph", "table", "other"]


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
class Unit:
    """One piece of the law as the law itself divides it: a section, a definition, a rule,
    a circular paragraph or a table. Made by the splitters, read by the chunker.
    It holds what the law says; the search decisions (size, context header) come later,
    in Chunk (plans/stage2_splitchunk.md)."""
    unit_type: UnitType
    doc_file: str    # path under docs/, as in docs/manifest.jsonl: the way back to the document
    location: str    # the citation: "section 16", "section 2(52)", "rule 36", "para 4"
    heading: str     # "Eligibility and conditions for taking input tax credit"; "" if none
    text: str        # the current law only, clean: no amendment markers, no old wording
    page_start: int
    page_end: int
    parent: str = ""   # what it sits in: "Chapter V Input Tax Credit"; for a definition, "section 2"
    term: str = ""     # definitions only: the word defined, e.g. "goods", for following one definition to another
    amended_by: list[str] = field(default_factory=list)  # footnotes: "Ins. by Act 8 of 2023, s. 138 (w.e.f. 1-10-2023)"
    history: list[str] = field(default_factory=list)     # old wording ("Prior to substitution, it read ..."), never in `text`
    table_ids: list[str] = field(default_factory=list)   # the tables in or of this unit: the way back to each whole Table
    warnings: list[str] = field(default_factory=list)    # small problems the splitter saw, kept with the unit, never hidden
    # Filled for every splitter the same way, by splitting.finish():
    unit_id: str = ""        # stable across runs: "act-12-of-2017:section-16"
    source_sha256: str = ""  # the PDF version this came from (from the manifest)
    token_count: int = 0     # bge-small tokens in `text`: for the chunker and the answer step's context budget


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
